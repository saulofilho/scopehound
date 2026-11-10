"""Orçamento de passos, requisições e tokens.

Orçamentos podem ser hierárquicos: uma tarefa cria orçamentos filhos para os
seus subagentes, e todo consumo de um filho também é cobrado do pai. O
consumo só é efetivado se couber em toda a cadeia.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .errors import BudgetExhausted

Resource = Literal["steps", "requests", "tokens"]


@dataclass
class Budget:
    max_steps: int
    max_requests: int
    max_tokens: int
    steps: int = 0
    requests: int = 0
    tokens: int = 0
    exhausted_reason: str | None = None
    parent: Budget | None = field(default=None, repr=False)

    def consume_step(self, n: int = 1) -> None:
        self._consume("steps", n)

    def consume_request(self, n: int = 1) -> None:
        self._consume("requests", n)

    def consume_tokens(self, n: int) -> None:
        self._consume("tokens", n)

    def remaining(self, resource: Resource) -> int:
        own = getattr(self, f"max_{resource}") - getattr(self, resource)
        if self.parent is None:
            return own
        return min(own, self.parent.remaining(resource))

    def child(
        self,
        *,
        max_steps: int | None = None,
        max_requests: int | None = None,
        max_tokens: int | None = None,
    ) -> Budget:
        """Cria um orçamento filho (ex.: para um subagente)."""
        return Budget(
            max_steps=max_steps if max_steps is not None else self.remaining("steps"),
            max_requests=max_requests if max_requests is not None else self.remaining("requests"),
            max_tokens=max_tokens if max_tokens is not None else self.remaining("tokens"),
            parent=self,
        )

    def snapshot(self) -> dict[str, int | str | None]:
        return {
            "steps": self.steps,
            "requests": self.requests,
            "tokens": self.tokens,
            "exhausted_reason": self.exhausted_reason,
        }

    def _check(self, resource: Resource, n: int) -> None:
        limit = getattr(self, f"max_{resource}")
        if getattr(self, resource) + n > limit:
            self.exhausted_reason = f"max_{resource}={limit}"
            raise BudgetExhausted(self.exhausted_reason)
        if self.parent is not None:
            self.parent._check(resource, n)

    def _commit(self, resource: Resource, n: int) -> None:
        setattr(self, resource, getattr(self, resource) + n)
        if self.parent is not None:
            self.parent._commit(resource, n)

    def _consume(self, resource: Resource, n: int) -> None:
        if n < 0:
            raise ValueError("consumo negativo")
        self._check(resource, n)
        self._commit(resource, n)
