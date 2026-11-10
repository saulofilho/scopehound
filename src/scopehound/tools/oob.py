"""Ferramentas OOB: gerar uma URL de callback e consultar os acessos."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .registry import ToolContext


class OobPayloadArgs(BaseModel):
    note: str = Field(default="", description="rótulo para lembrar onde você injetou a URL")


class OobPollArgs(BaseModel):
    token: str = Field(description="token devolvido por oob_payload")


async def oob_payload(ctx: ToolContext, a: OobPayloadArgs) -> str:
    if ctx.oob_new is None:
        return "listener OOB indisponível neste contexto."
    token, url = ctx.oob_new()
    return (
        f"URL OOB criada (token {token}): {url}\n"
        f"Injete-a onde o alvo possa acessá-la (ex.: campo de URL, XXE, SSRF). "
        f"Depois use oob_poll com o token para ver se houve callback."
    )


async def oob_poll(ctx: ToolContext, a: OobPollArgs) -> str:
    if ctx.oob_poll is None:
        return "listener OOB indisponível neste contexto."
    hits = ctx.oob_poll(a.token)
    if hits is None:
        return f"token {a.token!r} desconhecido."
    if not hits:
        return "Nenhum callback ainda para este token."
    lines = [f"  {h['method']} {h['path']} de {h['source_ip']}" for h in hits]
    return f"{len(hits)} callback(s):\n" + "\n".join(lines)
