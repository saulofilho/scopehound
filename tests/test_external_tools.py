from conftest import LAB_SCOPE, Harness
from langchain_core.messages import AIMessage

from scopehound.agent.fake import tool_call
from scopehound.core import service as svc


async def run_tool_call(h, call, **settings):
    h.model.script = [call]
    async with h.runtime() as rt:
        project = await svc.create_project(rt, name="lab", scope=LAB_SCOPE)
        task = await svc.create_task(rt, project.id, prompt="x", mode="autonomous", wait=True)
        actions = await svc.list_actions(rt, task.id)
        return actions[0]


async def test_external_disabled_by_default(harness):
    action = await run_tool_call(harness, tool_call("nuclei", {"url": "http://app.lab/"}, "c1"))
    assert "DESABILITADO" in action.result


async def test_external_scope_checked(tmp_path):
    h = Harness(tmp_path, enable_external_tools=True, dry_run_external=True)
    action = await run_tool_call(h, tool_call("nuclei", {"url": "http://evil.com/"}, "c1"))
    assert "BLOQUEADO (escopo)" in action.result


async def test_nuclei_dry_run(tmp_path):
    h = Harness(tmp_path, enable_external_tools=True, dry_run_external=True)
    action = await run_tool_call(
        h, tool_call("nuclei", {"url": "http://app.lab/", "tags": "cve"}, "c1")
    )
    assert action.result.startswith("DRY_RUN:") and "-tags cve" in action.result


async def _run_sqlmap(tmp_path, extra_args):
    # sqlmap é always_ask: aprova antes de executar (dry-run)
    h = Harness(tmp_path, enable_external_tools=True, dry_run_external=True)
    h.model.script = [
        tool_call("sqlmap", {"url": "http://app.lab/x?id=1", "extra_args": extra_args}, "c1"),
        AIMessage("fim"),
    ]
    async with h.runtime() as rt:
        project = await svc.create_project(rt, name="lab", scope=LAB_SCOPE)
        task = await svc.create_task(rt, project.id, prompt="x", mode="manual", wait=True)
        [approval] = await svc.list_approvals(rt, task.id, "pending")
        await svc.resolve_approval(rt, approval.id, "once", wait=True)
        return (await svc.list_actions(rt, task.id))[0]


async def test_sqlmap_forces_low_risk_and_allowlist(tmp_path):
    ok = await _run_sqlmap(tmp_path, "--dbs")
    assert "--batch" in ok.result and "--risk=1" in ok.result and "--dbs" in ok.result


async def test_sqlmap_blocks_dangerous_flag(tmp_path):
    bad = await _run_sqlmap(tmp_path, "--os-shell")
    assert "BLOQUEADO (argumento)" in bad.result


async def test_sqlmap_always_asks(harness):
    # sqlmap é always_ask: mesmo em autonomous, pede aprovação
    harness.model.script = [tool_call("sqlmap", {"url": "http://app.lab/x?id=1"}, "c1")]
    async with harness.runtime() as rt:
        project = await svc.create_project(rt, name="lab", scope=LAB_SCOPE)
        task = await svc.create_task(rt, project.id, prompt="x", mode="autonomous", wait=True)
        assert task.status == "waiting_approval"


async def test_ffuf_adds_fuzz_marker(tmp_path):
    h = Harness(tmp_path, enable_external_tools=True, dry_run_external=True)
    action = await run_tool_call(
        h, tool_call("ffuf", {"url": "http://app.lab/api", "wordlist": "/w.txt"}, "c1")
    )
    assert "/api/FUZZ" in action.result
