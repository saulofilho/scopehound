"""Ferramentas de arquivo: ler, listar e escrever dentro do workspace do projeto.

O workspace é uma pasta read-write que o operador aponta (opt-in). Tudo é
confinado por fsguard: sem `..`, sem caminho absoluto, sem escape por symlink,
e nunca dentro da pasta de dados do scopehound. write_file tem impacto active
(pede aprovação no modo smart) e entra na auditoria.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from ..fsguard import (
    BLOCKED_WRITE_SUFFIXES,
    MAX_FILE_BYTES,
    MAX_LIST,
    WorkspaceError,
    safe_target,
)
from ..i18n import t

if TYPE_CHECKING:
    from .registry import ToolContext


def _no_ws() -> str:
    return t(
        "Nenhum workspace configurado. Use `scopehound project workspace "
        "<projeto> <pasta>` para habilitar as ferramentas de arquivo.",
        "No workspace configured. Use `scopehound project workspace "
        "<project> <folder>` to enable the file tools.",
    )


class ListFilesArgs(BaseModel):
    subdir: str = Field(default="", description="Workspace subfolder (empty = root)")


class ReadFileArgs(BaseModel):
    path: str = Field(description="Path relative to the workspace")
    max_bytes: int = Field(default=MAX_FILE_BYTES, ge=1, le=MAX_FILE_BYTES)


class WriteFileArgs(BaseModel):
    path: str = Field(description="Path relative to the workspace")
    content: str = Field(description="File content (text)")
    append: bool = Field(default=False, description="Append to the end instead of overwriting")


def _human(n: int) -> str:
    return f"{n}B" if n < 1024 else f"{n // 1024}KB"


async def list_files(ctx: ToolContext, a: ListFilesArgs) -> str:
    if ctx.workspace_root is None:
        return _no_ws()
    from .registry import untrusted

    try:
        base = safe_target(ctx.workspace_root, a.subdir or ".") if a.subdir else ctx.workspace_root
    except WorkspaceError as exc:
        return t(f"BLOQUEADO: {exc}", f"BLOCKED: {exc}")
    if not base.is_dir():
        return t(f"não é uma pasta: {a.subdir!r}", f"not a folder: {a.subdir!r}")
    rows = []
    for entry in sorted(base.iterdir())[:MAX_LIST]:
        rel = entry.relative_to(ctx.workspace_root)
        if entry.is_dir():
            rows.append(f"  {rel}/")
        else:
            rows.append(f"  {rel}  ({_human(entry.stat().st_size)})")
    if not rows:
        return t("(workspace vazio)", "(empty workspace)")
    return untrusted("\n".join(rows))


async def read_file(ctx: ToolContext, a: ReadFileArgs) -> str:
    if ctx.workspace_root is None:
        return _no_ws()
    from .registry import untrusted

    try:
        target = safe_target(ctx.workspace_root, a.path)
    except WorkspaceError as exc:
        return t(f"BLOQUEADO: {exc}", f"BLOCKED: {exc}")
    if not target.is_file():
        return t(f"arquivo não encontrado: {a.path}", f"file not found: {a.path}")
    size = target.stat().st_size
    data = target.read_bytes()[: a.max_bytes]
    text = data.decode("utf-8", errors="replace")
    more = (
        t(f"\n[truncado: {_human(size)} no total]", f"\n[truncated: {_human(size)} total]")
        if size > a.max_bytes
        else ""
    )
    return untrusted(f"// {a.path} ({_human(size)})\n{text}{more}")


async def write_file(ctx: ToolContext, a: WriteFileArgs) -> str:
    if ctx.workspace_root is None:
        return _no_ws()
    try:
        target = safe_target(ctx.workspace_root, a.path, for_write=True)
    except WorkspaceError as exc:
        return t(f"BLOQUEADO: {exc}", f"BLOCKED: {exc}")
    if target.suffix.lower() in BLOCKED_WRITE_SUFFIXES:
        return t(
            f"BLOQUEADO: extensão não permitida para escrita: {target.suffix}",
            f"BLOCKED: file extension not allowed for writing: {target.suffix}",
        )
    payload = a.content.encode("utf-8")
    existing = target.stat().st_size if target.exists() else 0
    projected = (existing if a.append else 0) + len(payload)
    if projected > MAX_FILE_BYTES:
        return t(
            f"BLOQUEADO: arquivo passaria de {_human(MAX_FILE_BYTES)} "
            f"(ficaria {_human(projected)})",
            f"BLOCKED: file would exceed {_human(MAX_FILE_BYTES)} (would be {_human(projected)})",
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("ab" if a.append else "wb") as fh:
        fh.write(payload)
    verb = t("acrescentado a", "appended to") if a.append else t("escrito", "written")
    return f"OK: {_human(len(payload))} {verb} {a.path} (total {_human(target.stat().st_size)})"
