import pytest
from conftest import LAB_SCOPE, Harness

from scopehound.agent.fake import tool_call
from scopehound.agent.prompts import system_prompt
from scopehound.core import NotFound
from scopehound.core import service as svc
from scopehound.guardrails import Scope, check_url
from scopehound.i18n import current_language, set_language, t


@pytest.fixture(autouse=True)
def _reset_language():
    set_language("pt")
    yield
    set_language("pt")


def test_t_picks_language():
    set_language("pt")
    assert t("oi", "hi") == "oi" and current_language() == "pt"
    set_language("en")
    assert t("oi", "hi") == "hi"
    set_language("xx")  # inválido cai em pt
    assert current_language() == "pt"


def test_system_prompt_switches():
    scope = {"allowed_hosts": ["app.lab"]}
    set_language("pt")
    assert "Responda em português" in system_prompt(scope, "smart")
    set_language("en")
    en = system_prompt(scope, "smart")
    assert "Respond in English" in en and "human-led pentest agent" in en


def test_scope_violation_message_translates():
    scope = Scope(allowed_hosts=["app.lab"], authorized_by="x")
    set_language("en")
    with pytest.raises(Exception) as exc:
        check_url(scope, "http://evil.com/")
    assert "outside the authorized scope" in str(exc.value)


async def test_runtime_applies_language_and_agent_output(tmp_path):
    h = Harness(tmp_path, language="en")
    h.model.script = [
        tool_call("send_request", {"url": "http://evil.com/"}, "c1"),
        __import__("langchain_core.messages", fromlist=["AIMessage"]).AIMessage("done"),
    ]
    async with h.runtime() as rt:
        assert current_language() == "en"
        project = await svc.create_project(rt, name="lab", scope=LAB_SCOPE)
        # mensagem de erro do projeto em inglês
        with pytest.raises(NotFound, match="not found"):
            await svc.find_project(rt, "nope")
        task = await svc.create_task(rt, project.id, prompt="x", mode="autonomous", wait=True)
        # ferramenta bloqueada: resultado em inglês
        action = (await svc.list_actions(rt, task.id))[0]
        assert "BLOCKED" in action.result and "scope" in action.result
        # prompt do sistema em inglês foi enviado ao modelo
        system = h.model.calls[-1][0].content
        assert "Respond in English" in system
