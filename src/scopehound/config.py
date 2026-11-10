"""Configuração (variáveis SCOPEHOUND_*)."""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from .guardrails import DEFAULT_INTERNAL, IpPolicy


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SCOPEHOUND_", env_file=".env", extra="ignore")

    mode: Literal["local", "server"] = "local"
    # Redes internas bloqueadas salvo allowed_cidrs do projeto.
    # None = padrão do modo (vazio no local, redes privadas no servidor).
    internal_deny_cidrs: list[str] | None = None
    # Faixas que nenhum projeto pode liberar (ex.: a rede do cluster).
    hard_deny_cidrs: list[str] = []
    verify_tls: bool = True
    request_timeout: float = 15.0
    max_response_bytes: int = 2_000_000
    user_agent: str = "scopehound/0.1 (+authorized-testing)"

    def effective_internal_deny(self) -> list[str]:
        if self.internal_deny_cidrs is not None:
            return self.internal_deny_cidrs
        return list(DEFAULT_INTERNAL) if self.mode == "server" else []

    def ip_policy(self) -> IpPolicy:
        return IpPolicy.build(
            hard_deny=self.hard_deny_cidrs, internal_deny=self.effective_internal_deny()
        )
