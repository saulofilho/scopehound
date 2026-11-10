"""API HTTP (FastAPI). No modo local, escuta só em 127.0.0.1.

Autenticação (OIDC) chega na Fase 5; até lá o modo servidor não deve ser
exposto em rede.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..core import Conflict, NotFound, Runtime
from ..core import service as svc
from ..core.serialize import project_dict, row_dict


class ProjectIn(BaseModel):
    name: str
    scope: dict[str, Any]
    llm_data_policy: str = "any"


class LlmIn(BaseModel):
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = Field(default=None, description="Nunca é devolvida pela API")
    clear_api_key: bool = False


class ToolSettingIn(BaseModel):
    enabled: bool | None = None
    manual: str | None = None


class TaskIn(BaseModel):
    prompt: str
    mode: str = "smart"
    title: str | None = None


class MessageIn(BaseModel):
    content: str


class ModeIn(BaseModel):
    mode: str


class ApprovalIn(BaseModel):
    response: str
    note: str = ""


class TrafficIn(BaseModel):
    exchanges: list[dict[str, Any]] = Field(max_length=500)
    source: str = "proxy"


class SessionIn(BaseModel):
    name: str
    secret: dict[str, str]
    description: str = ""


class SourceIn(BaseModel):
    path: str | None = None


class KillIn(BaseModel):
    reason: str = ""


def create_app(runtime: Runtime, *, manage_runtime: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if manage_runtime:
            await runtime.start()
        try:
            yield
        finally:
            if manage_runtime:
                await runtime.close()

    app = FastAPI(title="scopehound", version="0.1.0", lifespan=lifespan)
    rt = runtime

    def guard(coro):
        async def wrapper():
            try:
                return await coro
            except NotFound as exc:
                raise HTTPException(404, str(exc)) from exc
            except Conflict as exc:
                raise HTTPException(409, str(exc)) from exc

        return wrapper()

    @app.get("/health")
    async def health():
        return {"ok": True, "mode": rt.settings.mode}

    # projetos
    @app.post("/projects", status_code=201)
    async def create_project(body: ProjectIn):
        return project_dict(await guard(svc.create_project(rt, **body.model_dump())))

    @app.get("/projects")
    async def list_projects():
        return [project_dict(p) for p in await svc.list_projects(rt)]

    @app.get("/projects/{project_id}")
    async def get_project(project_id: str):
        return project_dict(await guard(rt.get_project(project_id)))

    @app.put("/projects/{project_id}/llm")
    async def set_llm(project_id: str, body: LlmIn):
        return project_dict(await guard(svc.set_llm_config(rt, project_id, **body.model_dump())))

    @app.get("/projects/{project_id}/tools")
    async def get_tools(project_id: str):
        return await guard(svc.tool_settings(rt, project_id))

    @app.put("/projects/{project_id}/tools/{tool}")
    async def put_tool(project_id: str, tool: str, body: ToolSettingIn):
        return await guard(svc.set_tool_setting(rt, project_id, tool, **body.model_dump()))

    @app.post("/projects/{project_id}/kill")
    async def kill(project_id: str, body: KillIn):
        await guard(svc.kill_project(rt, project_id, body.reason))
        return {"killed": True}

    @app.post("/projects/{project_id}/revive")
    async def revive(project_id: str):
        await guard(svc.revive_project(rt, project_id))
        return {"killed": False}

    @app.get("/projects/{project_id}/leads")
    async def leads(project_id: str):
        return [row_dict(r) for r in await svc.list_leads(rt, project_id)]

    @app.get("/projects/{project_id}/audit")
    async def audit(project_id: str, limit: int = 200):
        return [row_dict(r) for r in await svc.list_audit(rt, project_id, limit)]

    # skills, sessões e código-fonte
    @app.get("/skills")
    async def skills():
        return await svc.list_skills(rt)

    @app.get("/projects/{project_id}/sessions")
    async def sessions(project_id: str):
        return [
            {"name": r.name, "description": r.description}
            for r in await guard(svc.list_sessions(rt, project_id))
        ]

    @app.put("/projects/{project_id}/sessions")
    async def put_session(project_id: str, body: SessionIn):
        await guard(svc.set_session(rt, project_id, body.name, body.secret, body.description))
        return {"name": body.name}

    @app.put("/projects/{project_id}/source")
    async def put_source(project_id: str, body: SourceIn):
        return project_dict(await guard(svc.set_source_root(rt, project_id, body.path)))

    @app.get("/tasks/{task_id}/subtasks")
    async def subtasks(task_id: str):
        return [row_dict(t) for t in await svc.list_subtasks(rt, task_id)]

    # tráfego
    @app.post("/projects/{project_id}/traffic")
    async def ingest(project_id: str, body: TrafficIn):
        if body.source not in ("proxy", "api"):
            raise HTTPException(422, "source deve ser proxy ou api")
        result = await guard(svc.ingest_traffic(rt, project_id, body.exchanges, body.source))
        return {"stored": result.stored, "skipped_out_of_scope": result.skipped_out_of_scope}

    @app.post("/projects/{project_id}/traffic/import")
    async def import_file(
        project_id: str, request: Request, format: str | None = None, filename: str = ""
    ):
        text = (await request.body()).decode("utf-8", errors="replace")
        result = await guard(
            svc.import_traffic(rt, project_id, text, filename=filename, fmt=format)
        )
        return {"stored": result.stored, "skipped_out_of_scope": result.skipped_out_of_scope}

    @app.get("/projects/{project_id}/traffic")
    async def traffic(
        project_id: str,
        text: str = "",
        host: str = "",
        method: str = "",
        path_contains: str = "",
        status: int | None = None,
        param: str = "",
        source: str = "",
        limit: int = 50,
        offset: int = 0,
    ):
        rows = await guard(
            svc.search_traffic(
                rt,
                project_id,
                text=text,
                host=host,
                method=method,
                path_contains=path_contains,
                status=status,
                param=param,
                source=source,
                limit=limit,
                offset=offset,
            )
        )
        return [
            row_dict(
                r, exclude={"request_body", "response_body", "request_headers", "response_headers"}
            )
            for r in rows
        ]

    @app.get("/projects/{project_id}/traffic/{exchange_id}")
    async def exchange(project_id: str, exchange_id: str):
        return row_dict(await guard(svc.get_exchange(rt, project_id, exchange_id)))

    @app.get("/projects/{project_id}/sitemap")
    async def get_sitemap(project_id: str, host: str | None = None):
        data = await guard(svc.sitemap(rt, project_id, host))
        return {origin: [e.to_json() for e in eps] for origin, eps in data.items()}

    # tarefas
    @app.post("/projects/{project_id}/tasks", status_code=201)
    async def create_task(project_id: str, body: TaskIn):
        return row_dict(await guard(svc.create_task(rt, project_id, **body.model_dump())))

    @app.get("/projects/{project_id}/tasks")
    async def list_tasks(project_id: str):
        return [row_dict(t) for t in await svc.list_tasks(rt, project_id)]

    @app.get("/tasks/{task_id}")
    async def get_task(task_id: str):
        return row_dict(await guard(svc.get_task(rt, task_id)))

    @app.patch("/tasks/{task_id}")
    async def patch_task(task_id: str, body: ModeIn):
        return row_dict(await guard(svc.set_task_mode(rt, task_id, body.mode)))

    @app.get("/tasks/{task_id}/messages")
    async def messages(task_id: str):
        return await guard(svc.get_messages(rt, task_id))

    @app.post("/tasks/{task_id}/messages", status_code=202)
    async def post_message(task_id: str, body: MessageIn):
        return row_dict(await guard(svc.send_message(rt, task_id, body.content)))

    @app.get("/tasks/{task_id}/actions")
    async def actions(task_id: str):
        return [row_dict(a) for a in await svc.list_actions(rt, task_id)]

    @app.get("/tasks/{task_id}/approvals")
    async def approvals(task_id: str, status: str | None = None):
        return [row_dict(a) for a in await svc.list_approvals(rt, task_id, status)]

    @app.post("/approvals/{approval_id}")
    async def resolve(approval_id: str, body: ApprovalIn):
        approval = await guard(svc.resolve_approval(rt, approval_id, body.response, body.note))
        return row_dict(approval)

    @app.get("/tasks/{task_id}/events")
    async def events(task_id: str, request: Request):
        await guard(svc.get_task(rt, task_id))

        async def stream() -> AsyncIterator[str]:
            async with rt.events.subscribe(task_id) as queue:
                yield ": conectado\n\n"
                while not await request.is_disconnected():
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15)
                    except TimeoutError:
                        yield ": ping\n\n"
                        continue
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    # interface web (app de página única, sem build; servido pela própria API)
    web_dir = Path(__file__).resolve().parent.parent / "web"
    if web_dir.is_dir():
        app.mount("/app", StaticFiles(directory=web_dir, html=True), name="web")

        @app.get("/")
        async def index():
            return RedirectResponse("/app/")

    return app
