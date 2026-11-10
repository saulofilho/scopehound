from conftest import LAB_SCOPE, Harness
from langchain_core.messages import AIMessage

from scopehound.agent.fake import tool_call
from scopehound.core import service as svc

GET2 = {"method": "GET", "url": "http://app.lab/api/users/2"}


async def seed(rt, **kw):
    project = await svc.create_project(rt, name="lab", scope=LAB_SCOPE, **kw)
    return project


async def test_use_skill_restricts_tools_and_loads_body(harness: Harness):
    captured = {}

    def check_tools(msgs):
        # depois de use_skill, o modelo é chamado só com as ferramentas da skill
        captured["system"] = msgs[0].content
        return AIMessage("ok")

    harness.model.script = [
        tool_call("use_skill", {"name": "idor"}, "c1"),
        check_tools,
    ]
    async with harness.runtime() as rt:
        project = await seed(rt)
        task = await svc.create_task(rt, project.id, prompt="teste idor", wait=True)
        actions = await svc.list_actions(rt, task.id)
        assert actions[0].tool == "use_skill" and actions[0].outcome == "executed"
        assert "Broken Object Level" in actions[0].result
        assert "Skill ativa:" in actions[0].result


async def test_use_skill_blocks_tool_outside_skill(harness):
    # idor não inclui content_discovery; o modelo que tentar usá-la recebe erro
    harness.model.script = [
        tool_call("use_skill", {"name": "idor"}, "c1"),
        tool_call("content_discovery", {"base_url": "http://app.lab/"}, "c2"),
        AIMessage("fim"),
    ]
    async with harness.runtime() as rt:
        project = await seed(rt)
        # autonomous: se a ferramenta estivesse disponível, rodaria sem pedir
        task = await svc.create_task(rt, project.id, prompt="x", mode="autonomous", wait=True)
        outcomes = {a.tool: a.outcome for a in await svc.list_actions(rt, task.id)}
        assert outcomes["use_skill"] == "executed"
        assert outcomes["content_discovery"] == "denied"
        assert harness.target.requests == []


async def test_replay_as_uses_session(harness):
    harness.model.script = [
        tool_call("send_request", GET2, "c1"),
        lambda msgs: tool_call(
            "replay_as",
            {"id": msgs[-1].content.split("[troca ")[1][:12], "session": "userB"},
            "c2",
        ),
        AIMessage("comparado"),
    ]
    async with harness.runtime() as rt:
        project = await seed(rt)
        await svc.set_session(rt, project.id, "userB", {"Cookie": "token=bbb"})
        task = await svc.create_task(rt, project.id, prompt="x", mode="autonomous", wait=True)
        # a requisição de replay levou o cookie da sessão userB
        replay = harness.target.requests[-1]
        assert replay.headers.get("cookie") == "token=bbb"
        outcomes = [a.outcome for a in await svc.list_actions(rt, task.id)]
        assert outcomes == ["executed", "executed"]


async def test_replay_as_missing_session(harness):
    harness.model.script = [
        tool_call("send_request", GET2, "c1"),
        lambda msgs: tool_call(
            "replay_as",
            {"id": msgs[-1].content.split("[troca ")[1][:12], "session": "fantasma"},
            "c2",
        ),
        AIMessage("fim"),
    ]
    async with harness.runtime() as rt:
        project = await seed(rt)
        await svc.create_task(rt, project.id, prompt="x", mode="autonomous", wait=True)
        last_tool = [m for m in harness.model.calls[-1] if m.type == "tool"][-1]
        assert "não existe" in last_tool.content


async def test_content_discovery_reports_found(harness):
    def target(request):
        import httpx

        if request.url.path in ("/admin", "/api"):
            return httpx.Response(200, text="painel")
        return httpx.Response(404)

    harness.target.handler = target
    harness.model.script = [
        tool_call(
            "content_discovery",
            {"base_url": "http://app.lab/", "words": ["admin", "api", "nope"]},
            "c1",
        ),
        AIMessage("fim"),
    ]
    async with harness.runtime() as rt:
        project = await seed(rt)
        task = await svc.create_task(rt, project.id, prompt="x", mode="autonomous", wait=True)
        result = [a for a in await svc.list_actions(rt, task.id)][0].result
        assert "/admin" in result and "/api" in result
        assert "3 caminhos testados" in result


async def test_race_request_flags_divergence(harness):
    state = {"n": 0}

    def target(request):
        import httpx

        state["n"] += 1
        # só a primeira "vence"
        return httpx.Response(200 if state["n"] == 1 else 409, text="x" * state["n"])

    harness.target.handler = target
    harness.model.script = [
        tool_call("race_request", {"url": "http://app.lab/api/redeem", "count": 5}, "c1"),
        AIMessage("fim"),
    ]
    async with harness.runtime() as rt:
        project = await seed(rt)
        task = await svc.create_task(rt, project.id, prompt="x", mode="autonomous", wait=True)
        result = (await svc.list_actions(rt, task.id))[0].result
        assert "condição de corrida" in result and "5 de 5" in result


async def test_read_source_within_root(tmp_path):
    h = Harness(tmp_path)
    src = tmp_path / "code"
    src.mkdir()
    (src / "app.py").write_text("SECRET_ROUTE = '/internal'")
    h.model.script = [
        tool_call("read_source", {"path": "app.py"}, "c1"),
        tool_call("read_source", {"path": "../../etc/passwd"}, "c2"),
        AIMessage("fim"),
    ]
    async with h.runtime() as rt:
        project = await svc.create_project(rt, name="lab", scope=LAB_SCOPE)
        await svc.set_source_root(rt, project.id, str(src))
        task = await svc.create_task(rt, project.id, prompt="x", mode="autonomous", wait=True)
        results = [a.result for a in await svc.list_actions(rt, task.id)]
        assert "SECRET_ROUTE" in results[0]
        assert "fora da raiz" in results[1]
