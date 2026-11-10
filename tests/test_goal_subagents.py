from conftest import LAB_SCOPE, Harness
from langchain_core.messages import AIMessage
from traffic_fixtures import juice_har

from scopehound.agent.fake import tool_call
from scopehound.core import service as svc


async def test_goal_loop_nudges_until_finish(harness: Harness):
    """Critério de pronto parcial: /goal persegue o objetivo por vários passos
    e encerra com finish."""
    # 1º passo: olha o site map (sem finish). O router deve insistir.
    # 2º passo: ainda sem finish. 3º: chama finish.
    harness.model.script = [
        tool_call("site_map", {}, "c1"),
        AIMessage("ainda analisando"),  # sem tool call → router insiste
        tool_call("search_traffic", {"param": "BasketId"}, "c2"),
        tool_call("finish", {"summary": "achei IDOR em /api/BasketItems"}, "c3"),
    ]
    async with harness.runtime() as rt:
        project = await svc.create_project(rt, name="lab", scope=LAB_SCOPE)
        await svc.import_traffic(rt, project.id, juice_har(), filename="j.har")
        task = await svc.create_task(
            rt, project.id, prompt="/goal encontrar um IDOR", mode="autonomous", wait=True
        )
        assert task.goal == "encontrar um IDOR"
        assert task.status == "done"
        tools_used = [a.tool for a in await svc.list_actions(rt, task.id)]
        assert tools_used == ["site_map", "search_traffic", "finish"]


async def test_goal_loop_stops_at_nudge_limit(harness):
    # o modelo nunca chama finish; o router insiste no máximo 3 vezes e encerra
    harness.model.script = [AIMessage("nada ainda")] * 10
    async with harness.runtime() as rt:
        project = await svc.create_project(rt, name="lab", scope=LAB_SCOPE)
        task = await svc.create_task(
            rt, project.id, prompt="/goal impossível", mode="autonomous", wait=True
        )
        assert task.status in ("done", "stopped")
        # 1 chamada inicial + 3 nudges = 4 chamadas ao modelo
        assert len(harness.model.calls) == 4


async def test_spawn_subagent_runs_and_charges_parent(harness):
    def parent_script(msgs):
        return tool_call(
            "spawn_subagent",
            {"title": "mapear produtos", "prompt": "liste produtos", "max_steps": 3},
            "c1",
        )

    # roteiro do pai e do filho compartilham o mesmo modelo roteirizado,
    # consumido em ordem: pai pede subagente; filho roda; pai conclui.
    harness.model.script = [
        parent_script,
        # filho:
        tool_call(
            "save_lead",
            {
                "title": "endpoint interessante",
                "severity": "LOW",
                "url": "http://app.lab/api/Products",
                "evidence": "e",
            },
            "s1",
        ),
        tool_call("finish", {"summary": "mapeado"}, "s2"),
        # volta ao pai:
        AIMessage("subtarefa concluída, encerro"),
    ]
    async with harness.runtime() as rt:
        project = await svc.create_project(rt, name="lab", scope=LAB_SCOPE)
        task = await svc.create_task(
            rt, project.id, prompt="investigue", mode="autonomous", wait=True
        )
        subtasks = await svc.list_subtasks(rt, task.id)
        assert len(subtasks) == 1
        child = subtasks[0]
        assert child.parent_id == task.id and child.status == "done"
        # consumo do filho foi cobrado do pai
        assert task.steps_used >= child.steps_used
        # o lead do filho aparece no projeto
        leads = await svc.list_leads(rt, project.id)
        assert len(leads) == 1 and leads[0].task_id == child.id
        # o resumo do subagente voltou ao pai
        parent_tool_msg = [m for m in harness.model.calls[-1] if m.type == "tool"][-1]
        assert "subagente 'mapear produtos' terminou" in parent_tool_msg.content


async def test_subagent_budget_divided(harness):
    # pai já gastou quase tudo; subagente não deve exceder o que resta
    h = Harness(harness.tmp_path, task_max_steps=4)
    h.model.script = [
        tool_call("spawn_subagent", {"title": "x", "prompt": "p", "max_steps": 10}, "c1"),
        AIMessage("loop"),
        AIMessage("loop"),
        AIMessage("loop"),  # filho sem finish
        AIMessage("pai encerra"),
    ]
    async with h.runtime() as rt:
        project = await svc.create_project(rt, name="lab", scope=LAB_SCOPE)
        task = await svc.create_task(rt, project.id, prompt="x", mode="autonomous", wait=True)
        child = (await svc.list_subtasks(rt, task.id))[0]
        # pai usou 1 passo antes de spawnar; filho limitado ao que restava (<=3)
        assert child.steps_used <= 3
