"""Request correlation IDs, access logging, and baseline security headers."""

import json
import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import error_body
from app.observability.logging import request_id_var

log = logging.getLogger("salesiq.access")

REQUEST_ID_HEADER = "x-request-id"
# Accept caller-supplied IDs only if they are short and boring, to avoid log injection.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

SECURITY_HEADERS = {
    b"x-content-type-options": b"nosniff",
    b"x-frame-options": b"DENY",
    b"referrer-policy": b"strict-origin-when-cross-origin",
    b"cache-control": b"no-store",
}


class RequestContextMiddleware:
    """Pure ASGI middleware so it also wraps streaming responses."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(REQUEST_ID_HEADER.encode(), b"").decode("latin-1")
        rid = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(rid)
        start = time.perf_counter()
        status = 500

        started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status, started
            if message["type"] == "http.response.start":
                started = True
                status = message["status"]
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                headers.append((REQUEST_ID_HEADER.encode(), rid.encode()))
                headers.extend((k, v) for k, v in SECURITY_HEADERS.items() if k not in present)
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            # Unhandled errors would otherwise reach Starlette's outermost handler after the
            # request ID is gone. Answer here so the 500 carries the ID and the envelope.
            log.exception("unhandled_error")
            if started:
                raise
            body = json.dumps(error_body("internal_error", "An unexpected error occurred"))
            await send_wrapper(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send_wrapper({"type": "http.response.body", "body": body.encode()})
        finally:
            log.info(
                "request",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                },
            )
            request_id_var.reset(token)
