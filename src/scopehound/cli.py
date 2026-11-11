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
from .i18n import t

app = typer.Typer(no_args_is_help=True, help="Pentest agent with scope enforced outside the model.")
project_app = typer.Typer(no_args_is_help=True, help="Projects (scope, LLM, tools).")
app.add_typer(project_app, name="project")
session_app = typer.Typer(no_args_is_help=True, help="Authentication sessions (for replay_as).")
app.add_typer(session_app, name="session")

ScopeOpt = Annotated[Path, typer.Option("--scope", "-s", help="Scope file")]


def _fail(message: str) -> None:
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


@app.command()
def version() -> None:
    """Show the version."""
    typer.echo(__version__)


@app.command()
def check(
    url: str,
    scope: ScopeOpt = Path("scope.yaml"),
    method: Annotated[str, typer.Option("--method", "-X")] = "GET",
) -> None:
    """Check, without sending anything, whether a request would pass the guardrails."""
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
        _fail(t(f"BLOQUEADO: {exc}", f"BLOCKED: {exc}"))
    typer.secho(
        t(
            f"PERMITIDO: {method.upper()} {url} -> {ip} (modo {settings.mode})",
            f"ALLOWED: {method.upper()} {url} -> {ip} (mode {settings.mode})",
        ),
        fg="green",
    )


@app.command()
def serve(
    host: Annotated[str | None, typer.Option()] = None,
    port: Annotated[int | None, typer.Option()] = None,
) -> None:
    """Start the API."""
    import uvicorn

    from .api import create_app
    from .core import Runtime

    settings = Settings()
    host = host or settings.host
    if settings.mode == "local" and host not in ("127.0.0.1", "localhost", "::1"):
        _fail(
            t(
                "no modo local a API só escuta em 127.0.0.1 (ainda não há autenticação)",
                "in local mode the API only listens on 127.0.0.1 (no authentication yet)",
            )
        )
    auth = None
    if settings.mode == "server":
        from .api.auth import AuthContext, build_oidc_verifier

        if not (settings.oidc_issuer and settings.oidc_audience and settings.oidc_jwks_url):
            _fail("modo servidor exige SCOPEHOUND_OIDC_ISSUER, _AUDIENCE e _JWKS_URL")
        verifier = build_oidc_verifier(
            settings.oidc_issuer, settings.oidc_audience, settings.oidc_jwks_url
        )
        auth = AuthContext(mode="server", verifier=verifier)
    uvicorn.run(create_app(Runtime(settings), auth=auth), host=host, port=port or settings.port)


def _with_runtime(fn):
    from .core import Conflict, NotFound, Runtime

    async def runner():
        async with Runtime(Settings()) as rt:
            return await fn(rt)

    try:
        return asyncio.run(runner())
    except (Conflict, NotFound, ValueError) as exc:
        _fail(str(exc))


@app.command()
def doctor(
    project: Annotated[
        str | None, typer.Option(help="Test the project LLM; empty uses the .env default")
    ] = None,
) -> None:
    """Check the LLM connection: provider, model and credential."""
    from langchain_core.messages import HumanMessage

    from .agent import explain_llm_error
    from .core import service as svc

    async def run(rt):
        if project:
            proj = await svc.find_project(rt, project)
        else:
            proj = type(
                "P",
                (),
                {
                    "llm_provider": None,
                    "llm_base_url": None,
                    "llm_model": None,
                    "llm_api_key_enc": None,
                },
            )()
        cfg = rt.llm_config(proj)
        typer.echo(f"provedor : {cfg.provider}")
        typer.echo(f"base_url : {cfg.base_url}")
        typer.echo(f"model    : {cfg.model or '(empty)'}")
        local_v = t("sim", "yes") if cfg.is_local else t("não", "no")
        key_v = t("definida", "set") if cfg.api_key else t("nenhuma", "none")
        typer.echo(f"local    : {local_v}  ·  {t('chave', 'key')}: {key_v}")
        if not cfg.model:
            _fail(
                t(
                    "modelo não configurado: defina SCOPEHOUND_LLM_MODEL ou o LLM do projeto.",
                    "model not configured: set SCOPEHOUND_LLM_MODEL or the project LLM.",
                )
            )
        typer.echo(t("testando uma chamada mínima…", "testing a minimal call…"))
        try:
            model = rt.llm_factory(cfg)
            reply = await model.ainvoke([HumanMessage("responda só: ok")])
        except Exception as exc:  # noqa: BLE001
            raise explain_llm_error(exc, cfg) from exc
        text = (reply.content or "").strip() if hasattr(reply, "content") else str(reply)
        typer.secho(
            t(f"OK — modelo respondeu: {text[:80]!r}", f"OK — model replied: {text[:80]!r}"),
            fg="green",
        )

    from .agent import LlmError

    try:
        _with_runtime(run)
    except LlmError as exc:
        _fail(str(exc))


