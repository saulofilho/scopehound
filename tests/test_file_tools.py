import pytest
from conftest import LAB_SCOPE, Harness
from cryptography.fernet import Fernet

from scopehound.agent.fake import tool_call
from scopehound.core import Conflict
from scopehound.core import service as svc


async def seed_ws(rt, tmp_path, name="lab"):
    ws = tmp_path / "work"
    ws.mkdir()
    (ws / "2tobetested.txt").write_text("http://a.lab\nhttp://b.lab\n")
    project = await svc.create_project(rt, name=name, scope=LAB_SCOPE)
    await svc.set_workspace_root(rt, project.id, str(ws))
    return project, ws


async def test_read_list_write_cycle(tmp_path):
    h = Harness(tmp_path)
    h.model.script = [
        tool_call("list_files", {}, "c1"),
        tool_call("read_file", {"path": "2tobetested.txt"}, "c2"),
        tool_call("write_file", {"path": "por_ip/1.2.3.4.txt", "content": "http://a.lab\n"}, "c3"),
        tool_call(
            "write_file",
            {"path": "por_ip/1.2.3.4.txt", "content": "http://b.lab\n", "append": True},
            "c4",
        ),
        tool_call("finish", {"summary": "separado"}, "c5"),
    ]
    async with h.runtime() as rt:
        project, ws = await seed_ws(rt, tmp_path)
        task = await svc.create_task(
            rt, project.id, prompt="separe os hosts", mode="autonomous", wait=True
        )
        actions = {a.tool: a for a in await svc.list_actions(rt, task.id)}
        assert "2tobetested.txt" in actions["list_files"].result
        assert "a.lab" in actions["read_file"].result
        assert actions["write_file"].outcome == "executed"
        out = (ws / "por_ip" / "1.2.3.4.txt").read_text()
        assert out == "http://a.lab\nhttp://b.lab\n"  # criado e depois append


async def test_write_requires_approval_in_smart(tmp_path):
    h = Harness(tmp_path)
    h.model.script = [tool_call("write_file", {"path": "x.txt", "content": "oi"}, "c1")]
    async with h.runtime() as rt:
        project, _ = await seed_ws(rt, tmp_path)
        task = await svc.create_task(rt, project.id, prompt="x", mode="smart", wait=True)
        assert task.status == "waiting_approval"  # write é active


@pytest.mark.parametrize(
    ("args", "needle"),
    [
        ({"path": "../escape.txt", "content": "x"}, "BLOQUEADO"),
        ({"path": "/etc/cron.d/x", "content": "x"}, "BLOQUEADO"),
        ({"path": "run.sh", "content": "rm -rf /"}, "extensão não permitida"),
        ({"path": "a.py", "content": "import os"}, "extensão não permitida"),
    ],
)
async def test_write_is_confined(tmp_path, args, needle):
    h = Harness(tmp_path)
    h.model.script = [
        tool_call("write_file", args, "c1"),
        __import__("langchain_core.messages", fromlist=["AIMessage"]).AIMessage("fim"),
    ]
    async with h.runtime() as rt:
        project, ws = await seed_ws(rt, tmp_path)
        task = await svc.create_task(rt, project.id, prompt="x", mode="autonomous", wait=True)
        result = (await svc.list_actions(rt, task.id))[0].result
        assert needle in result
        assert not (ws.parent / "escape.txt").exists()


async def test_tools_inert_without_workspace(harness):
    harness.model.script = [
        tool_call("read_file", {"path": "x"}, "c1"),
        __import__("langchain_core.messages", fromlist=["AIMessage"]).AIMessage("fim"),
    ]
    async with harness.runtime() as rt:
        project = await svc.create_project(rt, name="lab", scope=LAB_SCOPE)
        task = await svc.create_task(rt, project.id, prompt="x", mode="autonomous", wait=True)
        assert "Nenhum workspace" in (await svc.list_actions(rt, task.id))[0].result


async def test_workspace_rejects_data_dir(tmp_path):
    h = Harness(tmp_path)
    async with h.runtime() as rt:
        project = await svc.create_project(rt, name="lab", scope=LAB_SCOPE)
        with pytest.raises(Conflict, match="reservada"):
            await svc.set_workspace_root(rt, project.id, str(h.settings.data_dir))


async def test_server_mode_disables_file_tools(tmp_path):
    h = Harness(tmp_path, mode="server", secret_key=Fernet.generate_key().decode())
    ws = tmp_path / "w"
    ws.mkdir()
    h.model.script = [
        tool_call("read_file", {"path": "x"}, "c1"),
        __import__("langchain_core.messages", fromlist=["AIMessage"]).AIMessage("fim"),
    ]
    async with h.runtime() as rt:
        project = await svc.create_project(rt, name="lab", scope=LAB_SCOPE)
        await svc.set_workspace_root(rt, project.id, str(ws))
        task = await svc.create_task(rt, project.id, prompt="x", mode="autonomous", wait=True)
        # file_tools desligadas no servidor → workspace_root None → inerte
        assert "Nenhum workspace" in (await svc.list_actions(rt, task.id))[0].result
