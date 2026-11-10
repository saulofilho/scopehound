from conftest import LAB_SCOPE

from scopehound.agent.fake import tool_call
from scopehound.core import service as svc
from scopehound.report import max_severity


async def test_run_ci_produces_leads_and_severity(harness):
    harness.model.script = [
        tool_call(
            "save_lead",
            {"title": "IDOR", "severity": "HIGH", "url": "http://app.lab/api/x", "evidence": "e"},
            "c1",
        ),
        tool_call("finish", {"summary": "1 lead"}, "c2"),
    ]
    async with harness.runtime() as rt:
        project = await svc.create_project(rt, name="lab", scope=LAB_SCOPE)
        task = await svc.run_ci(rt, project.id, goal="achar IDOR")
        assert task.goal == "achar IDOR" and task.status in ("done", "stopped")
        leads = await svc.list_leads(rt, project.id)
        assert max_severity(leads) == "HIGH"
