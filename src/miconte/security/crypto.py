"""Cryptographic token encryption service using AES-256-GCM."""

import base64
import binascii
import contextlib
import os
import re
from collections.abc import Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from miconte.security.exceptions import DecryptionError, KeyConfigurationError

_CIPHERTEXT_V1_PREFIX = "v1"
_ENVELOPE_PATTERN = re.compile(r"^v1:([a-zA-Z0-9_\-]+):([a-zA-Z0-9_\-=]+):([a-zA-Z0-9_\-=]+)$")


def parse_key_material(key_input: str | bytes) -> bytes:
    """Normalize and validate a 256-bit (32-byte) key from bytes, hex, or base64."""
    if isinstance(key_input, bytes):
        if len(key_input) == 32:
            return key_input
        raise KeyConfigurationError(f"Raw key must be exactly 32 bytes, got {len(key_input)} bytes")

    cleaned = key_input.strip()
    # Try hexadecimal (64 characters)
    if len(cleaned) == 64:
        with contextlib.suppress(ValueError):
            raw = bytes.fromhex(cleaned)
            if len(raw) == 32:
                return raw

    # Try base64 / urlsafe base64
    with contextlib.suppress(ValueError, binascii.Error):
        raw = base64.urlsafe_b64decode(cleaned.encode("ascii"))
        if len(raw) == 32:
            return raw

    # Try standard base64
    with contextlib.suppress(ValueError, binascii.Error):
        raw = base64.b64decode(cleaned.encode("ascii"))
        if len(raw) == 32:
            return raw

    raise KeyConfigurationError(
        "Encryption key must be a valid 256-bit key (32 bytes raw, 64-char hex, or base64)"
    )


class TokenEncryptionService:
    """Service providing authenticated encryption (AES-256-GCM) for OAuth tokens.

    Envelope format:
        v1:<key_id>:<nonce_b64>:<ciphertext_tag_b64>

    Security properties:
    - Authenticated encryption with associated data (AEAD).
    - Unique 96-bit (12-byte) CSPRNG nonce per encryption operation.
    - Versioned envelope supporting transparent key rotation.
    - Context binding via AAD (e.g. user_id + channel_id + token_type).
    - No plaintext tokens or key material exposed in exceptions or logs.
    """

    def __init__(
        self,
        primary_key: str | bytes,
        primary_key_id: str = "k1",
        fallback_keys: Mapping[str, str | bytes] | None = None,
    ) -> None:
        self.primary_key_id = primary_key_id
        self._keys: dict[str, bytes] = {primary_key_id: parse_key_material(primary_key)}

        if fallback_keys:
            for kid, kmat in fallback_keys.items():
                self._keys[kid] = parse_key_material(kmat)

    def encrypt(self, plaintext: str, aad: bytes | None = None) -> str:
        """Encrypt a plaintext string using AES-256-GCM.

        Returns a versioned envelope string: `v1:<key_id>:<nonce_b64>:<ciphertext_tag_b64>`.
        """
        if not plaintext:
            raise ValueError("Plaintext to encrypt cannot be empty")

        key_bytes = self._keys[self.primary_key_id]
        aesgcm = AESGCM(key_bytes)

        # 96-bit nonce generated freshly from OS CSPRNG
        nonce = os.urandom(12)
        plaintext_bytes = plaintext.encode("utf-8")

        ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext_bytes, aad)

        nonce_b64 = base64.urlsafe_b64encode(nonce).decode("ascii")
        ct_b64 = base64.urlsafe_b64encode(ciphertext_with_tag).decode("ascii")

        return f"{_CIPHERTEXT_V1_PREFIX}:{self.primary_key_id}:{nonce_b64}:{ct_b64}"

    def decrypt(self, envelope: str, aad: bytes | None = None) -> str:
        """Decrypt a versioned envelope string.

        Raises DecryptionError if format is invalid, key is missing, or authentication tag fails.
        """
        if not envelope or not isinstance(envelope, str):
            raise DecryptionError("Ciphertext envelope must be a non-empty string")

        match = _ENVELOPE_PATTERN.match(envelope.strip())
        if not match:
            raise DecryptionError("Invalid ciphertext envelope format")

        key_id, nonce_b64, ct_b64 = match.groups()

        key_bytes = self._keys.get(key_id)
        if key_bytes is None:
            raise DecryptionError(f"Unknown encryption key identifier: {key_id}")

        try:
            nonce = base64.urlsafe_b64decode(nonce_b64.encode("ascii"))
            ciphertext_with_tag = base64.urlsafe_b64decode(ct_b64.encode("ascii"))
        except Exception as exc:
            raise DecryptionError("Malformed base64 data in ciphertext envelope") from exc

        if len(nonce) != 12:
            raise DecryptionError("Invalid nonce length for AES-GCM (expected 12 bytes)")

        aesgcm = AESGCM(key_bytes)
        try:
            decrypted_bytes = aesgcm.decrypt(nonce, ciphertext_with_tag, aad)
            return decrypted_bytes.decode("utf-8")
        except InvalidTag as exc:
            raise DecryptionError(
                "Authentication tag verification failed: ciphertext was modified or AAD mismatch"
            ) from exc
        except UnicodeDecodeError as exc:
            raise DecryptionError("Decrypted payload is not valid UTF-8 text") from exc


def build_token_aad(
    user_id: str,
    platform: str,
    external_channel_id: str,
    credential_kind: str,
) -> bytes:
    """Construct deterministic Associated Authenticated Data (AAD) for context binding.

    Prevents ciphertext substitution across different users, platforms, or token types.
    """
    return f"{user_id}:{platform}:{external_channel_id}:{credential_kind}".encode()
