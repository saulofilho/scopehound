"""Saneamento de argumentos de ferramentas externas.

O hackbot usava uma denylist para o sqlmap. Aqui é uma allowlist: qualquer
flag não listada é recusada. Denylist deixava passar, por exemplo, `-u`
(troca o alvo, fugindo do escopo), `-m`/`-l`/`-g` (alvos vindos de arquivo
ou do Google), `--alert` (executa comando no host) e abreviações de flags
proibidas.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from .errors import ToolArgsDenied

SQLMAP_FORCED = ("--batch", "--risk=1", "--level=1")

_SQLMAP_SWITCHES = frozenset(
    {
        "--batch",
        "--random-agent",
        "--banner",
        "--current-user",
        "--current-db",
        "--is-dba",
        "--dbs",
        "--tables",
        "--columns",
        "--count",
        "--skip-static",
        "--flush-session",
        "--fresh-queries",
        "--text-only",
        "--titles",
        "--smart",
        "--keep-alive",
        "--null-connection",
        "--hex",
        "--no-cast",
        "--parse-errors",
    }
)
_SQLMAP_OPTIONS = frozenset(
    {
        "-p",
        "--technique",
        "--dbms",
        "--string",
        "--not-string",
        "--regexp",
        "--code",
        "--prefix",
        "--suffix",
        "--timeout",
        "--retries",
        "--delay",
        "--cookie",
        "--cookie-del",
        "--headers",
        "-H",
        "--method",
        "--param-del",
        "-D",
        "-T",
        "-C",
        "--skip",
        "--time-sec",
        "--union-cols",
        "--union-char",
        "--threads",
        "-v",
    }
)
_SQLMAP_DROPPED = frozenset({"--risk", "--level"})
_MAX_THREADS = 4


def sanitize_sqlmap_args(tokens: Sequence[str]) -> list[str]:
    """Valida argumentos extras do sqlmap e devolve a lista final, com os
    parâmetros obrigatórios (`--batch --risk=1 --level=1`) na frente."""
    out: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if not token.startswith("-"):
            raise ToolArgsDenied(f"argumento posicional não permitido: {token!r}")
        name, has_value, value = token.partition("=")

        if name in _SQLMAP_DROPPED:
            i += 1 if has_value else 2
            continue

        if name in _SQLMAP_SWITCHES:
            if has_value:
                raise ToolArgsDenied(f"{name} não aceita valor")
            out.append(name)
            i += 1
            continue

        if name not in _SQLMAP_OPTIONS:
            raise ToolArgsDenied(f"flag não permitida no sqlmap: {name}")

        if not has_value:
            if i + 1 >= len(tokens):
                raise ToolArgsDenied(f"{name} precisa de um valor")
            value = tokens[i + 1]
            i += 2
        else:
            i += 1
        if not value or value.startswith("-"):
            raise ToolArgsDenied(f"valor inválido para {name}: {value!r}")
        if name in ("--headers", "-H") and any(
            line.strip().lower().startswith("host:") for line in re.split(r"\\n|\n", value)
        ):
            raise ToolArgsDenied("cabeçalho Host não pode ser alterado")
        if name == "--threads":
            try:
                threads = int(value)
            except ValueError as exc:
                raise ToolArgsDenied(f"--threads inválido: {value!r}") from exc
            value = str(max(1, min(threads, _MAX_THREADS)))
        out += [name, value]
    return [*SQLMAP_FORCED, *out]
