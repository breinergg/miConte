"""Security and cryptographic exceptions."""


class CryptoError(Exception):
    """Base exception for cryptographic operations in miConte."""


class DecryptionError(CryptoError):
    """Raised when ciphertext decryption or integrity authentication fails.

    Security rule: This exception must never leak plaintext tokens or key bytes.
    """


class KeyConfigurationError(CryptoError):
    """Raised when encryption keys are improperly configured or invalid."""


class SecurityAuthorizationError(CryptoError):
    """Raised when an unauthorized actor attempts to access or decrypt a credential."""
