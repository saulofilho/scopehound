from conftest import LAB_SCOPE, Harness

from scopehound.agent.fake import tool_call
from scopehound.core import service as svc


async def test_redaction_applies_when_llm_not_local(tmp_path):
    def target(request):
        import httpx

        return httpx.Response(
            200,
            headers={"Set-Cookie": "session=supersecretvalue", "Content-Type": "text/plain"},
            text="usuário admin@empresa.com cartão 4111 1111 1111 1111",
        )

    h = Harness(
        tmp_path,
        llm_provider="openai_compat",
        llm_base_url="https://api.groq.com/openai/v1",
        redact="auto",
    )
    h.target.handler = target
    h.model.script = [tool_call("send_request", {"url": "http://app.lab/x"}, "c1")]
    async with h.runtime() as rt:
        project = await svc.create_project(rt, name="lab", scope=LAB_SCOPE)
        await svc.create_task(rt, project.id, prompt="x", mode="autonomous", wait=True)
        tool_msg = [m for m in h.model.calls[-1] if m.type == "tool"][-1].content
        assert "admin@empresa.com" not in tool_msg and "«email»" in tool_msg
        assert "4111 1111 1111 1111" not in tool_msg
        assert "supersecretvalue" not in tool_msg  # header mascarado
        # o tráfego guardado mantém o original (não é o que o modelo vê)
        rows = await svc.search_traffic(rt, project.id, source="agent")
        assert "admin@empresa.com" in rows[0].response_body


async def test_no_redaction_for_local_llm(harness):
    # provider fake conta como local → sem mascaramento
    def target(request):
        import httpx

        return httpx.Response(200, text="admin@empresa.com")

    harness.target.handler = target
    harness.model.script = [tool_call("send_request", {"url": "http://app.lab/x"}, "c1")]
    async with harness.runtime() as rt:
        project = await svc.create_project(rt, name="lab", scope=LAB_SCOPE)
        await svc.create_task(rt, project.id, prompt="x", mode="autonomous", wait=True)
        tool_msg = [m for m in harness.model.calls[-1] if m.type == "tool"][-1].content
        assert "admin@empresa.com" in tool_msg
