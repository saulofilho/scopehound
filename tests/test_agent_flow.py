"""Fluxos completos do agente (LLM roteirizado, alvo simulado)."""

import pytest
from conftest import LAB_SCOPE, Harness
from langchain_core.messages import AIMessage

from scopehound.agent.fake import tool_call
from scopehound.core import Conflict
from scopehound.core import service as svc

POST_LOGIN = {"method": "POST", "url": "http://app.lab/api/login", "body": "u=a&p=b"}
GET_USER = {"method": "GET", "url": "http://app.lab/api/users/2"}


async def new_project(rt, **kw):
    return await svc.create_project(rt, name=kw.pop("name", "lab"), scope=LAB_SCOPE, **kw)


async def test_acceptance_approval_survives_restart(harness: Harness):
    """Critério de pronto da Fase 1: pede aprovação para uma requisição ativa,
    pausa, é retomada depois de reiniciar o processo e registra um lead."""
    harness.model.script = [tool_call("send_request", POST_LOGIN, "c1", "Vou testar o login.")]
    async with harness.runtime() as rt:
        project = await new_project(rt)
        task = await svc.create_task(rt, project.id, prompt="teste o login", wait=True)
        assert task.status == "waiting_approval"
        [approval] = await svc.list_approvals(rt, task.id, "pending")
        assert approval.tool == "send_request" and approval.impact == "intrusive"
        assert harness.target.requests == []

    # "reinício": runtime novo, mesmo diretório de dados
    harness.model.script = [
        tool_call(
            "save_lead",
            {
                "title": "Login sem rate limit",
                "severity": "MEDIUM",
                "url": "http://app.lab/api/login",
                "evidence": "200 ok",
            },
            "c2",
        ),
        tool_call("finish", {"summary": "1 lead"}, "c3"),
    ]
    async with harness.runtime() as rt:
        await svc.resolve_approval(rt, approval.id, "once", wait=True)
        task = await svc.get_task(rt, task.id)
        assert task.status == "done"
        assert task.requests_used == 1 and task.steps_used == 3
        [sent] = harness.target.requests
        assert sent.method == "POST" and sent.headers["host"] == "app.lab"
        [lead] = await svc.list_leads(rt, project.id)
        assert lead.status == "lead" and lead.task_id == task.id
        outcomes = [(a.tool, a.outcome) for a in await svc.list_actions(rt, task.id)]
        assert outcomes == [
            ("send_request", "executed"),
            ("save_lead", "executed"),
            ("finish", "executed"),
        ]
        kinds = [a.kind for a in await svc.list_audit(rt, project.id)]
        assert "egress.sent" in kinds and "approval.resolved" in kinds
        approvals = await svc.list_approvals(rt, task.id)
        assert approvals[0].status == "approved" and approvals[0].response == "once"


async def test_smart_get_runs_without_approval(harness):
    harness.model.script = [tool_call("send_request", GET_USER, "c1"), AIMessage("feito")]
    async with harness.runtime() as rt:
        project = await new_project(rt)
        task = await svc.create_task(rt, project.id, prompt="x", wait=True)
        assert task.status == "idle"
        assert len(harness.target.requests) == 1
        tool_msg = harness.model.calls[-1][-1]
        assert "nao_confiaveis" in tool_msg.content and "outro@lab" in tool_msg.content


async def test_redirect_rejects_and_passes_instruction(harness):
    harness.model.script = [tool_call("send_request", POST_LOGIN, "c1"), AIMessage("ok")]
    async with harness.runtime() as rt:
        project = await new_project(rt)
        task = await svc.create_task(rt, project.id, prompt="x", wait=True)
        [approval] = await svc.list_approvals(rt, task.id, "pending")
        await svc.resolve_approval(rt, approval.id, "redirect", "teste só GET", wait=True)
        assert harness.target.requests == []
        last = harness.model.calls[-1][-1]
        assert "REJEITADO" in last.content and "teste só GET" in last.content
        [action] = await svc.list_actions(rt, task.id)
        assert action.outcome == "rejected"


async def test_session_grant_skips_second_question(harness):
    harness.model.script = [
        tool_call("send_request", POST_LOGIN, "c1"),
        tool_call("send_request", POST_LOGIN, "c2"),
        AIMessage("fim"),
    ]
    async with harness.runtime() as rt:
        project = await new_project(rt)
        task = await svc.create_task(rt, project.id, prompt="x", wait=True)
        [approval] = await svc.list_approvals(rt, task.id, "pending")
        await svc.resolve_approval(rt, approval.id, "session", wait=True)
        assert (await svc.get_task(rt, task.id)).status == "idle"
        assert len(harness.target.requests) == 2
        assert len(await svc.list_approvals(rt, task.id)) == 1


async def test_manual_always_sets_tool_to_act(harness):
    harness.model.script = [
        tool_call("send_request", GET_USER, "c1"),
        tool_call("send_request", GET_USER, "c2"),
        AIMessage("fim"),
    ]
    async with harness.runtime() as rt:
        project = await new_project(rt)
        task = await svc.create_task(rt, project.id, prompt="x", mode="manual", wait=True)
        [approval] = await svc.list_approvals(rt, task.id, "pending")
        with pytest.raises(Conflict):
            await svc.resolve_approval(rt, approval.id, "session")
        await svc.resolve_approval(rt, approval.id, "always", wait=True)
        settings = await svc.tool_settings(rt, project.id)
        assert settings["send_request"]["manual"] == "act"
        assert len(harness.target.requests) == 2
        assert len(await svc.list_approvals(rt, task.id)) == 1


