import httpx
from conftest import LAB_SCOPE

from scopehound.api import create_app
from scopehound.oob import OobRegistry, make_hit


def test_registry_isolates_by_project():
    reg = OobRegistry()
    t1 = reg.new_token("p1")
    assert reg.record(t1, make_hit("GET", "/x", "1.2.3.4", {}, ""))
    assert not reg.record("desconhecido", make_hit("GET", "/x", "1.2.3.4", {}, ""))
    assert len(reg.poll(t1, "p1")) == 1
    assert reg.poll(t1, "outro") is None  # projeto errado não enxerga


async def test_oob_endpoint_records_and_tool_polls(harness):
    from scopehound.agent.fake import tool_call
    from scopehound.core import service as svc

    async with harness.runtime() as rt:
        project = await svc.create_project(rt, name="lab", scope=LAB_SCOPE)
        token = rt.oob.new_token(project.id)
        app = create_app(rt, manage_runtime=False)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as client:
            # alvo faz o callback (sem autenticação, rota aberta)
            r = await client.get(f"/oob/{token}/leak?x=1")
            assert r.status_code == 200 and r.json() == {"ok": True}
        assert len(rt.oob.poll(token, project.id)) == 1

        # a ferramenta oob_poll vê o callback
        harness.model.script = [tool_call("oob_poll", {"token": token}, "c1")]
        task = await svc.create_task(rt, project.id, prompt="x", mode="autonomous", wait=True)
        result = (await svc.list_actions(rt, task.id))[0].result
        assert "1 callback" in result and "/leak" in result