@project_app.command("create")
def project_create(
    name: str,
    scope: ScopeOpt = Path("scope.yaml"),
    local_only: Annotated[
        bool, typer.Option(help="Refuse a non-local LLM (sensitive data)")
    ] = False,
) -> None:
    """Create a project from a scope file."""
    from .core import service as svc

    data = load_scope(scope).model_dump(mode="json")
    policy = "local_only" if local_only else "any"
    project = _with_runtime(
        lambda rt: svc.create_project(rt, name=name, scope=data, llm_data_policy=policy)
    )
    typer.echo(
        t(
            f"projeto criado: {project.name} ({project.id})",
            f"project created: {project.name} ({project.id})",
        )
    )


@project_app.command("list")
def project_list() -> None:
    """List the projects."""
    from .core import service as svc

    for p in _with_runtime(svc.list_projects):
        default = t("padrão", "default")
        key = t("própria", "own") if p.llm_api_key_enc else f"({default})"
        typer.echo(
            f"{p.id}  {p.name}  llm={p.llm_model or f'({default})'}  {t('chave', 'key')}={key}"
        )


@project_app.command("llm")
def project_llm(
    project: str,
    base_url: Annotated[str | None, typer.Option(help="e.g. http://localhost:11434/v1")] = None,
    model: Annotated[str | None, typer.Option()] = None,
    api_key: Annotated[
        bool, typer.Option("--api-key", help="Prompt for your key (not stored in shell history)")
    ] = False,
    clear_api_key: Annotated[bool, typer.Option()] = False,
) -> None:
    """Set the project LLM, including your own key."""
    from .core import service as svc

    key = typer.prompt("Chave de API", hide_input=True) if api_key else None

    async def run(rt):
        p = await svc.find_project(rt, project)
        return await svc.set_llm_config(
            rt, p.id, base_url=base_url, model=model, api_key=key, clear_api_key=clear_api_key
        )

    p = _with_runtime(run)
    default = t("padrão", "default")
    key = t("própria", "own") if p.llm_api_key_enc else f"({default})"
    typer.echo(
        f"{t('LLM de', 'LLM of')} {p.name}: {p.llm_base_url or f'({default})'} "
        f"{p.llm_model or f'({default})'} {t('chave', 'key')}={key}"
    )


@project_app.command("tool")
def project_tool(
    project: str,
    tool: str,
    enable: Annotated[bool | None, typer.Option("--enable/--disable")] = None,
    manual: Annotated[str | None, typer.Option(help="ask | act")] = None,
) -> None:
    """Enable/disable a tool or set Ask/Act (manual mode)."""
    from .core import service as svc

    async def run(rt):
        p = await svc.find_project(rt, project)
        return await svc.set_tool_setting(rt, p.id, tool, enabled=enable, manual=manual)

    typer.echo(json.dumps(_with_runtime(run), ensure_ascii=False, indent=2))


@app.command("import")
def import_cmd(
    project: str,
    file: Path,
    fmt: Annotated[str | None, typer.Option("--format", help="har | burp (auto-detected)")] = None,
) -> None:
    """Import traffic from a HAR or the Burp XML export ("Save items")."""
    from .core import service as svc

    text = file.read_text(encoding="utf-8", errors="replace")

    async def run(rt):
        p = await svc.find_project(rt, project)
        return await svc.import_traffic(rt, p.id, text, filename=file.name, fmt=fmt)

    result = _with_runtime(run)
    typer.echo(f"{result.stored} trocas importadas, {result.skipped_out_of_scope} fora do escopo")


