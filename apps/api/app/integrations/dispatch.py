"""How an approved email leaves: SMTP, or nothing at all.

An adapter only reports what the server said. Authorization happens before it is called, in
`dispatch_service`. "Accepted" means a server took responsibility, not that a person received it.
"""

import ipaddress
import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from app.core.config import get_settings
from app.integrations.fetcher import is_public_ip
from app.models import DeliveryStatus

# The ports mail submission uses, so a connection cannot be pointed at other services. Not 465,
# which starts with TLS at once, while this speaks STARTTLS.
_EXTERNAL_PORTS = (25, 587, 2525)


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    sender_name: str
    sender_email: str
    subject: str
    body: str
    # What a mail provider's one-click request posts to. The link in the body opens a page.
    one_click_url: str
    message_id: str | None = None


@dataclass(frozen=True)
class SmtpTarget:
    host: str
    port: int
    starttls: bool
    username: str | None = None
    password: str | None = None
    # Chosen by a tenant, as opposed to by whoever runs this server, so it is trusted less.
    from_connection: bool = False


@dataclass(frozen=True)
class Outcome:
    status: DeliveryStatus
    message_id: str | None = None
    category: str | None = None


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def server_target() -> SmtpTarget:
    settings = get_settings()
    password = settings.dispatch_smtp_password
    return SmtpTarget(
        host=settings.dispatch_smtp_host,
        port=settings.dispatch_smtp_port,
        starttls=settings.dispatch_smtp_starttls,
        username=settings.dispatch_smtp_username,
        password=password.get_secret_value() if password else None,
    )


def target_blocker(host: str, port: int, starttls: bool) -> str | None:
    """For an address a tenant chose. This machine's own services are off limits to a tenant, except
    in development. Anything else is a real server, and needs the deliberate switch and TLS."""
    settings = get_settings()
    if is_loopback(host):
        return (
            None if settings.environment in ("development", "test") else "connection_host_refused"
        )
    if not settings.dispatch_allow_external:
        return "external_not_allowed"
    if port not in _EXTERNAL_PORTS:
        return "connection_host_refused"
    return None if starttls else "connection_needs_tls"


def unavailable_reason(target: SmtpTarget | None = None) -> str | None:
    """Why nothing can be sent right now, or None. Checked again at the moment of every send."""
    settings = get_settings()
    if settings.dispatch_adapter != "smtp":
        return "dispatch_disabled"
    if target is not None and target.from_connection:
        return target_blocker(target.host, target.port, target.starttls)
    host = target.host if target else settings.dispatch_smtp_host
    if not is_loopback(host) and not settings.dispatch_allow_external:
        return "external_not_allowed"
    return None


def _connect(target: SmtpTarget) -> smtplib.SMTP | None:
    """A tenant's hostname is resolved once and that address is used, so a name that later points
    somewhere internal cannot get past the check. None means it may not be contacted."""
    timeout = get_settings().dispatch_smtp_timeout_s
    address = target.host
    if target.from_connection and not is_loopback(target.host):
        try:
            found = socket.getaddrinfo(target.host, target.port, type=socket.SOCK_STREAM)
        except (OSError, UnicodeError):
            return None
        addresses = [str(info[4][0]) for info in found]
        if not addresses or not all(is_public_ip(a) for a in addresses):
            return None
        address = addresses[0]
    client = smtplib.SMTP(address, target.port, timeout=timeout)
    # TLS checks the certificate against this, and it must be the name and not the address.
    client._host = target.host  # type: ignore[attr-defined]
    return client


def _open_session(client: smtplib.SMTP, target: SmtpTarget) -> None:
    client.ehlo()
    if target.starttls:
        client.starttls(context=ssl.create_default_context())
        client.ehlo()
    if target.username and target.password:
        client.login(target.username, target.password)


def probe_smtp(target: SmtpTarget) -> str | None:
    """Connect and log in, sending nothing. Returns what is wrong, or None. This works with
    sending turned off, because that is when someone would want to try a new connection."""
    if target.from_connection and (
        reason := target_blocker(target.host, target.port, target.starttls)
    ):
        return reason
    try:
        client = _connect(target)
    except (OSError, smtplib.SMTPException):
        return "connection_failed"
    if client is None:
        return "connection_host_refused"
    try:
        _open_session(client, target)
        client.noop()
    except smtplib.SMTPAuthenticationError:
        return "login_refused"
    except (OSError, smtplib.SMTPException):
        return "session_failed"
    finally:
        try:
            client.quit()
        except (OSError, smtplib.SMTPException):
            client.close()
    return None


def build_message(email: OutgoingEmail) -> EmailMessage:
    message = EmailMessage()
    message["From"] = formataddr((email.sender_name, email.sender_email))
    message["To"] = email.to
    message["Subject"] = email.subject
    message["Date"] = formatdate(usegmt=True)
    message["Message-ID"] = email.message_id or make_msgid(
        domain=email.sender_email.rpartition("@")[2]
    )
    message["List-Unsubscribe"] = f"<{email.one_click_url}>"
    message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    message.set_content(email.body)
    return message


def _refused(code: int, category: str, message_id: str) -> Outcome:
    status = DeliveryStatus.rejected if code >= 500 else DeliveryStatus.failed
    return Outcome(status, message_id, category)


def _recipient_refusal(code: int, response: bytes, message_id: str) -> Outcome:
    """Only these say the address itself is bad. 5.7.x is about policy, such as a relay refusing
    this sender, and treating that as a bounce would suppress good addresses in bulk."""
    if code in (550, 551, 553) and b"5.7." not in response:
        return Outcome(DeliveryStatus.rejected, message_id, "recipient_refused")
    category = "recipient_refused" if code < 500 else "server_refused"
    return Outcome(DeliveryStatus.failed, message_id, category)


def send_smtp(email: OutgoingEmail, target: SmtpTarget | None = None) -> Outcome:
    """Anything that goes wrong after the message starts going out is reported as unknown, since
    the server may already have it. A retry there could reach the same person twice."""
    target = target or server_target()
    if unavailable_reason(target):
        return Outcome(DeliveryStatus.failed, category="connection_host_refused")
    message = build_message(email)
    message_id = str(message["Message-ID"])
    try:
        client = _connect(target)
    except (OSError, smtplib.SMTPException):
        return Outcome(DeliveryStatus.failed, category="connection_failed")
    if client is None:
        return Outcome(DeliveryStatus.failed, category="connection_host_refused")
    try:
        try:
            _open_session(client, target)
        except (OSError, smtplib.SMTPException):
            return Outcome(DeliveryStatus.failed, category="session_failed")
        try:
            client.send_message(message)
        except smtplib.SMTPRecipientsRefused as exc:
            code, response = next(iter(exc.recipients.values()), (500, b""))
            return _recipient_refusal(code, response, message_id)
        except smtplib.SMTPSenderRefused as exc:
            # About the sender and not this person, so it says nothing against the address.
            return Outcome(DeliveryStatus.failed, message_id, f"sender_refused_{exc.smtp_code}")
        except smtplib.SMTPDataError as exc:
            return _refused(exc.smtp_code, "message_refused", message_id)
        except (OSError, smtplib.SMTPException):
            return Outcome(DeliveryStatus.unknown, message_id, "connection_lost")
        return Outcome(DeliveryStatus.accepted, message_id)
    finally:
        try:
            client.quit()
        except (OSError, smtplib.SMTPException):
            client.close()
