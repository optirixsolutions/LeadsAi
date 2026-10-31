"""Password hashing, opaque tokens, and CSRF token derivation."""

import base64
import hashlib
import hmac
import secrets
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

# argon2-cffi defaults follow the RFC 9106 low-memory profile.
_hasher = PasswordHasher()
# Verified against when the user does not exist, so login timing does not reveal accounts.
_DUMMY_HASH = _hasher.hash("timing-equalizer-not-a-password")

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_token() -> str:
    """256-bit URL-safe random token. Only its digest is stored."""
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token_for(session_token: str) -> str:
    """CSRF token bound to the session; a stolen CSRF cookie is useless with another session."""
    key = get_settings().secret_key.get_secret_value().encode()
    return hmac.new(key, b"csrf:" + session_token.encode(), hashlib.sha256).hexdigest()


def csrf_matches(session_token: str, presented: str | None) -> bool:
    return presented is not None and hmac.compare_digest(csrf_token_for(session_token), presented)


def _unsubscribe_mac(org_id: uuid.UUID, delivery_id: uuid.UUID) -> bytes:
    key = get_settings().secret_key.get_secret_value().encode()
    message = b"unsubscribe:" + org_id.bytes + delivery_id.bytes
    return hmac.new(key, message, hashlib.sha256).digest()[:16]


def unsubscribe_token(org_id: uuid.UUID, delivery_id: uuid.UUID) -> str:
    """Names a delivery and not an address, so links in logs reveal nothing about the person.
    It never expires, because an opt-out link in an old email still has to work."""
    raw = org_id.bytes + delivery_id.bytes + _unsubscribe_mac(org_id, delivery_id)
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def read_unsubscribe_token(token: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except ValueError:
        return None
    if len(raw) != 48:
        return None
    org_id, delivery_id = uuid.UUID(bytes=raw[:16]), uuid.UUID(bytes=raw[16:32])
    if not hmac.compare_digest(_unsubscribe_mac(org_id, delivery_id), raw[32:]):
        return None
    return org_id, delivery_id