@app.command()
def sitemap(project: str, host: Annotated[str | None, typer.Option()] = None) -> None:
    """Show the project site map."""
    from .core import service as svc
    from .traffic import render_sitemap

    async def run(rt):
        p = await svc.find_project(rt, project)
        return await svc.sitemap(rt, p.id, host)

    typer.echo(render_sitemap(_with_runtime(run), max_endpoints=10_000))


@app.command()
def traffic(
    project: str,
    text: Annotated[str, typer.Option("--text", "-t")] = "",
    limit: Annotated[int, typer.Option()] = 30,
) -> None:
    """List the traffic history (most recent first)."""
    from .core import service as svc
    from .traffic import summarize

    async def run(rt):
        p = await svc.find_project(rt, project)
        return await svc.search_traffic(rt, p.id, text=text, limit=limit)

    for row in _with_runtime(run):
        typer.echo(summarize(row))


@app.command()
def proxy(
    project: str,
    port: Annotated[int, typer.Option(help="Proxy port")] = 8081,
    api: Annotated[str | None, typer.Option(help="scopehound API URL")] = None,
) -> None:
    """Capture proxy: browse the app and in-scope traffic goes to the project.

    Requires `scopehound serve` running and the proxy extra (`uv sync --extra proxy`).
    """
    try:
        import mitmproxy  # noqa: F401

        from .traffic.proxy import run_proxy
    except ImportError:
        _fail("instale o extra de proxy: uv sync --extra proxy")
    settings = Settings()
    api_url = api or f"http://{settings.host}:{settings.port}"
    import httpx

    try:
        projects = httpx.get(f"{api_url}/projects", timeout=5, trust_env=False).json()
    except httpx.HTTPError:
        _fail(
            t(
                f"API indisponível em {api_url}: rode `scopehound serve` antes",
                f"API unavailable at {api_url}: run `scopehound serve` first",
            )
        )
    match = [p for p in projects if project in (p["id"], p["name"])]
    if not match:
        _fail(
            t(
                f"projeto {project!r} não encontrado na API",
                f"project {project!r} not found in the API",
            )
        )
    typer.secho(
        t(
            f"proxy em 127.0.0.1:{port} → projeto {match[0]['name']}\n"
            "configure o navegador para usar este proxy e instale o certificado em http://mitm.it",
            f"proxy on 127.0.0.1:{port} → project {match[0]['name']}\n"
            "set your browser to use this proxy and install the certificate at http://mitm.it",
        ),
        fg="green",
    )
    asyncio.run(run_proxy(api_url, match[0]["id"], port))


@app.command()
def skills() -> None:
    """List the available skills."""
    from .core import service as svc

    for s in _with_runtime(svc.list_skills):
        typer.echo(f"{s['name']:18} {s['description']}")


@session_app.command("add")
def session_add(
    project: str,
    name: str,
    header: Annotated[
        list[str], typer.Option("--header", "-H", help="e.g. -H 'Cookie: token=...'")
    ],
    description: Annotated[str, typer.Option()] = "",
) -> None:
    """Register a session (cookies/headers of an identity) for replay_as."""
    from .core import service as svc

    secret: dict[str, str] = {}
    for item in header:
        if ":" not in item:
            _fail(
                t(
                    f"header inválido (use 'Nome: valor'): {item}",
                    f"invalid header (use 'Name: value'): {item}",
                )
            )
        k, v = item.split(":", 1)
        secret[k.strip()] = v.strip()

    async def run(rt):
        p = await svc.find_project(rt, project)
        await svc.set_session(rt, p.id, name, secret, description)

    _with_runtime(run)
    typer.echo(
        t(
            f"sessão '{name}' salva ({', '.join(secret)})",
            f"session '{name}' saved ({', '.join(secret)})",
        )
    )


