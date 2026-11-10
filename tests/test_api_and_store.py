import httpx
from conftest import LAB_SCOPE
from sqlalchemy import create_engine

from scopehound.agent.fake import tool_call
from scopehound.api import create_app
from scopehound.core.events import EventBus


async def test_api_end_to_end(harness):
    harness.model.script = [
        tool_call("send_request", {"method": "POST", "url": "http://app.lab/api/x"}, "c1"),
        tool_call("finish", {"summary": "ok"}, "c2"),
    ]
    async with harness.runtime() as rt:
        app = create_app(rt, manage_runtime=False)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post("/projects", json={"name": "lab", "scope": LAB_SCOPE})
            assert r.status_code == 201
            pid = r.json()["id"]
            r = await client.put(f"/projects/{pid}/llm", json={"api_key": "segredo-do-usuario"})
            assert r.json()["llm_api_key"] and "segredo" not in r.text
            r = await client.post(f"/projects/{pid}/tasks", json={"prompt": "vai"})
            assert r.status_code == 201
            tid = r.json()["id"]
            await rt.runner.wait(tid)
            r = await client.get(f"/tasks/{tid}/approvals", params={"status": "pending"})
            [approval] = r.json()
            r = await client.post(f"/approvals/{approval['id']}", json={"response": "always"})
            assert r.status_code == 409  # 'sempre aprovar' só no modo manual
            r = await client.post(f"/approvals/{approval['id']}", json={"response": "once"})
            assert r.status_code == 200
            await rt.runner.wait(tid)
            assert (await client.get(f"/tasks/{tid}")).json()["status"] == "done"
            msgs = (await client.get(f"/tasks/{tid}/messages")).json()
            assert [m["role"] for m in msgs] == ["human", "ai", "tool", "ai", "tool"]
            assert (await client.get("/projects/nao-existe")).status_code == 404
            r = await client.post("/projects", json={"name": "lab", "scope": LAB_SCOPE})
            assert r.status_code == 409


async def test_event_bus():
    bus = EventBus()
    async with bus.subscribe("t1") as queue:
        bus.publish("t1", {"type": "status"})
        bus.publish("t2", {"type": "outro"})
        assert await queue.get() == {"type": "status"}
        assert queue.empty()


def test_migrations_match_models(tmp_path):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from scopehound.store import Base, run_migrations

    url = f"sqlite:///{tmp_path / 'm.db'}"
    run_migrations(url)
    with create_engine(url).connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


async def test_restart_marks_running_tasks_idle(harness):
    from scopehound.core import service as svc
    from scopehound.store import Task

    async with harness.runtime() as rt:
        project = await svc.create_project(rt, name="lab", scope=LAB_SCOPE)
        async with rt.db() as session:
            task = Task(project_id=project.id, title="t", status="running")
            session.add(task)
            await session.commit()
    async with harness.runtime() as rt:
        task = await svc.get_task(rt, task.id)
        assert task.status == "idle" and "reinício" in task.error
