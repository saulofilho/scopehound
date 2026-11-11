"""Casos de uso (usados pela API e pela CLI)."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command
from pydantic import ValidationError
from sqlalchemy import select

from ..guardrails import Scope
from ..i18n import t
from ..policy import MODES_SET, validate_response
from ..store import Action, Approval, AuditLog, Lead, Project, Task
from ..store.models import utcnow
from ..tools import TOOLS, get_tool
from .errors import Conflict, NotFound
from .runtime import Runtime
from .serialize import message_dict

LLM_POLICIES = ("any", "local_only")


def _check_mode(mode: str) -> None:
    if mode not in MODES_SET:
        raise Conflict(
            t(
                f"modo inválido: {mode} (use manual, smart ou autonomous)",
                f"invalid mode: {mode} (use manual, smart or autonomous)",
            )
        )


# ---- projetos ------------------------------------------------------------
async def create_project(
    rt: Runtime, *, name: str, scope: dict[str, Any], llm_data_policy: str = "any"
) -> Project:
    try:
        validated = Scope.model_validate(scope)
    except ValidationError as exc:
        raise Conflict(t(f"escopo inválido: {exc}", f"invalid scope: {exc}")) from exc
    if llm_data_policy not in LLM_POLICIES:
        raise Conflict(
            t(
                f"llm_data_policy inválida: {llm_data_policy}",
                f"invalid llm_data_policy: {llm_data_policy}",
            )
        )
    async with rt.db() as session:
        if await session.scalar(select(Project).where(Project.name == name)):
            raise Conflict(
                t(
                    f"já existe um projeto chamado {name!r}",
                    f"a project named {name!r} already exists",
                )
            )
        project = Project(
            name=name,
            scope=validated.model_dump(mode="json"),
            llm_data_policy=llm_data_policy,
            tool_settings={},
        )
        session.add(project)
        await session.commit()
    await rt.audit(
        project.id,
        "project.created",
        f"autorizado por {validated.authorized_by} "
        f"({validated.authorization_ref or 'sem referência'})",
    )
    return project


async def list_projects(rt: Runtime) -> list[Project]:
    async with rt.db() as session:
        return list(await session.scalars(select(Project).order_by(Project.created_at)))


async def find_project(rt: Runtime, ref: str) -> Project:
    async with rt.db() as session:
        project = await session.get(Project, ref) or await session.scalar(
            select(Project).where(Project.name == ref)
        )
    if project is None:
        raise NotFound(t(f"projeto {ref!r} não encontrado", f"project {ref!r} not found"))
    return project


async def set_llm_config(
    rt: Runtime,
    project_id: str,
    *,
    provider: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    clear_api_key: bool = False,
) -> Project:
    """Configura o LLM do projeto, inclusive com a chave do próprio usuário.
    A chave é guardada criptografada e nunca é devolvida."""
    if provider is not None and provider not in ("openai_compat", "fake"):
        raise Conflict(t(f"provedor inválido: {provider}", f"invalid provider: {provider}"))
    async with rt.db() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise NotFound(
                t(f"projeto {project_id} não encontrado", f"project {project_id} not found")
            )
        if provider is not None:
            project.llm_provider = provider or None
        if base_url is not None:
            project.llm_base_url = base_url or None
        if model is not None:
            project.llm_model = model or None
        if clear_api_key:
            project.llm_api_key_enc = None
        elif api_key:
            project.llm_api_key_enc = rt.secrets.encrypt(api_key)
        await session.commit()
    await rt.audit(
        project_id,
        "project.llm_changed",
        f"provider={provider} base_url={base_url} model={model} "
        f"chave={'removida' if clear_api_key else 'alterada' if api_key else 'mantida'}",
    )
    return await rt.get_project(project_id)


async def set_tool_setting(
    rt: Runtime,
    project_id: str,
    tool: str,
    *,
    enabled: bool | None = None,
    manual: str | None = None,
) -> dict[str, Any]:
    t = get_tool(tool)
    if t is None:
        raise NotFound(t(f"ferramenta {tool!r} não existe", f"tool {tool!r} does not exist"))
    if manual is not None:
        if manual not in ("ask", "act"):
            raise Conflict(t("manual deve ser 'ask' ou 'act'", "manual must be 'ask' or 'act'"))
        if manual == "act" and t.spec.always_ask:
            raise Conflict(
                t("esta ferramenta sempre exige aprovação", "this tool always requires approval")
            )
    async with rt.db() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise NotFound(
                t(f"projeto {project_id} não encontrado", f"project {project_id} not found")
            )
        settings = dict(project.tool_settings or {})
        current = dict(settings.get(tool, {}))
        if enabled is not None:
            current["enabled"] = enabled
        if manual is not None:
            current["manual"] = manual
        settings[tool] = current
        project.tool_settings = settings
        await session.commit()
    await rt.audit(project_id, "tool.setting_changed", f"{tool}: {current}")
    return await tool_settings(rt, project_id)


async def tool_settings(rt: Runtime, project_id: str) -> dict[str, Any]:
    from ..policy.engine import tool_setting

    project = await rt.get_project(project_id)
    return {
        name: {
            **tool_setting(t.spec, (project.tool_settings or {}).get(name)),
            "impact": t.spec.impact,
            "always_ask": t.spec.always_ask,
            "description": t.spec.description,
        }
        for name, t in TOOLS.items()
    }


async def kill_project(rt: Runtime, project_id: str, reason: str) -> None:
    async with rt.db() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise NotFound(
                t(f"projeto {project_id} não encontrado", f"project {project_id} not found")
            )
        project.killed_reason = reason or "acionado pelo analista"
        await session.commit()
    rt.kill_switch(await rt.get_project(project_id))
    await rt.audit(project_id, "project.killed", reason)


async def revive_project(rt: Runtime, project_id: str) -> None:
    async with rt.db() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise NotFound(
                t(f"projeto {project_id} não encontrado", f"project {project_id} not found")
            )
        project.killed_reason = None
        await session.commit()
    rt.reset_kill_switch(project_id)
    await rt.audit(project_id, "project.revived")


# ---- tarefas -------------------------------------------------------------
async def _check_llm_allowed(rt: Runtime, project: Project) -> None:
    try:
        rt.chat_model(project)  # falha cedo se faltar modelo ou chave
    except ValueError as exc:
        raise Conflict(str(exc)) from exc
    if project.llm_data_policy == "local_only" and not rt.llm_config(project).is_local:
        raise Conflict(
            t(
                "este projeto exige LLM local (llm_data_policy=local_only); "
                "configure um modelo local, ex.: Ollama",
                "this project requires a local LLM (llm_data_policy=local_only); "
                "configure a local model, e.g. Ollama",
            )
        )


def _parse_goal(prompt: str) -> tuple[str, str | None]:
    """`/goal <critério>` inicia um loop que persegue o critério até cumpri-lo."""
    stripped = prompt.strip()
    if stripped.startswith("/goal "):
        goal = stripped[len("/goal ") :].strip()
        return goal, goal
    return prompt, None


async def create_task(
    rt: Runtime,
    project_id: str,
    *,
    prompt: str,
    mode: str = "smart",
    title: str | None = None,
    wait: bool = False,
) -> Task:
    _check_mode(mode)
    project = await rt.get_project(project_id)
    await _check_llm_allowed(rt, project)
    content, goal = _parse_goal(prompt)
    async with rt.db() as session:
        task = Task(project_id=project_id, title=(title or content)[:200], mode=mode, goal=goal)
        session.add(task)
        await session.commit()
    await rt.audit(
        project_id, "task.created", f"modo {mode}" + (" · /goal" if goal else ""), task_id=task.id
    )
    init: dict = {"messages": [HumanMessage(content)], "finished": False, "stopped": False}
    if goal:
        init["goal"] = goal
    await _run(rt, task.id, init, wait)
    return await get_task(rt, task.id)


async def send_message(rt: Runtime, task_id: str, content: str, *, wait: bool = False) -> Task:
    task, project = await rt.load_task(task_id)
    if task.status in ("running", "waiting_approval") or rt.runner.busy(task_id):
        raise Conflict(
            t(
                f"tarefa está {task.status}; aguarde ou responda à aprovação pendente",
                f"task is {task.status}; wait or answer the pending approval",
            )
        )
    await _check_llm_allowed(rt, project)
    await _run(
        rt,
        task_id,
        {"messages": [HumanMessage(content)], "finished": False, "stopped": False},
        wait,
    )
    return await get_task(rt, task_id)


async def set_task_mode(rt: Runtime, task_id: str, mode: str) -> Task:
    _check_mode(mode)
    task, _ = await rt.load_task(task_id)
    async with rt.db() as session:
        row = await session.get(Task, task_id)
        row.mode = mode
        await session.commit()
    await rt.audit(task.project_id, "task.mode_changed", f"{task.mode} -> {mode}", task_id=task_id)
    return await get_task(rt, task_id)


async def get_task(rt: Runtime, task_id: str) -> Task:
    task, _ = await rt.load_task(task_id)
    return task


async def list_tasks(rt: Runtime, project_id: str) -> list[Task]:
    async with rt.db() as session:
        return list(
            await session.scalars(
                select(Task).where(Task.project_id == project_id).order_by(Task.created_at)
            )
        )


async def get_messages(rt: Runtime, task_id: str) -> list[dict[str, Any]]:
    await rt.load_task(task_id)
    snapshot = await rt.graph.aget_state({"configurable": {"thread_id": task_id}})
    return [message_dict(m) for m in snapshot.values.get("messages", [])]


async def _run(rt: Runtime, task_id: str, graph_input: Any, wait: bool) -> None:
    if wait:
        await rt.runner.run(task_id, graph_input)
    else:
        rt.runner.start(task_id, graph_input)


# ---- aprovações ----------------------------------------------------------
async def list_approvals(rt: Runtime, task_id: str, status: str | None = None) -> list[Approval]:
    async with rt.db() as session:
        query = select(Approval).where(Approval.task_id == task_id)
        if status:
            query = query.where(Approval.status == status)
        return list(await session.scalars(query.order_by(Approval.created_at)))


async def resolve_approval(
    rt: Runtime, approval_id: str, response: str, note: str = "", *, wait: bool = False
) -> Approval:
    async with rt.db() as session:
        approval = await session.get(Approval, approval_id)
        if approval is None:
            raise NotFound(
                t(f"aprovação {approval_id} não encontrada", f"approval {approval_id} not found")
            )
        if approval.status != "pending":
            raise Conflict(
                t("esta aprovação já foi respondida", "this approval was already answered")
            )
        task = await session.get(Task, approval.task_id)
        spec = get_tool(approval.tool).spec
        try:
            validate_response(response, mode=task.mode, spec=spec)
        except ValueError as exc:
            raise Conflict(str(exc)) from exc
        snapshot = await rt.graph.aget_state({"configurable": {"thread_id": task.id}})
        pending = [i.value.get("approval_id") for i in snapshot.interrupts]
        if not pending or pending[0] != approval_id:
            raise Conflict(
                t(
                    "esta aprovação não é a próxima pendente da tarefa",
                    "this approval is not the task's next pending one",
                )
            )
        approval.status = "approved" if response in ("once", "session", "always") else "rejected"
        approval.response = response
        approval.note = note or None
        approval.resolved_at = utcnow()
        await session.commit()
        project_id = task.project_id
    await rt.audit(
        project_id,
        "approval.resolved",
        f"{approval.tool} {approval.args} -> {response} {note}".strip(),
        task_id=approval.task_id,
    )
    await _run(rt, approval.task_id, Command(resume={"response": response, "note": note}), wait)
    return approval


# ---- consultas -----------------------------------------------------------
async def list_leads(rt: Runtime, project_id: str) -> list[Lead]:
    async with rt.db() as session:
        return list(
            await session.scalars(
                select(Lead).where(Lead.project_id == project_id).order_by(Lead.created_at)
            )
        )


async def list_actions(rt: Runtime, task_id: str) -> list[Action]:
    async with rt.db() as session:
        return list(
            await session.scalars(
                select(Action).where(Action.task_id == task_id).order_by(Action.created_at)
            )
        )


async def list_audit(rt: Runtime, project_id: str, limit: int = 200) -> list[AuditLog]:
    async with rt.db() as session:
        return list(
            await session.scalars(
                select(AuditLog)
                .where(AuditLog.project_id == project_id)
                .order_by(AuditLog.id.desc())
                .limit(limit)
            )
        )


# ---- tráfego -------------------------------------------------------------
async def ingest_traffic(rt: Runtime, project_id: str, exchanges: list, source: str):
    from ..traffic import ExchangeIn

    project = await rt.get_project(project_id)
    items = [e if isinstance(e, ExchangeIn) else ExchangeIn.from_json(e) for e in exchanges]
    return await rt.traffic(project).ingest(items, source)


async def import_traffic(
    rt: Runtime, project_id: str, text: str, *, filename: str = "", fmt: str | None = None
):
    from ..traffic.importers import detect_format, parse_traffic

    try:
        fmt = fmt or detect_format(filename, text)
        exchanges = parse_traffic(text, fmt)
    except ValueError as exc:
        raise Conflict(t(f"arquivo inválido: {exc}", f"invalid file: {exc}")) from exc
    except Exception as exc:  # XML malformado ou com entidades proibidas
        raise Conflict(
            t(
                f"arquivo inválido ({type(exc).__name__}): {exc}",
                f"invalid file ({type(exc).__name__}): {exc}",
            )
        ) from exc
    result = await ingest_traffic(rt, project_id, exchanges, fmt)
    await rt.audit(
        project_id,
        "traffic.imported",
        f"{fmt}: {result.stored} guardadas, {result.skipped_out_of_scope} fora do escopo",
    )
    return result


async def search_traffic(rt: Runtime, project_id: str, **filters):
    return await rt.traffic(await rt.get_project(project_id)).search(**filters)


async def get_exchange(rt: Runtime, project_id: str, ref: str):
    row = await rt.traffic(await rt.get_project(project_id)).get(ref)
    if row is None:
        raise NotFound(t(f"troca {ref!r} não encontrada", f"exchange {ref!r} not found"))
    return row


async def sitemap(rt: Runtime, project_id: str, host: str | None = None):
    return await rt.traffic(await rt.get_project(project_id)).sitemap(host)


# ---- sessões de autenticação e código-fonte ------------------------------
async def set_session(
    rt: Runtime, project_id: str, name: str, secret: dict, description: str = ""
) -> None:
    await rt.get_project(project_id)
    if not secret:
        raise Conflict("informe pelo menos um header (ex.: Cookie ou Authorization)")
    await rt.set_auth_session(
        project_id, name, {str(k): str(v) for k, v in secret.items()}, description
    )
    await rt.audit(project_id, "session.set", f"{name}: {sorted(secret)}")


async def list_sessions(rt: Runtime, project_id: str):
    return await rt.list_auth_sessions(project_id)


async def set_workspace_root(rt: Runtime, project_id: str, path: str | None) -> Project:
    """Define a pasta read-write do projeto para as ferramentas de arquivo.
    Recusa pastas reservadas (ex.: o diretório de dados do scopehound)."""
    from ..fsguard import WorkspaceError, check_not_reserved, resolve_root

    if path:
        root = resolve_root(path)
        if not root.is_dir():
            raise Conflict(t(f"diretório não encontrado: {path}", f"folder not found: {path}"))
        try:
            check_not_reserved(root, [rt.settings.data_dir])
        except WorkspaceError as exc:
            raise Conflict(str(exc)) from exc
        path = str(root)
    async with rt.db() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise NotFound(
                t(f"projeto {project_id} não encontrado", f"project {project_id} not found")
            )
        project.workspace_root = path
        await session.commit()
    await rt.audit(project_id, "project.workspace_root", path or "(removido)")
    return await rt.get_project(project_id)


async def set_source_root(rt: Runtime, project_id: str, path: str | None) -> Project:
    from pathlib import Path

    if path:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_dir():
            raise Conflict(t(f"diretório não encontrado: {path}", f"folder not found: {path}"))
        path = str(resolved)
    async with rt.db() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise NotFound(
                t(f"projeto {project_id} não encontrado", f"project {project_id} not found")
            )
        project.source_root = path
        await session.commit()
    await rt.audit(project_id, "project.source_root", path or "(removido)")
    return await rt.get_project(project_id)


async def list_skills(rt: Runtime):
    return rt.library.catalog()


async def list_subtasks(rt: Runtime, parent_id: str):
    from sqlalchemy import select as _select

    from ..store import Task as _Task

    async with rt.db() as session:
        return list(
            await session.scalars(
                _select(_Task).where(_Task.parent_id == parent_id).order_by(_Task.created_at)
            )
        )


# ---- modo CI -------------------------------------------------------------
async def run_ci(rt: Runtime, project_id: str, *, goal: str, mode: str = "autonomous") -> Task:
    """Roda uma tarefa /goal até o fim (uso não interativo). Em CI, use o modo
    autônomo e aprovações desligadas (nenhuma ferramenta always_ask habilitada)."""
    prompt = goal if goal.strip().startswith("/goal ") else f"/goal {goal}"
    return await create_task(rt, project_id, prompt=prompt, mode=mode, wait=True)
