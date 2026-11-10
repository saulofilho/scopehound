"""Parada de emergência do projeto.

Compartilhada por todas as tarefas e subagentes de um projeto. Depois de
acionada, nenhuma requisição nova sai, inclusive as que estavam esperando
o rate limiter.
"""

from __future__ import annotations

from .errors import KillSwitchTripped


class KillSwitch:
    def __init__(self) -> None:
        self._reason: str | None = None

    @property
    def tripped(self) -> bool:
        return self._reason is not None

    @property
    def reason(self) -> str | None:
        return self._reason

    def trip(self, reason: str) -> None:
        if self._reason is None:
            self._reason = reason

    def check(self) -> None:
        if self._reason is not None:
            raise KillSwitchTripped(f"kill switch acionado: {self._reason}")
