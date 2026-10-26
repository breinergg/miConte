"""Unit tests for AES-256-GCM token encryption service."""

import base64
import os
import uuid

import pytest

from miconte.security.crypto import TokenEncryptionService, build_token_aad, parse_key_material
from miconte.security.exceptions import DecryptionError, KeyConfigurationError


@pytest.fixture
def raw_key_32() -> bytes:
    return os.urandom(32)


@pytest.fixture
def hex_key_64() -> str:
    return os.urandom(32).hex()


@pytest.fixture
def b64_key_44() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


@pytest.fixture
def crypto_service(raw_key_32: bytes) -> TokenEncryptionService:
    return TokenEncryptionService(primary_key=raw_key_32, primary_key_id="k1")


def test_key_material_parsing(raw_key_32: bytes, hex_key_64: str, b64_key_44: str) -> None:
    assert parse_key_material(raw_key_32) == raw_key_32
    assert parse_key_material(hex_key_64) == bytes.fromhex(hex_key_64)
    assert parse_key_material(b64_key_44) == base64.urlsafe_b64decode(b64_key_44.encode("ascii"))

    with pytest.raises(KeyConfigurationError):
        parse_key_material(b"too_short")

    with pytest.raises(KeyConfigurationError):
        parse_key_material("invalid_hex_string_that_is_not_length_64")


def test_encrypt_decrypt_roundtrip(crypto_service: TokenEncryptionService) -> None:
    plaintext = "ya29.a0AfH6SMB_secret_access_token_1234567890"
    envelope = crypto_service.encrypt(plaintext)

    assert envelope.startswith("v1:k1:")
    decrypted = crypto_service.decrypt(envelope)
    assert decrypted == plaintext


def test_fresh_nonce_per_encryption(crypto_service: TokenEncryptionService) -> None:
    plaintext = "sample_refresh_token_xyz"
    env1 = crypto_service.encrypt(plaintext)
    env2 = crypto_service.encrypt(plaintext)

    assert env1 != env2
    parts1 = env1.split(":")
    parts2 = env2.split(":")
    # Nonce and ciphertext must both differ due to unique CSPRNG nonces
    assert parts1[2] != parts2[2]
    assert parts1[3] != parts2[3]

    assert crypto_service.decrypt(env1) == plaintext
    assert crypto_service.decrypt(env2) == plaintext


def test_aad_context_binding_protection(crypto_service: TokenEncryptionService) -> None:
    user_id_1 = str(uuid.uuid4())
    user_id_2 = str(uuid.uuid4())
    channel_id = "UC_TEST_CHANNEL_123"

    aad_user1 = build_token_aad(
        user_id=user_id_1,
        platform="youtube",
        external_channel_id=channel_id,
        credential_kind="access",
    )
    aad_user2 = build_token_aad(
        user_id=user_id_2,
        platform="youtube",
        external_channel_id=channel_id,
        credential_kind="access",
    )

    token = "ya29.user1_confidential_token"
    envelope = crypto_service.encrypt(token, aad=aad_user1)

    # Valid context decrypts
    assert crypto_service.decrypt(envelope, aad=aad_user1) == token

    # Different user context fails
    with pytest.raises(DecryptionError, match="Authentication tag verification failed"):
        crypto_service.decrypt(envelope, aad=aad_user2)

    # Missing AAD fails
    with pytest.raises(DecryptionError, match="Authentication tag verification failed"):
        crypto_service.decrypt(envelope, aad=None)


def test_ciphertext_tamper_detection(crypto_service: TokenEncryptionService) -> None:
    token = "confidential_refresh_token"
    envelope = crypto_service.encrypt(token)
    parts = envelope.split(":")
    # Flip last character of ciphertext/tag payload
    ct_b64 = parts[3]
    altered_char = "B" if ct_b64[-1] == "A" else "A"
    tampered_envelope = f"{parts[0]}:{parts[1]}:{parts[2]}:{ct_b64[:-1]}{altered_char}"

    with pytest.raises(DecryptionError):
        crypto_service.decrypt(tampered_envelope)


def test_malformed_envelope_detection(crypto_service: TokenEncryptionService) -> None:
    with pytest.raises(DecryptionError, match="non-empty string"):
        crypto_service.decrypt("")

    with pytest.raises(DecryptionError, match="Invalid ciphertext envelope format"):
        crypto_service.decrypt("invalid:envelope:missing_parts")

    with pytest.raises(DecryptionError, match="Invalid ciphertext envelope format"):
        crypto_service.decrypt("v2:k1:nonce:tag")


def test_key_rotation_and_fallback_keys(raw_key_32: bytes) -> None:
    key_old = raw_key_32
    key_new = os.urandom(32)

    service_old = TokenEncryptionService(primary_key=key_old, primary_key_id="k1")
    old_envelope = service_old.encrypt("token_encrypted_under_old_key")

    service_rotated = TokenEncryptionService(
        primary_key=key_new,
        primary_key_id="k2",
        fallback_keys={"k1": key_old},
    )

    # Decrypt payload created with old key
    assert service_rotated.decrypt(old_envelope) == "token_encrypted_under_old_key"

    # New encryptions use new key k2
    new_envelope = service_rotated.encrypt("token_encrypted_under_new_key")
    assert new_envelope.startswith("v1:k2:")
    assert service_rotated.decrypt(new_envelope) == "token_encrypted_under_new_key"

    # Service with missing key fails cleanly
    service_without_k1 = TokenEncryptionService(primary_key=key_new, primary_key_id="k2")
    with pytest.raises(DecryptionError, match="Unknown encryption key identifier: k1"):
        service_without_k1.decrypt(old_envelope)


def test_exception_never_leaks_plaintext_or_key(crypto_service: TokenEncryptionService) -> None:
    secret_token = "SUPER_SECRET_TOKEN_DO_NOT_LEAK_IN_LOGS"
    envelope = crypto_service.encrypt(secret_token)
    tampered = envelope[:-2] + "00"

    try:
        crypto_service.decrypt(tampered)
    except DecryptionError as exc:
        msg = str(exc)
        assert secret_token not in msg
        assert "SUPER_SECRET" not in msg
