"""Runtime: junta banco, checkpoints, grafo, eventos e guardrails."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import select, update

from ..agent.graph import build_graph
from ..agent.llm import LlmConfig, build_chat_model
from ..config import Settings
from ..guardrails import AuditEvent, Budget, Egress, KillSwitch, RateLimiter, Resolver, Scope
from ..policy import Decision
from ..secrets import SecretBox, load_secret_key
from ..skills import load_skills
from ..store import (
    Action,
    Approval,
    AuditLog,
    AuthSession,
    Database,
    Lead,
    Project,
    Task,
    run_migrations,
)
from ..store.models import utcnow
from ..tools import ToolContext
from ..traffic import TrafficStore
from .errors import NotFound
from .events import EventBus
from .runner import TaskRunner

LlmFactory = Callable[[LlmConfig], BaseChatModel]


class Runtime:
    def __init__(
        self,
        settings: Settings,
        *,
        llm_factory: LlmFactory = build_chat_model,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver | None = None,
    ) -> None:
        self.settings = settings
        self.llm_factory = llm_factory
        self.transport = transport
        self.resolver = resolver
        self.events = EventBus()
        self.runner = TaskRunner(self)
        self._kill: dict[str, KillSwitch] = {}
        self._limiters: dict[str, RateLimiter] = {}
        self.task_caps: dict[str, tuple[int, int]] = {}
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> Runtime:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def start(self) -> None:
        s = self.settings
        s.data_dir.mkdir(parents=True, exist_ok=True)
        url = s.resolved_database_url()
        await asyncio.to_thread(run_migrations, url)
        self.db = Database(url)
        key = s.secret_key.get_secret_value() if s.secret_key else None
        self.secrets = SecretBox(load_secret_key(key, s.data_dir, mode=s.mode))
        saver = await self._stack.enter_async_context(
            AsyncSqliteSaver.from_conn_string(str(s.checkpoint_path()))
        )
        self.library = load_skills(tuple(s.skill_dirs))
        self.graph = build_graph(self).compile(checkpointer=saver)
        # Tarefas que estavam rodando quando o processo caiu.
        async with self.db() as session:
            await session.execute(
                update(Task)
                .where(Task.status == "running")
                .values(status="idle", error="interrompida por reinício do processo")
            )
            await session.commit()

    async def close(self) -> None:
        await self.runner.cancel_all()
        await self._stack.aclose()
        await self.db.dispose()

    # ---- leitura -------------------------------------------------------
    async def get_project(self, project_id: str) -> Project:
        async with self.db() as session:
            project = await session.get(Project, project_id)
        if project is None:
            raise NotFound(f"projeto {project_id} não encontrado")
        return project

    async def load_task(self, task_id: str) -> tuple[Task, Project]:
        async with self.db() as session:
            task = await session.get(Task, task_id)
            if task is None:
                raise NotFound(f"tarefa {task_id} não encontrada")
            project = await session.get(Project, task.project_id)
        return task, project

    # ---- LLM -----------------------------------------------------------
    def llm_config(self, project: Project) -> LlmConfig:
        s = self.settings
        api_key = (
            self.secrets.decrypt(project.llm_api_key_enc)
            if project.llm_api_key_enc
            else (s.llm_api_key.get_secret_value() if s.llm_api_key else None)
        )
        return LlmConfig(
            provider=project.llm_provider or s.llm_provider,
            base_url=project.llm_base_url or s.llm_base_url,
            model=project.llm_model or s.llm_model,
            api_key=api_key,
            temperature=s.llm_temperature,
        )

    def chat_model(self, project: Project) -> BaseChatModel:
        return self.llm_factory(self.llm_config(project))

    # ---- guardrails por projeto ------------------------------------------
    def traffic(self, project: Project) -> TrafficStore:
        return TrafficStore(self.db, project.id, Scope.model_validate(project.scope))

    def kill_switch(self, project: Project) -> KillSwitch:
        ks = self._kill.get(project.id)
        if ks is None:
            ks = self._kill[project.id] = KillSwitch()
        if project.killed_reason and not ks.tripped:
            ks.trip(project.killed_reason)
        return ks

    def reset_kill_switch(self, project_id: str) -> None:
        self._kill.pop(project_id, None)

    def rate_limiter(self, project: Project, scope: Scope) -> RateLimiter:
        limiter = self._limiters.get(project.id)
        if limiter is None or limiter.rate != scope.max_requests_per_second:
            limiter = self._limiters[project.id] = RateLimiter(scope.max_requests_per_second)
        return limiter

    @asynccontextmanager
    async def tool_context(self, task_id: str) -> AsyncIterator[ToolContext]:
        task, project = await self.load_task(task_id)
        s = self.settings
        scope = Scope.model_validate(project.scope)
        budget = Budget(
            max_steps=s.task_max_steps,
            max_requests=s.task_max_requests,
            max_tokens=s.task_max_tokens,
            requests=task.requests_used,
        )
        events: list[AuditEvent] = []
        egress = Egress(
            scope,
            budget=budget,
            ip_policy=s.ip_policy(),
            kill_switch=self.kill_switch(project),
            rate_limiter=self.rate_limiter(project, scope),
            transport=self.transport,
            verify_tls=s.verify_tls,
            timeout=s.request_timeout,
            max_response_bytes=s.max_response_bytes,
            user_agent=s.user_agent,
            audit=events.append,
            **({"resolver": self.resolver} if self.resolver else {}),
        )

        async def save_lead(**fields: Any) -> str:
            return await self.save_lead(project.id, task_id, **fields)

        async def confirm_lead(lead_id: str, evidence: str) -> bool:
            return await self.confirm_lead(project.id, lead_id, evidence)

        try:
            traffic = TrafficStore(self.db, project.id, scope, task_id)

            async def get_session(name: str) -> dict[str, str] | None:
                return await self.get_auth_session(project.id, name)

            async def spawn(**kw: Any) -> str:
                return await self.spawn_subagent(project.id, task_id, **kw)

            source_root = Path(project.source_root) if project.source_root else None
            yield ToolContext(
                project.id,
                task_id,
                egress,
                save_lead,
                confirm_lead,
                traffic,
                get_session=get_session,
                library=self.library,
                source_root=source_root,
                spawn=spawn,
            )
        finally:
            await egress.aclose()
            await self.add_usage(task_id, requests=budget.requests - task.requests_used)
            await self.write_egress_audit(project.id, task_id, events)

    # ---- escrita ---------------------------------------------------------
    async def add_usage(self, task_id: str, *, steps: int = 0, tokens: int = 0, requests: int = 0):
        async with self.db() as session:
            await session.execute(
                update(Task)
                .where(Task.id == task_id)
                .values(
                    steps_used=Task.steps_used + steps,
                    tokens_used=Task.tokens_used + tokens,
                    requests_used=Task.requests_used + requests,
                )
            )
            await session.commit()

    async def set_task_status(self, task_id: str, status: str, *, error: str | None = None):
        async with self.db() as session:
            task = await session.get(Task, task_id)
            task.status = status
            task.error = error
            await session.commit()
        self.events.publish(task_id, {"type": "status", "status": status, "error": error})

    async def ensure_approval(self, task_id: str, call: dict[str, Any], decision: Decision) -> str:
        """Cria o pedido de aprovação uma única vez (o nó de política é
        reexecutado na retomada)."""
        async with self.db() as session:
            existing = await session.scalar(
                select(Approval).where(
                    Approval.task_id == task_id, Approval.tool_call_id == call["id"]
                )
            )
            if existing is not None:
                return existing.id
            approval = Approval(
                task_id=task_id,
                tool_call_id=call["id"],
                tool=call["name"],
                args=call["args"],
                impact=decision.impact,
                reason=decision.reason,
            )
            session.add(approval)
            await session.commit()
            return approval.id

    async def set_tool_manual(self, project_id: str, tool: str, value: str) -> None:
        async with self.db() as session:
            project = await session.get(Project, project_id)
            settings = dict(project.tool_settings or {})
            settings[tool] = {**settings.get(tool, {}), "manual": value}
            project.tool_settings = settings
            await session.commit()

    async def record_action(self, task_id: str, call: dict[str, Any], outcome: str, text: str):
        async with self.db() as session:
            session.add(
                Action(
                    task_id=task_id,
                    tool_call_id=call["id"],
                    tool=call["name"],
                    args=call["args"],
                    outcome=outcome,
                    result=text[:20_000],
                )
            )
            await session.commit()

    async def save_lead(self, project_id: str, task_id: str | None, **fields: Any) -> str:
        async with self.db() as session:
            lead = Lead(project_id=project_id, task_id=task_id, **fields)
            session.add(lead)
            await session.commit()
            return lead.id

    async def confirm_lead(self, project_id: str, lead_id: str, evidence: str) -> bool:
        async with self.db() as session:
            lead = await session.get(Lead, lead_id)
            if lead is None or lead.project_id != project_id:
                return False
            lead.status = "confirmed"
            lead.evidence = f"{lead.evidence}\n\n{evidence}"
            await session.commit()
            return True

    async def audit(
        self,
        project_id: str,
        kind: str,
        detail: str = "",
        *,
        actor: str = "user",
        task_id: str | None = None,
    ) -> None:
        async with self.db() as session:
            session.add(
                AuditLog(
                    project_id=project_id,
                    task_id=task_id,
                    actor=actor,
                    kind=kind,
                    detail=detail,
                    created_at=utcnow(),
                )
            )
            await session.commit()

    # ---- sessões de autenticação ----------------------------------------
    async def set_auth_session(
        self, project_id: str, name: str, secret: dict[str, str], description: str = ""
    ) -> None:
        token = self.secrets.encrypt(__import__("json").dumps(secret))
        async with self.db() as session:
            existing = await session.scalar(
                select(AuthSession).where(
                    AuthSession.project_id == project_id, AuthSession.name == name
                )
            )
            if existing is None:
                session.add(
                    AuthSession(
                        project_id=project_id, name=name, secret_enc=token, description=description
                    )
                )
            else:
                existing.secret_enc = token
                existing.description = description
            await session.commit()

    async def get_auth_session(self, project_id: str, name: str) -> dict[str, str] | None:
        async with self.db() as session:
            row = await session.scalar(
                select(AuthSession).where(
                    AuthSession.project_id == project_id, AuthSession.name == name
                )
            )
        if row is None:
            return None
        return __import__("json").loads(self.secrets.decrypt(row.secret_enc))

    async def list_auth_sessions(self, project_id: str) -> list[AuthSession]:
        async with self.db() as session:
            return list(
                await session.scalars(
                    select(AuthSession)
                    .where(AuthSession.project_id == project_id)
                    .order_by(AuthSession.name)
                )
            )

    # ---- subagentes ------------------------------------------------------
    async def spawn_subagent(
        self,
        project_id: str,
        parent_id: str,
        *,
        title: str,
        prompt: str,
        skill: str | None = None,
        max_steps: int = 10,
        max_requests: int = 40,
    ) -> str:
        from langchain_core.messages import HumanMessage

        parent, project = await self.load_task(parent_id)
        # orçamento dividido: o filho não pode pedir mais do que resta ao pai
        s = self.settings
        steps_left = max(0, s.task_max_steps - parent.steps_used)
        reqs_left = max(0, s.task_max_requests - parent.requests_used)
        max_steps = min(max_steps, steps_left)
        max_requests = min(max_requests, reqs_left)
        if max_steps < 1:
            return "sem orçamento restante para subagente."
        async with self.db() as sess:
            child = Task(
                project_id=project_id, parent_id=parent_id, title=title[:200], mode=parent.mode
            )
            sess.add(child)
            await sess.commit()
            child_id = child.id
        init: dict[str, Any] = {
            "messages": [HumanMessage(prompt)],
            "finished": False,
            "stopped": False,
        }
        if skill:
            init["active_skill"] = skill
        await self.audit(
            project_id, "subagent.spawned", f"{title} (pai {parent_id})", task_id=child_id
        )
        # roda já (sequencial): o modelo pai aguarda o resultado
        status = await self.runner.run(child_id, init, step_cap=max_steps, request_cap=max_requests)
        child = await self.get_task_row(child_id)
        messages = await self.graph.aget_state({"configurable": {"thread_id": child_id}})
        summary = ""
        for m in reversed(messages.values.get("messages", [])):
            if m.type == "ai" and m.content:
                summary = m.content
                break
        leads = await self.subagent_leads(child_id)
        # cobra o consumo do filho no pai
        await self.add_usage(
            parent_id,
            steps=child.steps_used,
            requests=child.requests_used,
            tokens=child.tokens_used,
        )
        lead_text = f" Leads: {leads}." if leads else ""
        return (
            f"subagente '{title}' terminou ({status}, {child.steps_used} passos, "
            f"{child.requests_used} req).{lead_text}\n"
            f"Resumo: {summary or '(sem resumo)'}"
        )

    async def get_task_row(self, task_id: str) -> Task:
        async with self.db() as session:
            return await session.get(Task, task_id)

    async def subagent_leads(self, task_id: str) -> int:
        from sqlalchemy import func

        async with self.db() as session:
            return (
                await session.scalar(
                    select(func.count()).select_from(Lead).where(Lead.task_id == task_id)
                )
                or 0
            )

    async def write_egress_audit(self, project_id: str, task_id: str, events: list[AuditEvent]):
        if not events:
            return
        async with self.db() as session:
            for e in events:
                session.add(
                    AuditLog(
                        project_id=project_id,
                        task_id=task_id,
                        actor="agent",
                        kind=f"egress.{e.kind}",
                        detail=e.detail,
                        method=e.method,
                        url=e.url,
                        resolved_ip=e.resolved_ip,
                        status_code=e.status,
                    )
                )
            await session.commit()
