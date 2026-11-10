"""Casos de uso (usados pela API e pela CLI)."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command
from pydantic import ValidationError
from sqlalchemy import select

from ..guardrails import Scope
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
        raise Conflict(f"modo inválido: {mode} (use manual, smart ou autonomous)")


# ---- projetos ------------------------------------------------------------
async def create_project(
    rt: Runtime, *, name: str, scope: dict[str, Any], llm_data_policy: str = "any"
) -> Project:
    try:
        validated = Scope.model_validate(scope)
    except ValidationError as exc:
        raise Conflict(f"escopo inválido: {exc}") from exc
    if llm_data_policy not in LLM_POLICIES:
        raise Conflict(f"llm_data_policy inválida: {llm_data_policy}")
    async with rt.db() as session:
        if await session.scalar(select(Project).where(Project.name == name)):
            raise Conflict(f"já existe um projeto chamado {name!r}")
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
        raise NotFound(f"projeto {ref!r} não encontrado")
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
        raise Conflict(f"provedor inválido: {provider}")
    async with rt.db() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise NotFound(f"projeto {project_id} não encontrado")
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
        raise NotFound(f"ferramenta {tool!r} não existe")
    if manual is not None:
        if manual not in ("ask", "act"):
            raise Conflict("manual deve ser 'ask' ou 'act'")
        if manual == "act" and t.spec.always_ask:
            raise Conflict("esta ferramenta sempre exige aprovação")
    async with rt.db() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise NotFound(f"projeto {project_id} não encontrado")
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
            raise NotFound(f"projeto {project_id} não encontrado")
        project.killed_reason = reason or "acionado pelo analista"
        await session.commit()
    rt.kill_switch(await rt.get_project(project_id))
    await rt.audit(project_id, "project.killed", reason)


async def revive_project(rt: Runtime, project_id: str) -> None:
    async with rt.db() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise NotFound(f"projeto {project_id} não encontrado")
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
            "este projeto exige LLM local (llm_data_policy=local_only); "
            "configure um modelo local, ex.: Ollama"
        )


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
    async with rt.db() as session:
        task = Task(project_id=project_id, title=(title or prompt)[:200], mode=mode)
        session.add(task)
        await session.commit()
    await rt.audit(project_id, "task.created", f"modo {mode}", task_id=task.id)
    await _run(
        rt, task.id, {"messages": [HumanMessage(prompt)], "finished": False, "stopped": False}, wait
    )
    return await get_task(rt, task.id)


async def send_message(rt: Runtime, task_id: str, content: str, *, wait: bool = False) -> Task:
    task, project = await rt.load_task(task_id)
    if task.status in ("running", "waiting_approval") or rt.runner.busy(task_id):
        raise Conflict(f"tarefa está {task.status}; aguarde ou responda à aprovação pendente")
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
            raise NotFound(f"aprovação {approval_id} não encontrada")
        if approval.status != "pending":
            raise Conflict("esta aprovação já foi respondida")
        task = await session.get(Task, approval.task_id)
        spec = get_tool(approval.tool).spec
        try:
            validate_response(response, mode=task.mode, spec=spec)
        except ValueError as exc:
            raise Conflict(str(exc)) from exc
        snapshot = await rt.graph.aget_state({"configurable": {"thread_id": task.id}})
        pending = [i.value.get("approval_id") for i in snapshot.interrupts]
        if not pending or pending[0] != approval_id:
            raise Conflict("esta aprovação não é a próxima pendente da tarefa")
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
