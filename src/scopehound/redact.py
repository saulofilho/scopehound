"""Mascaramento de dados sensíveis antes de enviar ao LLM.

Quando o projeto usa um LLM que não é local, o tráfego do alvo pode conter
credenciais e PII que não devem sair da máquina. Esta camada mascara esses
valores no texto que vai para o modelo. Não altera o que é enviado ao alvo
nem o que fica guardado no projeto: só o que o modelo vê.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Cabeçalhos cujo valor é sempre substituído por um marcador.
SECRET_HEADERS = (
    "authorization",
    "cookie",
    "set-cookie",
    "proxy-authorization",
    "x-api-key",
    "x-auth-token",
    "api-key",
)

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("card", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{10,}")),
    ("pix_cpf", re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")),
)

CATEGORIES = ("headers", *[name for name, _ in _PATTERNS])


@dataclass(frozen=True)
class Redactor:
    categories: frozenset[str]

    @classmethod
    def from_policy(cls, policy: str | list[str] | None) -> Redactor:
        if not policy or policy == "off":
            return cls(frozenset())
        if policy in ("on", "all", "default"):
            return cls(frozenset(CATEGORIES))
        if isinstance(policy, str):
            policy = [p.strip() for p in policy.split(",") if p.strip()]
        return cls(frozenset(policy) & frozenset(CATEGORIES))

    @property
    def active(self) -> bool:
        return bool(self.categories)

    def header_value(self, name: str, value: str) -> str:
        if "headers" in self.categories and name.lower() in SECRET_HEADERS:
            return "«oculto»"
        return self.text(value)

    def text(self, text: str) -> str:
        if not self.active or not text:
            return text
        for name, pattern in _PATTERNS:
            if name in self.categories:
                text = pattern.sub(f"«{name}»", text)
        return text
