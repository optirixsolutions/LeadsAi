"""SSRF controls, against real sockets and a real local HTTP server. Nothing is stubbed."""

import contextlib
import ipaddress
import socket
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.integrations.fetcher import (
    MAX_BYTES,
    FetchBlockedError,
    Fetcher,
    FetchFailedError,
    extract_text,
    is_public_ip,
)

_hits: list[str] = []


class _Site(BaseHTTPRequestHandler):
    def log_message(self, *_: object) -> None:
        pass

    def _send(self, status: int, body: bytes, ctype: str = "text/html", **headers: str) -> None:
        self.send_response(status)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(body)))
        for k, v in headers.items():
            self.send_header(k.replace("_", "-"), v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        _hits.append(self.path)
        host, port = self.server.server_address[:2]
        if self.path == "/robots.txt":
            self._send(200, b"User-agent: *\nDisallow: /private\n", "text/plain")
        elif self.path == "/page":
            self._send(
                200,
                b"<html><head><title>About</title><script>var x='no'</script></head><body>"
                b"<p>Acme sells tools.</p><div hidden>planted one</div>"
                b"<div style='display: none'><b>planted two</b></div>"
                b"<div aria-hidden='true'>planted three</div></body></html>",
            )
        elif self.path == "/big":
            self._send(200, b"<p>" + b"a " * (MAX_BYTES // 2 + 100) + b"</p>")
        elif self.path == "/binary":
            self._send(200, b"\x00\x01", "application/pdf")
        elif self.path == "/redirect-ok":
            self._send(302, b"", location=f"http://site.test:{port}/page")
        elif self.path == "/redirect-ip":
            self._send(302, b"", location=f"http://{host}:{port}/page")
        elif self.path == "/redirect-off-allowlist":
            self._send(302, b"", location="http://elsewhere.example/page")
        elif self.path == "/redirect-loop":
            self._send(302, b"", location="/redirect-loop")
        elif self.path == "/slow-charset":
            self._send(200, b"caf\xc3\xa9 " * 40_000, "text/plain; charset=punycode")
        elif self.path == "/latin":
            self._send(200, b"caf\xe9", "text/plain; charset=latin-1")
        elif self.path == "/nul":
            self._send(200, b"before\x00after", "text/plain")
        elif self.path == "/broken-markup":
            self._send(200, b"<p>kept</p><![if", "text/html")
        elif self.path == "/bad-redirect":
            self._send(302, b"", location="https://[::1")
        elif self.path == "/private":
            self._send(200, b"<p>should not be read</p>")
        else:
            self._send(404, b"nope")


@pytest.fixture(scope="module")
def site() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _local(allow_ip: bool = True) -> Fetcher:
    """Permissive only about what a test server needs: the loopback address and plain HTTP."""
    return Fetcher(
        allow_ip=lambda _: allow_ip,
        schemes=frozenset({"http"}),
        ports=None,
        resolver=lambda _h, _p: ["127.0.0.1"],
    )


def _anyhost(_: str) -> bool:
    return True


def _robots_status_blocks(status: int) -> bool:
    """A real server whose robots.txt answers with `status`."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            pass

        def do_GET(self) -> None:
            code = status if self.path == "/robots.txt" else 200
            self.send_response(code)
            self.send_header("content-type", "text/plain")
            self.send_header("content-length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        _local().fetch(f"http://site.test:{server.server_address[1]}/page", _anyhost)
    except FetchBlockedError:
        return True
    finally:
        server.shutdown()
    return False


# IP literals are refused by policy, so tests reach the server through this name.
def _named(url: str) -> str:
    return url.replace("127.0.0.1", "site.test")


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",  # cloud metadata
        "100.64.0.1",  # carrier-grade NAT
        "0.0.0.0",  # noqa: S104
        "224.0.0.1",
        "::1",
        "fc00::1",
        "fe80::1",
        "::ffff:127.0.0.1",
        "::ffff:169.254.169.254",
        "64:ff9b::7f00:1",  # NAT64 embedding of 127.0.0.1
        "2002:7f00:1::",  # 6to4 embedding of 127.0.0.1
        "::127.0.0.1",  # IPv4-compatible
        "::a9fe:a9fe",
        "::ffff:0:127.0.0.1",
        "fec0::1",  # site-local
        "5f00::1",
    ],
)
def test_internal_addresses_are_not_public(address: str) -> None:
    assert not is_public_ip(address)
    ipaddress.ip_address(address)


def test_public_address_is_allowed() -> None:
    assert is_public_ip("93.184.216.34")
    assert is_public_ip("2606:2800:220:1:248:1893:25c8:1946")


@pytest.mark.parametrize(
    ("url", "why"),
    [
        ("http://example.com/", "HTTPS"),
        ("ftp://example.com/", "HTTPS"),
        ("file:///etc/passwd", "HTTPS"),
        ("https://user:pw@example.com/", "credentials"),
        ("https://example.com:8443/", "port"),
        ("https://127.0.0.1/", "IP addresses"),
        ("https://[::1]/", "IP addresses"),
        ("https://169.254.169.254/latest/meta-data", "IP addresses"),
        ("https://other.example/", "allowlist"),
    ],
)
def test_default_policy_refuses_before_connecting(url: str, why: str) -> None:
    with pytest.raises(FetchBlockedError, match=why):
        Fetcher().fetch(url, lambda host: host == "example.com")


def test_real_loopback_name_is_blocked_by_the_default_ip_policy() -> None:
    fetcher = Fetcher(schemes=frozenset({"http"}), ports=None)
    with pytest.raises(FetchBlockedError, match="not allowed"):
        fetcher.fetch("http://localhost/", _anyhost)


def test_name_with_any_private_answer_is_refused(site: str) -> None:
    """One public and one private answer: the private one must not get a chance."""
    fetcher = Fetcher(
        schemes=frozenset({"http"}),
        ports=None,
        resolver=lambda _h, _p: ["93.184.216.34", "127.0.0.1"],
    )
    before = len(_hits)
    with pytest.raises(FetchBlockedError):
        fetcher.fetch(_named(site) + "/page", _anyhost)
    assert len(_hits) == before, "nothing reached the server"


def test_connects_to_the_checked_address_not_a_new_lookup(site: str) -> None:
    """A rebinding DNS server answers differently each time. Only one lookup per connection."""
    answers = iter([["127.0.0.1"]] + [["10.9.9.9"]] * 9)
    fetcher = Fetcher(
        allow_ip=lambda a: a == "127.0.0.1",
        schemes=frozenset({"http"}),
        ports=None,
        resolver=lambda _h, _p: next(answers),
    )
    # The first lookup is robots.txt; the page lookup then gets the rebound private answer.
    with pytest.raises(FetchBlockedError):
        fetcher.fetch(_named(site) + "/page", _anyhost)


def test_visible_text_only(site: str) -> None:
    page = _local().fetch(_named(site) + "/page", _anyhost)
    assert page.title == "About"
    assert page.text == "Acme sells tools."
    assert not page.truncated


def test_redirect_is_followed_and_rechecked(site: str) -> None:
    page = _local().fetch(_named(site) + "/redirect-ok", _anyhost)
    assert page.text == "Acme sells tools."


def test_redirect_off_the_allowlist_is_blocked(site: str) -> None:
    with pytest.raises(FetchBlockedError, match="allowlist"):
        _local().fetch(_named(site) + "/redirect-off-allowlist", lambda h: h == "site.test")


def test_redirect_to_ip_literal_is_blocked(site: str) -> None:
    with pytest.raises(FetchBlockedError, match="IP addresses"):
        _local().fetch(_named(site) + "/redirect-ip", _anyhost)


def test_redirect_loop_stops(site: str) -> None:
    with pytest.raises(FetchFailedError, match="too many"):
        _local().fetch(_named(site) + "/redirect-loop", _anyhost)


def test_robots_disallow_is_honored(site: str) -> None:
    before = _hits.count("/private")
    with pytest.raises(FetchBlockedError, match=r"robots\.txt"):
        _local().fetch(_named(site) + "/private", _anyhost)
    assert _hits.count("/private") == before


def test_size_is_bounded(site: str) -> None:
    page = _local().fetch(_named(site) + "/big", _anyhost)
    assert page.truncated
    assert len(page.text) <= 20_000


def test_non_text_is_refused(site: str) -> None:
    with pytest.raises(FetchFailedError, match="text and HTML"):
        _local().fetch(_named(site) + "/binary", _anyhost)


def test_http_errors_are_reported(site: str) -> None:
    with pytest.raises(FetchFailedError, match="404"):
        _local().fetch(_named(site) + "/missing", _anyhost)


def test_nested_hidden_markup_stays_hidden() -> None:
    _, text = extract_text("<div hidden><div>a</div><div>b</div></div><p>shown</p><br><p>too</p>")
    assert text == "shown too"


@pytest.mark.parametrize(
    "style", ["display:\tnone", "display\n:none", "font-size: 0", "opacity:0", "VISIBILITY: HIDDEN"]
)
def test_more_ways_of_hiding_text_are_stripped(style: str) -> None:
    _, text = extract_text(f"<div style='{style}'>planted</div><p>shown</p>")
    assert text == "shown"


def test_dangerous_charset_is_not_used(site: str) -> None:
    started = time.perf_counter()
    page = _local().fetch(_named(site) + "/slow-charset", _anyhost)
    assert time.perf_counter() - started < 5
    assert page.text.startswith("caf\u00e9")


def test_declared_common_charset_is_used(site: str) -> None:
    assert _local().fetch(_named(site) + "/latin", _anyhost).text == "caf\u00e9"


def test_nul_bytes_are_removed(site: str) -> None:
    assert "\x00" not in _local().fetch(_named(site) + "/nul", _anyhost).text


def test_broken_markup_keeps_what_was_readable(site: str) -> None:
    assert _local().fetch(_named(site) + "/broken-markup", _anyhost).text == "kept"


def test_malformed_redirect_is_a_clean_failure(site: str) -> None:
    with pytest.raises(FetchFailedError, match="invalid redirect"):
        _local().fetch(_named(site) + "/bad-redirect", _anyhost)


@pytest.mark.parametrize(
    "url",
    ["https://" + "a" * 64 + ".example/", "https://a..example/", "https://xn--example-.com/"],
)
def test_malformed_hosts_are_clean_refusals(url: str) -> None:
    with pytest.raises(FetchBlockedError):
        Fetcher().fetch(url, _anyhost)


def test_overlong_url_is_refused() -> None:
    with pytest.raises(FetchBlockedError, match="too long"):
        Fetcher().fetch("https://example.com/" + "a" * 3000, _anyhost)


@pytest.fixture
def dripping_server() -> Iterator[str]:
    """Never finishes its headers: sends an endless series of 100 Continue responses."""
    listener = socket.create_server(("127.0.0.1", 0))
    stop = threading.Event()

    def serve() -> None:
        listener.settimeout(0.2)
        conns = []
        while not stop.is_set():
            with contextlib.suppress(TimeoutError):
                conn, _ = listener.accept()
                conns.append(conn)
            for conn in conns:
                with contextlib.suppress(OSError):
                    conn.sendall(b"HTTP/1.1 100 Continue\r\n\r\n")
        for conn in conns:
            conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield f"http://site.test:{listener.getsockname()[1]}"
    stop.set()
    thread.join()
    listener.close()


def test_deadline_stops_a_server_that_never_finishes_its_headers(dripping_server: str) -> None:
    fetcher = Fetcher(
        allow_ip=lambda _: True,
        schemes=frozenset({"http"}),
        ports=None,
        resolver=lambda _h, _p: ["127.0.0.1"],
        deadline_s=1.0,
    )
    started = time.perf_counter()
    with pytest.raises(FetchFailedError, match="too long"):
        fetcher.fetch(dripping_server + "/page", _anyhost)
    assert time.perf_counter() - started < 4


def test_robots_server_error_fails_closed() -> None:
    assert _robots_status_blocks(503)


def test_robots_not_found_means_no_rules() -> None:
    assert not _robots_status_blocks(404)
