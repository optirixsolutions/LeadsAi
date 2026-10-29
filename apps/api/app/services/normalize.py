"""Deterministic field normalization used for storage and duplicate detection."""

import re
from urllib.parse import urlsplit

from email_validator import EmailNotValidError, validate_email

# Addresses at these providers say nothing about the person's company.
FREE_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "icloud.com",
        "me.com",
        "aol.com",
        "proton.me",
        "protonmail.com",
        "gmx.com",
        "mail.com",
        "yandex.com",
    }
)

_DOMAIN = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def normalize_email(raw: str | None) -> str | None:
    """Lowercased, syntax-checked email, or None if blank. Raises ValueError if invalid."""
    if raw is None or not raw.strip():
        return None
    try:
        info = validate_email(raw.strip(), check_deliverability=False)
    except EmailNotValidError as exc:
        raise ValueError(f"Invalid email: {raw.strip()[:80]}") from exc
    return info.normalized.lower()


def normalize_domain(raw: str | None) -> str | None:
    """Bare hostname from a domain or URL (`https://www.Acme.com/x` -> `acme.com`)."""
    if raw is None or not raw.strip():
        return None
    value = raw.strip().lower()
    host = urlsplit(value if "://" in value else f"//{value}").hostname or ""
    host = host.removeprefix("www.").rstrip(".")
    return host if _DOMAIN.match(host) else None


def company_domain_from_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    domain = email.rpartition("@")[2]
    return None if domain in FREE_EMAIL_DOMAINS else normalize_domain(domain)


def split_full_name(full: str) -> tuple[str | None, str | None]:
    parts = full.strip().split(None, 1)
    if not parts:
        return None, None
    return parts[0], (parts[1] if len(parts) > 1 else None)


def parse_tags(raw: str) -> list[str]:
    """Tags in a CSV cell are separated by `;` or `,`."""
    return [t for t in (p.strip().lower() for p in re.split(r"[;,]", raw)) if t]
