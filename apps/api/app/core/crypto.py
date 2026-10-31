"""Encryption of stored credentials, with AES-256-GCM.

A value is bound to its organization, record, and purpose, so ciphertext copied into another row
does not decrypt. The key is separate from `secret_key`, so that rotating signing keys does not
lose credentials, and stays outside the database.
"""

import base64
import binascii
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

_PREFIX = "v1:"


class CredentialError(Exception):
    """A stored credential cannot be read, usually because the key changed."""


def _key() -> bytes:
    settings = get_settings()
    if settings.credentials_key is not None:
        try:
            key = base64.b64decode(settings.credentials_key.get_secret_value(), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise CredentialError("SALESIQ_CREDENTIALS_KEY is not valid base64") from exc
        if len(key) != 32:
            raise CredentialError("SALESIQ_CREDENTIALS_KEY must be 32 bytes")
        return key
    # Only reached in development and tests: startup refuses this anywhere else.
    return hashlib.sha256(
        b"credentials:" + settings.secret_key.get_secret_value().encode()
    ).digest()


def encrypt(plaintext: str, *, context: str) -> str:
    nonce = os.urandom(12)
    sealed = AESGCM(_key()).encrypt(nonce, plaintext.encode(), context.encode())
    return _PREFIX + base64.b64encode(nonce + sealed).decode()


def decrypt(ciphertext: str, *, context: str) -> str:
    if not ciphertext.startswith(_PREFIX):
        raise CredentialError("Unknown credential format")
    raw = base64.b64decode(ciphertext[len(_PREFIX) :])
    try:
        return AESGCM(_key()).decrypt(raw[:12], raw[12:], context.encode()).decode()
    except InvalidTag as exc:
        raise CredentialError("This credential cannot be read with the current key") from exc