@session_app.command("list")
def session_list(project: str) -> None:
    """List the project sessions (without showing the values)."""
    from .core import service as svc

    async def run(rt):
        p = await svc.find_project(rt, project)
        return await svc.list_sessions(rt, p.id)

    for row in _with_runtime(run):
        typer.echo(f"{row.name:16} {row.description}")


@project_app.command("source")
def project_source(
    project: str,
    path: Annotated[str | None, typer.Argument(help="Target source root; empty removes it")] = None,
) -> None:
    """Set the source root for the read_source tool (read-only)."""
    from .core import service as svc

    async def run(rt):
        p = await svc.find_project(rt, project)
        return await svc.set_source_root(rt, p.id, path)

    p = _with_runtime(run)
    typer.echo(
        t(
            f"source_root de {p.name}: {p.source_root or '(nenhum)'}",
            f"source_root of {p.name}: {p.source_root or '(none)'}",
        )
    )


@project_app.command("workspace")
def project_workspace(
    project: str,
    path: Annotated[
        str | None, typer.Argument(help="Read-write folder to read/write files; empty removes it")
    ] = None,
) -> None:
    """Set the workspace: a folder where the agent can read and write files."""
    from .core import service as svc

    async def run(rt):
        p = await svc.find_project(rt, project)
        return await svc.set_workspace_root(rt, p.id, path)

    p = _with_runtime(run)
    typer.echo(
        t(
            f"workspace de {p.name}: {p.workspace_root or '(nenhum)'}",
            f"workspace of {p.name}: {p.workspace_root or '(none)'}",
        )
    )


@app.command()
def run(
    project: str,
    goal: Annotated[str, typer.Option("--goal", "-g", help="Goal to pursue")],
    fail_on: Annotated[
        str, typer.Option("--fail-on", help="Minimum severity that fails CI (e.g. high)")
    ] = "",
    sarif: Annotated[Path | None, typer.Option("--sarif", help="Write SARIF to this file")] = None,
    mode: Annotated[str, typer.Option()] = "autonomous",
) -> None:
    """Non-interactive run (CI): pursue a goal and report the findings."""
    import sys

    from .core import service as svc
    from .report import max_severity, sarif_json, severity_at_least

    async def go(rt):
        p = await svc.find_project(rt, project)
        task = await svc.run_ci(rt, p.id, goal=goal, mode=mode)
        leads = await svc.list_leads(rt, p.id)
        return task, leads

    task, leads = _with_runtime(go)
    confirmed = [lead for lead in leads if lead.status == "confirmed"]
    typer.echo(
        t(
            f"tarefa {task.status}: {len(leads)} lead(s), {len(confirmed)} confirmado(s)",
            f"task {task.status}: {len(leads)} lead(s), {len(confirmed)} confirmed",
        )
    )
    for lead in leads:
        typer.echo(f"  [{lead.severity}] {lead.title} ({lead.status}) {lead.url}")
    if sarif:
        sarif.write_text(sarif_json(leads), encoding="utf-8")
        typer.echo(t(f"SARIF escrito em {sarif}", f"SARIF written to {sarif}"))
    if task.status == "failed":
        _fail(t(f"execução falhou: {task.error}", f"run failed: {task.error}"))
    if fail_on:
        worst = max_severity(leads)
        if worst and severity_at_least(worst, fail_on):
            typer.secho(
                t(
                    f"CI: achado {worst} >= {fail_on.upper()}",
                    f"CI: finding {worst} >= {fail_on.upper()}",
                ),
                fg="red",
            )
            sys.exit(2)
    typer.secho("CI: ok", fg="green")


@app.command()
def chat(
    project: str,
    task: Annotated[str | None, typer.Option(help="Continue an existing task")] = None,
    mode: Annotated[str, typer.Option(help="manual | smart | autonomous")] = "smart",
) -> None:
    """Chat with the agent in the terminal, with interactive approvals."""
    from .chat import run_chat

    _with_runtime(lambda rt: run_chat(rt, project, task, mode))
