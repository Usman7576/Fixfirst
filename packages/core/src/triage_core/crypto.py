"""Symmetric encryption for secrets stored in the database (GitHub tokens, webhook URLs)."""

from cryptography.fernet import Fernet, InvalidToken

__all__ = ["InvalidToken", "SecretCipher"]


class SecretCipher:
    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode())

    def decrypt(self, ciphertext: bytes) -> str:
        return self._fernet.decrypt(ciphertext).decode()
