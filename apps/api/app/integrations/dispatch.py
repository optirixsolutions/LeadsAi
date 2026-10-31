"""How an approved email leaves: SMTP, or nothing at all.

An adapter only reports what the server said. Authorization happens before it is called, in
`dispatch_service`. "Accepted" means a server took responsibility, not that a person received it.
"""

import ipaddress
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from app.core.config import get_settings
from app.models import DeliveryStatus


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    sender_name: str
    sender_email: str
    subject: str
    body: str
    # What a mail provider's one-click request posts to. The link in the body opens a page.
    one_click_url: str


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


def unavailable_reason() -> str | None:
    """Why nothing can be sent right now, or None. Checked again at the moment of every send."""
    settings = get_settings()
    if settings.dispatch_adapter != "smtp":
        return "dispatch_disabled"
    if not is_loopback(settings.dispatch_smtp_host) and not settings.dispatch_allow_external:
        return "external_not_allowed"
    return None


def build_message(email: OutgoingEmail) -> EmailMessage:
    message = EmailMessage()
    message["From"] = formataddr((email.sender_name, email.sender_email))
    message["To"] = email.to
    message["Subject"] = email.subject
    message["Date"] = formatdate(usegmt=True)
    message["Message-ID"] = make_msgid(domain=email.sender_email.rpartition("@")[2])
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


def send_smtp(email: OutgoingEmail) -> Outcome:
    """Anything that goes wrong after the message starts going out is reported as unknown, since
    the server may already have it. A retry there could reach the same person twice."""
    settings = get_settings()
    message = build_message(email)
    message_id = str(message["Message-ID"])
    try:
        client = smtplib.SMTP(
            settings.dispatch_smtp_host,
            settings.dispatch_smtp_port,
            timeout=settings.dispatch_smtp_timeout_s,
        )
    except (OSError, smtplib.SMTPException):
        return Outcome(DeliveryStatus.failed, category="connection_failed")
    try:
        try:
            client.ehlo()
            if settings.dispatch_smtp_starttls:
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            if settings.dispatch_smtp_username and settings.dispatch_smtp_password:
                client.login(
                    settings.dispatch_smtp_username,
                    settings.dispatch_smtp_password.get_secret_value(),
                )
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
