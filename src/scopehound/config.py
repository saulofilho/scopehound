"""Configuração (variáveis SCOPEHOUND_*)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from .guardrails import DEFAULT_INTERNAL, IpPolicy

LlmProvider = Literal["openai_compat", "fake"]
LOCAL_LLM_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "host.docker.internal"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SCOPEHOUND_", env_file=".env", extra="ignore")

    mode: Literal["local", "server"] = "local"
    data_dir: Path = Path(".scopehound")
    database_url: str | None = None
    host: str = "127.0.0.1"
    port: int = 8787
    # Chave Fernet para criptografar segredos (ex.: chave de LLM do projeto).
    # No modo local, é gerada em data_dir/secret.key se não for informada.
    secret_key: SecretStr | None = None

    # Rede (guardrails)
    internal_deny_cidrs: list[str] | None = None
    hard_deny_cidrs: list[str] = []
    verify_tls: bool = True
    request_timeout: float = 15.0
    max_response_bytes: int = 2_000_000
    user_agent: str = "scopehound/0.1 (+authorized-testing)"

    # LLM padrão (cada projeto pode sobrescrever, inclusive com a própria chave)
    llm_provider: LlmProvider = "openai_compat"
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_model: str = ""
    llm_api_key: SecretStr | None = None
    llm_temperature: float = 0.1

    # Orçamento padrão por tarefa
    task_max_steps: int = 30
    task_max_requests: int = 200
    task_max_tokens: int = 500_000
    skill_dirs: list[Path] = []

    def effective_internal_deny(self) -> list[str]:
        if self.internal_deny_cidrs is not None:
            return self.internal_deny_cidrs
        return list(DEFAULT_INTERNAL) if self.mode == "server" else []

    def ip_policy(self) -> IpPolicy:
        return IpPolicy.build(
            hard_deny=self.hard_deny_cidrs, internal_deny=self.effective_internal_deny()
        )

    def resolved_database_url(self) -> str:
        return self.database_url or f"sqlite+aiosqlite:///{self.data_dir / 'scopehound.db'}"

    def checkpoint_path(self) -> Path:
        return self.data_dir / "checkpoints.db"


def is_local_llm(provider: str, base_url: str) -> bool:
    """O modelo roda na infraestrutura do usuário (nada sai para terceiros)?"""
    if provider == "fake":
        return True
    return (urlparse(base_url).hostname or "") in LOCAL_LLM_HOSTS
