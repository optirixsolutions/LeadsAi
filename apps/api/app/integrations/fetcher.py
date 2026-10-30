"""SSRF-resistant page fetcher for research evidence. Fetched text is untrusted data.

Controls: the caller's host allowlist is checked on every hop, HTTPS on port 443 only, no
credentials or IP literals in URLs, and no cookies or auth headers are ever sent. Every address
a name resolves to must be public, and the socket connects to the address that was checked, so
a second DNS answer cannot redirect it (DNS rebinding). TLS is still verified for the hostname.
Redirects, size, and total time are bounded, with the deadline enforced on every socket read
and write. robots.txt is honored, and fails closed when it cannot be read.
"""

import codecs
import contextlib
import ipaddress
import socket
import ssl
import time
import urllib.robotparser
from collections.abc import Callable, Iterable
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from html.parser import HTMLParser

import httpcore
import httpx

from app.core.errors import AppError

MAX_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 20_000
MAX_REDIRECTS = 3
MAX_URL_CHARS = 2048
DEADLINE_S = 15.0
OP_TIMEOUT_S = 5.0
USER_AGENT = "SalesIQ-Research/0.1"
_TEXT_TYPES = ("text/html", "text/plain", "application/xhtml+xml")
_REDIRECTS = (301, 302, 303, 307, 308)
# A site chooses its own charset, and some Python codecs take quadratic time. Anything else is
# read as UTF-8.
_CHARSETS = frozenset({"utf-8", "ascii", "iso8859-1", "iso8859-15", "cp1252", "utf-16"})
_GLOBAL_UNICAST_V6 = ipaddress.ip_network("2000::/3")
# Prefixes that embed an IPv4 address, which could otherwise smuggle a private one.
_EMBEDDING_V6 = tuple(
    ipaddress.ip_network(n) for n in ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32")
)


class FetchBlockedError(AppError):
    """Refused by policy before or during the request."""

    status_code = 422
    code = "fetch_blocked"


class FetchFailedError(AppError):
    """The target could not be read."""

    status_code = 502
    code = "fetch_failed"


def is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip not in _GLOBAL_UNICAST_V6 or any(ip in net for net in _EMBEDDING_V6):
            return False
    return ip.is_global and not ip.is_multicast


_BLOCKED_ADDRESS = "That address is not allowed or could not be found"
# Absolute time.monotonic() limit for the current fetch, read by every socket operation.
_deadline: ContextVar[float | None] = ContextVar("fetch_deadline", default=None)


def _within_deadline(timeout: float | None) -> float | None:
    deadline = _deadline.get()
    if deadline is None:
        return timeout
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise httpcore.ReadTimeout("fetch deadline passed")
    return remaining if timeout is None else min(timeout, remaining)


class _DeadlineStream(httpcore.NetworkStream):
    """Applies the fetch deadline per socket call, so slow-drip headers cannot outlast it."""

    def __init__(self, inner: httpcore.NetworkStream) -> None:
        self._inner = inner

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return self._inner.read(max_bytes, _within_deadline(timeout))

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self._inner.write(buffer, _within_deadline(timeout))

    def close(self) -> None:
        self._inner.close()

    def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.NetworkStream:
        return _DeadlineStream(
            self._inner.start_tls(ssl_context, server_hostname, _within_deadline(timeout))
        )

    def get_extra_info(self, info: str) -> object:
        return self._inner.get_extra_info(info)


def _system_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as exc:
        # Same message as a blocked address, so errors cannot be used to map internal names.
        raise FetchBlockedError(_BLOCKED_ADDRESS) from exc
    return [str(info[4][0]) for info in infos]


class _PinnedBackend(httpcore.SyncBackend):
    """Checks every resolved address, then connects to one of those exact addresses."""

    def __init__(
        self, resolver: Callable[[str, int], list[str]], allow_ip: Callable[[str], bool]
    ) -> None:
        self._resolver = resolver
        self._allow_ip = allow_ip

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        addresses = self._resolver(host, port)
        if not addresses or not all(self._allow_ip(a) for a in addresses):
            raise FetchBlockedError(_BLOCKED_ADDRESS)
        return _DeadlineStream(
            super().connect_tcp(
                addresses[0], port, _within_deadline(timeout), local_address, socket_options
            )
        )


