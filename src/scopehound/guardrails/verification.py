"""Verificação de PoC.

Um achado só vira "confirmado" se a prova de conceito for reexecutada e a
evidência bater. Sem execução real (dry-run ou bloqueio), nada é confirmado.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PocVerdict:
    reproduced: bool
    detail: str


def evaluate_poc(
    *,
    status: int | None,
    body: str,
    expected_status: int | None = None,
    expected_substring: str = "",
) -> PocVerdict:
    if expected_status is None and not expected_substring:
        raise ValueError("informe expected_status e/ou expected_substring")
    if status is None:
        return PocVerdict(False, "requisição não executada (dry-run ou bloqueada)")
    status_ok = expected_status is None or status == expected_status
    substring_ok = not expected_substring or expected_substring in body
    if status_ok and substring_ok:
        return PocVerdict(True, f"reproduzido: status={status}")
    return PocVerdict(
        False,
        f"não reproduzido: status={status} (esperado {expected_status}), "
        f"substring_presente={substring_ok}",
    )
