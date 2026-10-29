"""Outbound email adapter.

No real provider is configured yet. `LogMailer` is development-only (config validation
blocks it elsewhere); `MemoryMailer` is for tests. Nothing here sends real email.
"""

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    body: str


class Mailer(Protocol):
    def send(self, email: Email) -> None: ...


class LogMailer:
    def send(self, email: Email) -> None:
        # Development convenience: the body contains the action link.
        log.info("dev_email", extra={"to": email.to, "subject": email.subject, "body": email.body})


@dataclass
class MemoryMailer:
    outbox: list[Email] = field(default_factory=list)

    def send(self, email: Email) -> None:
        self.outbox.append(email)


class DisabledMailer:
    def send(self, email: Email) -> None:
        log.warning("email_not_sent_no_provider", extra={"subject": email.subject})


@lru_cache
def get_mailer() -> Mailer:
    kind = get_settings().mailer
    if kind == "log":
        return LogMailer()
    if kind == "memory":
        return MemoryMailer()
    return DisabledMailer()
