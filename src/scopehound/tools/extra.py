"""Ferramentas das skills da Fase 3: replay_as, content_discovery, race_request,
read_source.

Todas usam o egress (escopo, DNS, orçamento, rate limit). O impacto declarado
alimenta o policy engine: content_discovery e race_request são intrusive.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from ..guardrails import EgressNetworkError, GuardrailError
from .discovery import DEFAULT_WORDLIST

if TYPE_CHECKING:
    from .registry import ToolContext

MAX_WORDS = 500
MAX_RACE = 40
READ_SOURCE_MAX = 60_000


class ReplayAsArgs(BaseModel):
    id: str = Field(description="Id de uma troca do histórico a repetir")
    session: str = Field(description="Nome da sessão de autenticação a usar")
    method: str = Field(default="", description="Sobrescreve o método (opcional)")
    url: str = Field(default="", description="Sobrescreve a URL (opcional)")


class ContentDiscoveryArgs(BaseModel):
    base_url: str = Field(description="URL base, ex.: http://app.lab/")
    words: list[str] = Field(default_factory=list, description="Vazio = wordlist embutida")
    extensions: list[str] = Field(default_factory=list)


class RaceRequestArgs(BaseModel):
    url: str
    method: str = "POST"
    headers: dict[str, str] = Field(default_factory=dict)
    body: str = ""
    count: int = Field(default=10, ge=2, le=MAX_RACE)
    session: str = Field(default="", description="Sessão de autenticação opcional")


class ReadSourceArgs(BaseModel):
    path: str = Field(description="Caminho relativo à raiz de código configurada")


def _status_table(results: dict[int, int]) -> str:
    return ", ".join(f"{status}×{count}" for status, count in sorted(results.items()))


async def replay_as(ctx: ToolContext, a: ReplayAsArgs) -> str:
    row = await ctx.traffic.get(a.id)
    if row is None:
        return f"Troca {a.id!r} não encontrada."
    creds = await ctx.get_session(a.session)
    if creds is None:
        return f"Sessão {a.session!r} não existe. Crie com `scopehound session add`."
    headers = {
        k: v
        for k, v in row.request_headers
        if k.lower() not in ("cookie", "authorization", "host", "content-length")
    }
    headers.update(creds)
    method = (a.method or row.method).upper()
    url = a.url or row.url
    res = await ctx.egress.send(method, url, headers=headers, content=row.request_body or None)
    await ctx.record(res, headers, row.request_body or "")
    from .registry import untrusted

    return untrusted(
        f"replay de {a.id[:12]} como '{a.session}': {method} {url} -> {res.status} "
        f"({res.response_size if hasattr(res, 'response_size') else len(res.body)}B)\n"
        f"{res.text[:3000]}"
    )


async def content_discovery(ctx: ToolContext, a: ContentDiscoveryArgs) -> str:
    words = a.words or list(DEFAULT_WORDLIST)
    if len(words) > MAX_WORDS:
        return f"wordlist grande demais (máx {MAX_WORDS}); refine a lista."
    candidates: list[str] = []
    base = a.base_url.rstrip("/")
    for word in words:
        word = word.lstrip("/")
        for ext in ["", *a.extensions]:
            candidates.append(f"{base}/{word}{ext}")
    found: list[str] = []
    status_counts: dict[int, int] = {}
    blocked = 0
    for url in candidates:
        try:
            res = await ctx.egress.send("GET", url)
        except GuardrailError:
            blocked += 1
            continue
        except EgressNetworkError:
            continue
        status_counts[res.status] = status_counts.get(res.status, 0) + 1
        if res.status not in (404, 400):
            found.append(f"  {res.status}  {url}  ({len(res.body)}B)")
    header = f"content_discovery em {base}: {len(candidates)} caminhos testados"
    if blocked:
        header += f", {blocked} fora do escopo"
    body = "\n".join(found) if found else "  (nada além de 404/400)"
    return f"{header}\nresumo: {_status_table(status_counts)}\nachados:\n{body}"


async def race_request(ctx: ToolContext, a: RaceRequestArgs) -> str:
    headers = dict(a.headers)
    if a.session:
        creds = await ctx.get_session(a.session)
        if creds is None:
            return f"Sessão {a.session!r} não existe."
        headers.update(creds)

    async def one():
        try:
            res = await ctx.egress.send(a.method, a.url, headers=headers, content=a.body or None)
            return res.status, res.response_size if hasattr(res, "response_size") else len(res.body)
        except (GuardrailError, EgressNetworkError) as exc:
            return None, str(exc)

    results = await asyncio.gather(*[one() for _ in range(a.count)])
    sent = [(s, size) for s, size in results if s is not None]
    errors = [size for s, size in results if s is None]
    if not sent:
        return f"race_request: nenhuma requisição saiu. Motivo: {errors[0] if errors else '?'}"
    status_counts: dict[int, int] = {}
    sizes = set()
    for status, size in sent:
        status_counts[status] = status_counts.get(status, 0) + 1
        sizes.add(size)
    note = ""
    if len(status_counts) > 1 or len(sizes) > 1:
        note = (
            "\n⚠ respostas divergentes entre requisições concorrentes: possível "
            "condição de corrida. Verifique o efeito no estado do alvo."
        )
    blocked = f", {len(errors)} bloqueadas/erro" if errors else ""
    return (
        f"race_request: {len(sent)} de {a.count} requisições concorrentes{blocked}\n"
        f"status: {_status_table(status_counts)}\ntamanhos distintos: {sorted(sizes)}{note}"
    )


async def read_source(ctx: ToolContext, a: ReadSourceArgs) -> str:
    root = ctx.source_root
    if root is None:
        return (
            "Nenhuma raiz de código configurada. Use "
            "`scopehound project source <projeto> <caminho>` para habilitar read_source."
        )
    try:
        target = (root / a.path).resolve()
        target.relative_to(root)
    except (ValueError, OSError):
        return f"caminho fora da raiz de código permitida: {a.path!r}"
    if not target.is_file():
        return f"arquivo não encontrado: {a.path}"
    if target.stat().st_size > READ_SOURCE_MAX:
        return f"arquivo grande demais (>{READ_SOURCE_MAX} bytes); leia um trecho menor."
    from .registry import untrusted

    return untrusted(f"// {a.path}\n{target.read_text(encoding='utf-8', errors='replace')}")
