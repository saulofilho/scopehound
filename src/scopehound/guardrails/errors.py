"""Exceções dos guardrails.

Toda ação bloqueada por uma regra de segurança levanta uma subclasse de
`GuardrailError`. Quem chama decide como apresentar o bloqueio, mas nunca
pode tratá-lo como sucesso.
"""

from __future__ import annotations


class GuardrailError(RuntimeError):
    """Base: ação bloqueada por uma regra de segurança."""


class ScopeViolation(GuardrailError):
    """URL, host, porta, path ou método fora do escopo autorizado."""


class EgressDenied(GuardrailError):
    """O destino resolvido (IP) é proibido, mesmo que o nome esteja no escopo."""


class BudgetExhausted(GuardrailError):
    """Limite de passos, requisições ou tokens atingido."""


class KillSwitchTripped(GuardrailError):
    """Parada de emergência acionada para o projeto."""


class ToolArgsDenied(GuardrailError):
    """Argumentos de ferramenta externa fora da lista permitida."""


class EgressNetworkError(RuntimeError):
    """Falha de rede depois que a requisição foi autorizada (não é bloqueio)."""
