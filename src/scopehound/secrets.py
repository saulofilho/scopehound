"""Criptografia de segredos guardados no banco (ex.: chave de LLM do usuário)."""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class SecretBox:
    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("segredo ilegível: SCOPEHOUND_SECRET_KEY mudou?") from exc


def load_secret_key(explicit: str | None, data_dir: Path, *, mode: str) -> bytes:
    if explicit:
        return explicit.encode()
    if mode == "server":
        raise RuntimeError("SCOPEHOUND_SECRET_KEY é obrigatório no modo servidor")
    path = data_dir / "secret.key"
    if path.exists():
        return path.read_bytes().strip()
    data_dir.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key)
    return key


def mask(value: str | None) -> str | None:
    if not value:
        return None
    return f"…{value[-4:]}" if len(value) > 8 else "…"
