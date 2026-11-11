"""Ferramentas externas: nuclei, ffuf, sqlmap.

Desligadas por padrão (segundo portão, além de escopo e dry-run). Fazem shell
em binários reais. O escopo é checado contra a URL. O sqlmap passa pela
allowlist de flags (guardrails.sanitize_sqlmap_args). Os argumentos extras
nunca trocam o alvo nem acrescentam flags fora da lista permitida.
"""

from __future__ import annotations

import asyncio
import shlex
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from ..guardrails import ScopeViolation, ToolArgsDenied, check_url, sanitize_sqlmap_args
from ..i18n import t

if TYPE_CHECKING:
    from .registry import ToolContext

TIMEOUT = 120.0
OUTPUT_CAP = 4000


class NucleiArgs(BaseModel):
    url: str
    tags: str = Field(default="", description="nuclei tags/templates, e.g. 'cve,exposure'")


class FfufArgs(BaseModel):
    url: str = Field(description="URL with the FUZZ marker (or appended at the end)")
    wordlist: str = Field(description="Wordlist path on the host")


class SqlmapArgs(BaseModel):
    url: str
    data: str = Field(default="", description="POST body (optional)")
    extra_args: str = Field(default="", description="extra flags (pass through the allowlist)")


async def _run(cmd: list[str], timeout: float = TIMEOUT) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "", f"timeout após {timeout}s"
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


def _gate(ctx: ToolContext, url: str) -> str | None:
    """Portões comuns: habilitação, escopo, dry-run. Retorna erro ou None."""
    if not ctx.external_enabled:
        return (
            t("DESABILITADO: defina ", "DISABLED: set ")
            + "SCOPEHOUND_ENABLE_EXTERNAL_TOOLS=true "
            + t("para habilitar nuclei/ffuf/sqlmap.", "to enable nuclei/ffuf/sqlmap.")
        )
    try:
        check_url(ctx.scope, url)
    except ScopeViolation as exc:
        return t(f"BLOQUEADO (escopo): {exc}", f"BLOCKED (scope): {exc}")
    return None


async def nuclei(ctx: ToolContext, a: NucleiArgs) -> str:
    gate = _gate(ctx, a.url)
    if gate:
        return gate
    cmd = [ctx.bins["nuclei"], "-u", a.url, "-silent", "-jsonl"]
    if a.tags:
        cmd += ["-tags", a.tags]
    if ctx.dry_run_external:
        return f"DRY_RUN: {shlex.join(cmd)}"
    code, out, err = await _run(cmd, ctx.external_timeout)
    return f"nuclei exit={code}\n{out[:OUTPUT_CAP]}\n{err[:500]}"


async def ffuf(ctx: ToolContext, a: FfufArgs) -> str:
    url = a.url if "FUZZ" in a.url else a.url.rstrip("/") + "/FUZZ"
    gate = _gate(ctx, url.replace("FUZZ", "scopehoundprobe"))
    if gate:
        return gate
    cmd = [ctx.bins["ffuf"], "-u", url, "-w", a.wordlist, "-of", "json", "-s"]
    if ctx.dry_run_external:
        return f"DRY_RUN: {shlex.join(cmd)}"
    code, out, err = await _run(cmd, ctx.external_timeout)
    return f"ffuf exit={code}\n{out[:OUTPUT_CAP]}\n{err[:500]}"


async def sqlmap(ctx: ToolContext, a: SqlmapArgs) -> str:
    gate = _gate(ctx, a.url)
    if gate:
        return gate
    try:
        extra = (
            sanitize_sqlmap_args(shlex.split(a.extra_args))
            if a.extra_args
            else sanitize_sqlmap_args([])
        )
    except ToolArgsDenied as exc:
        return t(f"BLOQUEADO (argumento): {exc}", f"BLOCKED (argument): {exc}")
    cmd = [ctx.bins["sqlmap"], "-u", a.url, *extra]
    if a.data:
        cmd += ["--data", a.data]
    if ctx.dry_run_external:
        return f"DRY_RUN: {shlex.join(cmd)}"
    code, out, err = await _run(cmd, ctx.external_timeout)
    return f"sqlmap exit={code}\n{out[:OUTPUT_CAP]}\n{err[:500]}"
