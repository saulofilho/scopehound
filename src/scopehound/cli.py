"""CLI do scopehound."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from .config import Settings
from .guardrails import Budget, Egress, GuardrailError, load_scope

app = typer.Typer(no_args_is_help=True, help="Agente de pentest com escopo imposto fora do modelo.")


@app.command()
def version() -> None:
    """Mostra a versão."""
    typer.echo(__version__)


@app.command()
def check(
    url: str,
    scope: Annotated[Path, typer.Option("--scope", "-s", help="Arquivo de escopo")] = Path(
        "scope.yaml"
    ),
    method: Annotated[str, typer.Option("--method", "-X")] = "GET",
) -> None:
    """Verifica, sem enviar nada, se uma requisição passaria pelos guardrails."""
    settings = Settings()
    project_scope = load_scope(scope)

    async def run() -> str:
        async with Egress(
            project_scope,
            budget=Budget(max_steps=1, max_requests=1, max_tokens=1),
            ip_policy=settings.ip_policy(),
            dry_run=True,
        ) as egress:
            result = await egress.send(method, url)
            return result.resolved_ip

    try:
        ip = asyncio.run(run())
    except GuardrailError as exc:
        typer.secho(f"BLOQUEADO: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    typer.secho(f"PERMITIDO: {method.upper()} {url} -> {ip} (modo {settings.mode})", fg="green")
