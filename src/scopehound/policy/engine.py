"""Policy engine: decide se uma ação pedida pelo modelo acontece.

Segue os modos de autonomia do Burp AT:

- **manual**: cada ferramenta segue a configuração do projeto (Ask/Act);
- **smart** (padrão): leituras e requisições sem efeito colateral passam;
  o resto pede aprovação, a menos que já tenha sido aprovado para a sessão;
- **autonomous**: nada pergunta, exceto ferramentas que sempre exigem
  aprovação.

Ferramentas desabilitadas nunca rodam, em nenhum modo. Ferramentas
`always_ask` nunca viram Act. O modo smart aqui é determinístico: ele só
decide entre "passa" e "pergunta", nunca libera o que uma regra fixa bloqueia.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

Impact = Literal["read", "active", "intrusive", "admin"]
Mode = Literal["manual", "smart", "autonomous"]
Outcome = Literal["allow", "ask", "deny"]
ManualSetting = Literal["ask", "act"]

MODES: tuple[Mode, ...] = ("manual", "smart", "autonomous")
MODES_SET = frozenset(MODES)
APPROVAL_RESPONSES = ("once", "session", "always", "reject", "redirect")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    impact: Impact
    always_ask: bool = False
    default_manual: ManualSetting = "ask"
    # Impacto que depende dos argumentos (ex.: GET é active, POST é intrusive).
    impact_for: Callable[[Mapping[str, Any]], Impact] | None = None

    def impact_of(self, args: Mapping[str, Any]) -> Impact:
        return self.impact_for(args) if self.impact_for else self.impact


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    reason: str
    impact: Impact


def grant_key(tool: str, impact: Impact) -> str:
    return f"{tool}:{impact}"


def tool_setting(spec: ToolSpec, settings: Mapping[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {"enabled": True, "manual": spec.default_manual}
    if settings:
        merged.update(settings)
    if spec.always_ask:
        merged["manual"] = "ask"
    return merged


def decide(
    spec: ToolSpec,
    args: Mapping[str, Any],
    *,
    mode: Mode,
    settings: Mapping[str, Any] | None = None,
    session_grants: Iterable[str] = (),
) -> Decision:
    impact = spec.impact_of(args)
    setting = tool_setting(spec, settings)

    if not setting["enabled"]:
        return Decision("deny", "ferramenta desabilitada neste projeto", impact)
    if spec.always_ask:
        return Decision("ask", "esta ferramenta sempre exige aprovação", impact)

    if mode == "autonomous":
        return Decision("allow", "modo autônomo", impact)
    if mode == "manual":
        if setting["manual"] == "act":
            return Decision("allow", "ferramenta configurada como Act", impact)
        return Decision("ask", "ferramenta configurada como Ask (modo manual)", impact)

    # smart
    if impact == "read":
        return Decision("allow", "leitura", impact)
    if grant_key(spec.name, impact) in set(session_grants):
        return Decision("allow", "aprovado para esta sessão", impact)
    if impact == "active":
        return Decision("allow", "rotina: requisição sem efeito colateral", impact)
    return Decision("ask", f"impacto {impact}: confirme antes de executar", impact)


def validate_response(response: str, *, mode: str, spec: ToolSpec) -> None:
    """Regras do Burp AT para respostas de aprovação."""
    if response not in APPROVAL_RESPONSES:
        raise ValueError(f"resposta inválida: {response}")
    if response == "session" and mode != "smart":
        raise ValueError("'aprovar para a sessão' só existe no modo smart")
    if response == "always":
        if mode != "manual":
            raise ValueError("'sempre aprovar' só existe no modo manual")
        if spec.always_ask:
            raise ValueError("esta ferramenta sempre exige aprovação")