class _TextExtractor(HTMLParser):
    """Visible text only. Hidden elements are a common place to plant instructions."""

    _SKIP = frozenset({"script", "style", "noscript", "template", "svg", "iframe", "object"})
    _VOID = frozenset(
        {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "source",
            "wbr",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title: str | None = None
        self._in_title = False
        self._skip_tag: str | None = None
        self._skip_depth = 0

    @staticmethod
    def _hidden(attrs: list[tuple[str, str | None]]) -> bool:
        a = {k: (v or "") for k, v in attrs}
        style = "".join(a.get("style", "").split()).lower()
        return (
            "hidden" in a
            or a.get("aria-hidden", "").lower() == "true"
            or "display:none" in style
            or "visibility:hidden" in style
            or "font-size:0" in style
            or "opacity:0" in style
        )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_tag:
            if tag == self._skip_tag:
                self._skip_depth += 1
            return
        if tag == "title" and self.title is None:
            self._in_title = True
            return
        if tag in self._VOID:
            return
        if tag in self._SKIP or self._hidden(attrs):
            self._skip_tag, self._skip_depth = tag, 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if self._skip_tag == tag:
            self._skip_depth -= 1
            if self._skip_depth == 0:
                self._skip_tag = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title = data.strip()[:300] or None
        elif not self._skip_tag and data.strip():
            self.parts.append(data.strip())


def extract_text(html: str) -> tuple[str | None, str]:
    parser = _TextExtractor()
    with contextlib.suppress(AssertionError):  # html.parser asserts on some broken markup.
        parser.feed(html)
    return parser.title, " ".join(parser.parts)


def _safe_charset(content_type_params: str) -> str:
    declared = content_type_params.partition("charset=")[2].split(";")[0].strip(" \"'")
    try:
        name = codecs.lookup(declared).name if declared else "utf-8"
    except (LookupError, ValueError):
        return "utf-8"
    return name if name in _CHARSETS else "utf-8"


@dataclass(frozen=True)
class FetchedPage:
    url: str
    title: str | None
    text: str
    truncated: bool


class Fetcher:
    """`allow_ip`, `schemes`, and `ports` exist so tests can reach a local server."""

    def __init__(
        self,
        *,
        allow_ip: Callable[[str], bool] = is_public_ip,
        resolver: Callable[[str, int], list[str]] = _system_resolver,
        schemes: frozenset[str] = frozenset({"https"}),
        ports: frozenset[int] | None = frozenset({443}),
        deadline_s: float = DEADLINE_S,
    ) -> None:
        self._deadline_s = deadline_s
        self._schemes = schemes
        self._ports = ports
        self._pool = httpcore.ConnectionPool(
            ssl_context=ssl.create_default_context(),
            network_backend=_PinnedBackend(resolver, allow_ip),
            max_connections=10,
            keepalive_expiry=5.0,
            retries=0,
        )

    def _validated(self, raw: str, host_allowed: Callable[[str], bool]) -> httpx.URL:
        if len(raw) > MAX_URL_CHARS:
            raise FetchBlockedError("That URL is too long")
        try:
            url = httpx.URL(raw)
            host = url.host.lower().rstrip(".")
            port = url.port or {"https": 443, "http": 80}.get(url.scheme)
        except (httpx.InvalidURL, ValueError) as exc:  # IDNA failures are ValueErrors.
            raise FetchBlockedError("That URL is not valid") from exc
        if url.scheme not in self._schemes:
            raise FetchBlockedError("Only HTTPS URLs can be fetched")
        if url.userinfo:
            raise FetchBlockedError("URLs with credentials are not allowed")
        if self._ports is not None and port not in self._ports:
            raise FetchBlockedError("That port is not allowed")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise FetchBlockedError("IP addresses cannot be fetched; use the company domain")
        if not host or not host_allowed(host):
            raise FetchBlockedError("That site is not on the allowlist for this lead")
        return url.copy_with(fragment=None)

    def _next_hop(
        self, url: httpx.URL, location: str, host_allowed: Callable[[str], bool]
    ) -> httpx.URL:
        try:
            target = str(url.join(location))
        except (httpx.InvalidURL, ValueError) as exc:
            raise FetchFailedError("That site sent an invalid redirect") from exc
        return self._validated(target, host_allowed)

    def _read(self, url: httpx.URL, limit: int) -> tuple[int, dict[str, str], bytes, bool]:
        timeouts = {
            "connect": OP_TIMEOUT_S,
            "read": OP_TIMEOUT_S,
            "write": OP_TIMEOUT_S,
            "pool": OP_TIMEOUT_S,
        }
        headers = [
            (b"host", url.netloc),
            (b"user-agent", USER_AGENT.encode()),
            (b"accept", b"text/html, text/plain"),
        ]
        body = bytearray()
        truncated = False
        try:
            with self._pool.stream(
                "GET", str(url), headers=headers, extensions={"timeout": timeouts}
            ) as r:
                head = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in r.headers}
                for chunk in r.iter_stream():
                    body += chunk
                    if len(body) >= limit:
                        truncated = True
                        break
                return r.status, head, bytes(body[:limit]), truncated
        except httpcore.TimeoutException as exc:
            raise FetchFailedError("The site took too long to respond") from exc
        except httpcore.ConnectError as exc:
            # The TLS certificate check fails here too; there is no way to turn it off.
            raise FetchFailedError("Could not connect securely to that site") from exc
        except httpcore.NetworkError as exc:
            raise FetchFailedError("The connection to that site failed") from exc
        except httpcore.ProtocolError as exc:
            raise FetchFailedError("That site sent an invalid response") from exc

    def _robots_allow(self, url: httpx.URL, host_allowed: Callable[[str], bool]) -> bool:
        """Per RFC 9309: 4xx means no rules; a server error or no answer means do not crawl."""
        robots = url.copy_with(raw_path=b"/robots.txt")
        for _ in range(MAX_REDIRECTS + 1):
            status, head, body, _ = self._read(robots, 256_000)
            if status in _REDIRECTS and "location" in head:
                robots = self._next_hop(robots, head["location"], host_allowed)
                continue
            if status == 200:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(body.decode("utf-8", "replace").splitlines())
                return parser.can_fetch(USER_AGENT, str(url))
            return 400 <= status < 500
        return False

    def fetch(self, raw_url: str, host_allowed: Callable[[str], bool]) -> FetchedPage:
        url = self._validated(raw_url, host_allowed)
        token = _deadline.set(time.monotonic() + self._deadline_s)
        try:
            for _ in range(MAX_REDIRECTS + 1):
                if not self._robots_allow(url, host_allowed):
                    raise FetchBlockedError("That site's robots.txt does not allow this page")
                status, head, body, truncated = self._read(url, MAX_BYTES)
                if status in _REDIRECTS and "location" in head:
                    url = self._next_hop(url, head["location"], host_allowed)
                    continue
                if status != 200:
                    raise FetchFailedError(f"The site answered with status {status}")
                return self._page(url, head, body, truncated)
            raise FetchFailedError("That page redirected too many times")
        finally:
            _deadline.reset(token)

    @staticmethod
    def _page(url: httpx.URL, head: dict[str, str], body: bytes, truncated: bool) -> FetchedPage:
        ctype, _, params = head.get("content-type", "").partition(";")
        if ctype.strip().lower() not in _TEXT_TYPES:
            raise FetchFailedError("Only text and HTML pages can be used as evidence")
        decoded = body.decode(_safe_charset(params), "replace")
        title, text = (
            (None, decoded) if ctype.strip().lower() == "text/plain" else extract_text(decoded)
        )
        text = " ".join(text.replace("\x00", " ").split())
        if not text:
            raise FetchFailedError("That page has no readable text")
        return FetchedPage(
            url=str(url),
            title=title,
            text=text[:MAX_TEXT_CHARS],
            truncated=truncated or len(text) > MAX_TEXT_CHARS,
        )


@lru_cache
def get_fetcher() -> Fetcher:
    return Fetcher()
