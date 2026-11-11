"""Confinamento de caminhos para as ferramentas de arquivo.

Resolve a raiz uma vez e garante que o alvo fica dentro dela mesmo com
symlinks, `..` ou caminho absoluto. Separado para ser testável sem o agente.
"""

from __future__ import annotations

import os
from pathlib import Path

from .guardrails.errors import GuardrailError

# Extensões que podem virar execução/código mais tarde: recusadas na escrita.
BLOCKED_WRITE_SUFFIXES = frozenset(
    {
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".py",
        ".pyc",
        ".pyo",
        ".rb",
        ".pl",
        ".php",
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".bat",
        ".cmd",
        ".ps1",
        ".psm1",
        ".com",
        ".scr",
        ".jar",
        ".app",
        ".bin",
        ".run",
        ".desktop",
        ".service",
        ".socket",
        ".timer",
    }
)
MAX_FILE_BYTES = 2_000_000
MAX_LIST = 500


class WorkspaceError(GuardrailError):
    """Operação de arquivo fora dos limites do workspace."""


def resolve_root(path: str | os.PathLike[str]) -> Path:
    return Path(path).expanduser().resolve()


def safe_target(root: Path, rel: str, *, for_write: bool = False) -> Path:
    """Devolve o caminho absoluto de `rel` dentro de `root`, ou levanta.

    `root` precisa já estar resolvido. A checagem segue symlinks: resolve o
    alvo (ou o pai, na escrita, já que o arquivo pode não existir) e confirma
    que continua sob `root`.
    """
    rel = rel.strip()
    if not rel or rel in (".", "./"):
        raise WorkspaceError("informe um caminho de arquivo dentro do workspace")
    candidate = Path(rel)
    if candidate.is_absolute() or candidate.drive or candidate.anchor:
        raise WorkspaceError(f"caminho absoluto não permitido: {rel!r}")
    if any(part == ".." for part in candidate.parts):
        raise WorkspaceError(f"'..' não permitido no caminho: {rel!r}")

    raw = (root / candidate).resolve() if not for_write else _resolve_for_write(root, candidate)
    if raw != root and root not in raw.parents:
        raise WorkspaceError(f"caminho escapa do workspace: {rel!r}")
    return raw


def _resolve_for_write(root: Path, candidate: Path) -> Path:
    # O arquivo pode não existir; resolve o diretório pai (que já deve existir
    # ou ser criado sob root) e recoloca o nome final sem segui-lo.
    parent = (root / candidate.parent).resolve()
    if parent != root and root not in parent.parents:
        raise WorkspaceError(f"diretório escapa do workspace: {candidate!s}")
    return parent / candidate.name


def check_not_reserved(root: Path, reserved: list[Path]) -> None:
    """Recusa um workspace que seja, contenha ou esteja dentro de uma pasta
    reservada (ex.: o diretório de dados do scopehound)."""
    for other in reserved:
        other = other.resolve()
        if root == other or root in other.parents or other in root.parents:
            raise WorkspaceError(f"workspace não pode coincidir com uma pasta reservada: {other}")