async def test_autonomous_and_disabled_tool(harness):
    harness.model.script = [
        tool_call("send_request", POST_LOGIN, "c1"),
        tool_call(
            "save_lead", {"title": "t", "severity": "LOW", "url": "u", "evidence": "e"}, "c2"
        ),
        AIMessage("fim"),
    ]
    async with harness.runtime() as rt:
        project = await new_project(rt)
        await svc.set_tool_setting(rt, project.id, "save_lead", enabled=False)
        task = await svc.create_task(rt, project.id, prompt="x", mode="autonomous", wait=True)
        assert len(harness.target.requests) == 1
        outcomes = [a.outcome for a in await svc.list_actions(rt, task.id)]
        assert outcomes == ["executed", "denied"]
        assert await svc.list_leads(rt, project.id) == []


async def test_out_of_scope_request_is_blocked_and_audited(harness):
    harness.model.script = [
        tool_call("send_request", {"url": "http://169.254.169.254/latest"}, "c1"),
        tool_call("send_request", {"url": "http://app.lab/logout"}, "c2"),
        AIMessage("fim"),
    ]
    async with harness.runtime() as rt:
        project = await new_project(rt)
        task = await svc.create_task(rt, project.id, prompt="x", wait=True)
        assert harness.target.requests == []
        outcomes = [a.outcome for a in await svc.list_actions(rt, task.id)]
        assert outcomes == ["blocked", "blocked"]
        kinds = [a.kind for a in await svc.list_audit(rt, project.id)]
        assert kinds.count("egress.denied") == 2


async def test_verify_finding_confirms_lead(harness):
    harness.model.script = [
        tool_call(
            "verify_finding",
            {
                **GET_USER,
                "title": "IDOR em /api/users",
                "severity": "HIGH",
                "expected_status": 200,
                "expected_substring": "outro@lab",
            },
            "c1",
        ),
        tool_call(
            "verify_finding",
            {**GET_USER, "title": "falso", "severity": "LOW", "expected_substring": "admin"},
            "c2",
        ),
        AIMessage("fim"),
    ]
    async with harness.runtime() as rt:
        project = await new_project(rt)
        await svc.create_task(rt, project.id, prompt="x", wait=True)
        [lead] = await svc.list_leads(rt, project.id)
        assert lead.status == "confirmed" and lead.title == "IDOR em /api/users"


async def test_kill_switch_stops_task(harness):
    harness.model.script = [tool_call("send_request", GET_USER, "c1")]
    async with harness.runtime() as rt:
        project = await new_project(rt)
        await svc.kill_project(rt, project.id, "incidente")
        task = await svc.create_task(rt, project.id, prompt="x", wait=True)
        assert task.status == "stopped"
        assert harness.target.requests == []
        await svc.revive_project(rt, project.id)
        assert not rt.kill_switch(await rt.get_project(project.id)).tripped


async def test_step_budget(tmp_path):
    h = Harness(tmp_path, task_max_steps=1)
    h.model.script = [tool_call("send_request", GET_USER, "c1"), AIMessage("nunca chega")]
    async with h.runtime() as rt:
        project = await new_project(rt)
        task = await svc.create_task(rt, project.id, prompt="x", wait=True)
        assert task.status == "stopped" and task.steps_used == 1
        messages = await svc.get_messages(rt, task.id)
        assert "orçamento de passos" in messages[-1]["content"]


async def test_conversation_continues(harness):
    harness.model.script = [AIMessage("oi"), AIMessage("de novo")]
    async with harness.runtime() as rt:
        project = await new_project(rt)
        task = await svc.create_task(rt, project.id, prompt="olá", wait=True)
        await svc.send_message(rt, task.id, "continue", wait=True)
        roles = [m["role"] for m in await svc.get_messages(rt, task.id)]
        assert roles == ["human", "ai", "human", "ai"]


async def test_cannot_message_while_waiting_approval(harness):
    harness.model.script = [tool_call("send_request", POST_LOGIN, "c1")]
    async with harness.runtime() as rt:
        project = await new_project(rt)
        task = await svc.create_task(rt, project.id, prompt="x", wait=True)
        with pytest.raises(Conflict):
            await svc.send_message(rt, task.id, "e aí?")


async def test_local_only_requires_local_llm(harness):
    async with harness.runtime() as rt:
        project = await new_project(rt, llm_data_policy="local_only")
        await svc.set_llm_config(
            rt,
            project.id,
            provider="openai_compat",
            base_url="https://api.groq.com/openai/v1",
            model="m",
        )
        with pytest.raises(Conflict, match="local"):
            await svc.create_task(rt, project.id, prompt="x")
        await svc.set_llm_config(rt, project.id, base_url="http://localhost:11434/v1")
        assert rt.llm_config(await rt.get_project(project.id)).is_local


async def test_user_api_key_is_encrypted(harness):
    from scopehound.core.serialize import project_dict

    async with harness.runtime() as rt:
        project = await new_project(rt)
        project = await svc.set_llm_config(rt, project.id, api_key="minha-chave-secreta-123")
        assert "minha-chave" not in project.llm_api_key_enc
        assert rt.llm_config(project).api_key == "minha-chave-secreta-123"
        public = project_dict(project)
        assert "llm_api_key_enc" not in public and "secreta" not in str(public)
        project = await svc.set_llm_config(rt, project.id, clear_api_key=True)
        assert rt.llm_config(project).api_key is None


async def test_invalid_scope_rejected(harness):
    async with harness.runtime() as rt:
        with pytest.raises(Conflict):
            await svc.create_project(rt, name="x", scope={"allowed_hosts": ["*"]})
