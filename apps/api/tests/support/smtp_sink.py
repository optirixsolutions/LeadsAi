"""A real SMTP server on localhost that keeps what it receives and sends nothing onward.

Addresses can make it misbehave in the ways real servers do, so failure paths are real failures
over a real connection. Run it as a module for browser tests, which read messages from a file.
"""

import asyncio
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from email import message_from_bytes, policy
from email.message import EmailMessage
from pathlib import Path
from typing import Any, cast

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import SMTP, Envelope, Session

REFUSE_FOREVER = "refused@"
REFUSE_FOR_NOW = "busy@"
REFUSE_RELAY = "relay@"
# The server takes the whole message, then hangs up without answering.
DROP_AFTER_DATA = "dropped@"


class Sink:
    def __init__(self, record: Path | None = None) -> None:
        self.messages: list[EmailMessage] = []
        self.record = record

    async def handle_RCPT(  # noqa: N802
        self, server: SMTP, session: Session, envelope: Envelope, address: str, options: list[str]
    ) -> str:
        if address.startswith(REFUSE_FOREVER):
            return "550 5.1.1 No such user"
        if address.startswith(REFUSE_RELAY):
            return "550 5.7.1 Relaying denied"
        if address.startswith(REFUSE_FOR_NOW):
            return "451 4.3.0 Try again later"
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server: SMTP, session: Session, envelope: Envelope) -> str:  # noqa: N802
        if any(a.startswith(DROP_AFTER_DATA) for a in envelope.rcpt_tos):
            assert server.transport is not None
            server.transport.abort()
            return "250 OK"
        message = cast(EmailMessage, message_from_bytes(envelope.content, policy=policy.SMTP))  # type: ignore[arg-type]
        self.messages.append(message)
        if self.record is not None:
            with self.record.open("a", encoding="utf-8") as file:
                file.write(json.dumps(_summary(message)) + "\n")
        return "250 OK"


def _summary(message: EmailMessage) -> dict[str, Any]:
    body = message.get_body()
    return {
        "to": message["To"],
        "from": message["From"],
        "subject": message["Subject"],
        "body": body.get_content() if body else "",
    }


@contextmanager
def running_sink(port: int = 0) -> Iterator[tuple[Sink, int]]:
    sink = Sink()
    controller = Controller(sink, hostname="127.0.0.1", port=port or 8125, ready_timeout=10)
    controller.start()
    try:
        yield sink, controller.server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    finally:
        controller.stop()


async def _forever(port: int, record: Path) -> None:
    controller = Controller(Sink(record), hostname="127.0.0.1", port=port)
    controller.start()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(_forever(int(sys.argv[1]), Path(sys.argv[2])))
