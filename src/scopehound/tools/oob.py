"""Ferramentas OOB: gerar uma URL de callback e consultar os acessos."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from ..i18n import t

if TYPE_CHECKING:
    from .registry import ToolContext


class OobPayloadArgs(BaseModel):
    note: str = Field(default="", description="label to remember where you injected the URL")


class OobPollArgs(BaseModel):
    token: str = Field(description="token returned by oob_payload")


async def oob_payload(ctx: ToolContext, a: OobPayloadArgs) -> str:
    if ctx.oob_new is None:
        return t(
            "listener OOB indisponível neste contexto.",
            "OOB listener unavailable in this context.",
        )
    token, url = ctx.oob_new()
    return t(
        f"URL OOB criada (token {token}): {url}\n"
        "Injete-a onde o alvo possa acessá-la (ex.: campo de URL, XXE, SSRF). "
        "Depois use oob_poll com o token para ver se houve callback.",
        f"OOB URL created (token {token}): {url}\n"
        "Inject it where the target can reach it (e.g. URL field, XXE, SSRF). "
        "Then use oob_poll with the token to check for a callback.",
    )


async def oob_poll(ctx: ToolContext, a: OobPollArgs) -> str:
    if ctx.oob_poll is None:
        return t(
            "listener OOB indisponível neste contexto.", "OOB listener unavailable in this context."
        )
    hits = ctx.oob_poll(a.token)
    if hits is None:
        return t(f"token {a.token!r} desconhecido.", f"unknown token {a.token!r}.")
    if not hits:
        return t("Nenhum callback ainda para este token.", "No callback yet for this token.")
    frm = t("de", "from")
    lines = [f"  {h['method']} {h['path']} {frm} {h['source_ip']}" for h in hits]
    return t(f"{len(hits)} callback(s):\n", f"{len(hits)} callback(s):\n") + "\n".join(lines)
