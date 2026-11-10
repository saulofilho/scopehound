"""CLI do scopehound."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from .config import Settings
from .guardrails import Budget, Egress, GuardrailError, load_scope

app = typer.Typer(no_args_is_help=True, help="Agente de pentest com escopo imposto fora do modelo.")
project_app = typer.Typer(no_args_is_help=True, help="Projetos (escopo, LLM, ferramentas).")
app.add_typer(project_app, name="project")

ScopeOpt = Annotated[Path, typer.Option("--scope", "-s", help="Arquivo de escopo")]


def _fail(message: str) -> None:
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


@app.command()
def version() -> None:
    """Mostra a versão."""
    typer.echo(__version__)


@app.command()
def check(
    url: str,
    scope: ScopeOpt = Path("scope.yaml"),
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
        _fail(f"BLOQUEADO: {exc}")
    typer.secho(f"PERMITIDO: {method.upper()} {url} -> {ip} (modo {settings.mode})", fg="green")


@app.command()
def serve(
    host: Annotated[str | None, typer.Option()] = None,
    port: Annotated[int | None, typer.Option()] = None,
) -> None:
    """Sobe a API."""
    import uvicorn

    from .api import create_app
    from .core import Runtime

    settings = Settings()
    host = host or settings.host
    if settings.mode == "local" and host not in ("127.0.0.1", "localhost", "::1"):
        _fail("no modo local a API só escuta em 127.0.0.1 (ainda não há autenticação)")
    uvicorn.run(create_app(Runtime(settings)), host=host, port=port or settings.port)


def _with_runtime(fn):
    from .core import Conflict, NotFound, Runtime

    async def runner():
        async with Runtime(Settings()) as rt:
            return await fn(rt)

    try:
        return asyncio.run(runner())
    except (Conflict, NotFound, ValueError) as exc:
        _fail(str(exc))


@project_app.command("create")
def project_create(
    name: str,
    scope: ScopeOpt = Path("scope.yaml"),
    local_only: Annotated[
        bool, typer.Option(help="Recusar LLM que não seja local (dados sensíveis)")
    ] = False,
) -> None:
    """Cria um projeto a partir de um arquivo de escopo."""
    from .core import service as svc

    data = load_scope(scope).model_dump(mode="json")
    policy = "local_only" if local_only else "any"
    project = _with_runtime(
        lambda rt: svc.create_project(rt, name=name, scope=data, llm_data_policy=policy)
    )
    typer.echo(f"projeto criado: {project.name} ({project.id})")


@project_app.command("list")
def project_list() -> None:
    """Lista os projetos."""
    from .core import service as svc

    for p in _with_runtime(svc.list_projects):
        typer.echo(
            f"{p.id}  {p.name}  llm={p.llm_model or '(padrão)'}  "
            f"chave={'própria' if p.llm_api_key_enc else '(padrão)'}"
        )


@project_app.command("llm")
def project_llm(
    project: str,
    base_url: Annotated[str | None, typer.Option(help="Ex.: http://localhost:11434/v1")] = None,
    model: Annotated[str | None, typer.Option()] = None,
    api_key: Annotated[
        bool, typer.Option("--api-key", help="Pede a sua chave (não fica no histórico)")
    ] = False,
    clear_api_key: Annotated[bool, typer.Option()] = False,
) -> None:
    """Define o LLM do projeto, inclusive com a sua própria chave."""
    from .core import service as svc

    key = typer.prompt("Chave de API", hide_input=True) if api_key else None

    async def run(rt):
        p = await svc.find_project(rt, project)
        return await svc.set_llm_config(
            rt, p.id, base_url=base_url, model=model, api_key=key, clear_api_key=clear_api_key
        )

    p = _with_runtime(run)
    typer.echo(
        f"LLM de {p.name}: {p.llm_base_url or '(padrão)'} {p.llm_model or '(padrão)'} "
        f"chave={'própria' if p.llm_api_key_enc else '(padrão)'}"
    )


@project_app.command("tool")
def project_tool(
    project: str,
    tool: str,
    enable: Annotated[bool | None, typer.Option("--enable/--disable")] = None,
    manual: Annotated[str | None, typer.Option(help="ask | act")] = None,
) -> None:
    """Liga/desliga uma ferramenta ou define Ask/Act (modo manual)."""
    from .core import service as svc

    async def run(rt):
        p = await svc.find_project(rt, project)
        return await svc.set_tool_setting(rt, p.id, tool, enabled=enable, manual=manual)

    typer.echo(json.dumps(_with_runtime(run), ensure_ascii=False, indent=2))


@app.command()
def chat(
    project: str,
    task: Annotated[str | None, typer.Option(help="Continuar uma tarefa existente")] = None,
    mode: Annotated[str, typer.Option(help="manual | smart | autonomous")] = "smart",
) -> None:
    """Conversa com o agente pelo terminal, com aprovações interativas."""
    from .chat import run_chat

    _with_runtime(lambda rt: run_chat(rt, project, task, mode))
