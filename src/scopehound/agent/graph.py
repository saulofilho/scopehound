"""Grafo do agente: agent → policy → tools → agent.

- `agent` chama o modelo (consome passo e tokens do orçamento);
- `policy` decide cada chamada de ferramenta; quando precisa de aprovação,
  pausa com `interrupt()`. O checkpoint mantém a pausa mesmo se o processo
  reiniciar. Este nó não tem efeitos colaterais fora do banco idempotente,
  porque é reexecutado na retomada;
- `tools` executa só o que foi permitido e registra cada ação.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.types import interrupt

from ..policy import decide, grant_key
from ..tools import get_tool, openai_tool_schemas, run_tool
from .prompts import system_prompt

if TYPE_CHECKING:
    from ..core.runtime import Runtime


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    decisions: dict[str, dict[str, Any]]
    session_grants: list[str]
    finished: bool
    stopped: bool


def _stop(reason: str) -> dict[str, Any]:
    return {"messages": [AIMessage(content=reason)], "finished": True, "stopped": True}


def build_graph(rt: Runtime) -> StateGraph:
    def task_id_of(config) -> str:
        return config["configurable"]["thread_id"]

    async def agent(state: AgentState, config) -> dict[str, Any]:
        task_id = task_id_of(config)
        task, project = await rt.load_task(task_id)
        if rt.kill_switch(project).tripped:
            return _stop(f"Parado: kill switch acionado ({rt.kill_switch(project).reason}).")
        s = rt.settings
        if task.steps_used >= s.task_max_steps:
            return _stop(f"Parado: orçamento de passos esgotado ({s.task_max_steps}).")
        if task.tokens_used >= s.task_max_tokens:
            return _stop(f"Parado: orçamento de tokens esgotado ({s.task_max_tokens}).")

        settings = project.tool_settings or {}
        tools = openai_tool_schemas(lambda name: settings.get(name, {}).get("enabled", True))
        model = rt.chat_model(project).bind_tools(tools)
        messages = [SystemMessage(system_prompt(project.scope, task.mode)), *state["messages"]]
        response = await model.ainvoke(messages)
        tokens = (response.usage_metadata or {}).get("total_tokens", 0)
        await rt.add_usage(task_id, steps=1, tokens=tokens)
        return {"messages": [response], "decisions": {}, "finished": False}

    async def policy(state: AgentState, config) -> dict[str, Any]:
        task_id = task_id_of(config)
        last = state["messages"][-1]
        grants = list(state.get("session_grants", []))
        decisions: dict[str, dict[str, Any]] = {}
        for call in last.tool_calls:
            task, project = await rt.load_task(task_id)
            tool = get_tool(call["name"])
            if tool is None:
                decisions[call["id"]] = {
                    "allowed": False,
                    "outcome": "denied",
                    "note": f"ferramenta desconhecida: {call['name']}",
                }
                continue
            decision = decide(
                tool.spec,
                call["args"],
                mode=task.mode,
                settings=(project.tool_settings or {}).get(tool.spec.name),
                session_grants=grants,
            )
            if decision.outcome == "allow":
                decisions[call["id"]] = {
                    "allowed": True,
                    "outcome": "auto",
                    "note": decision.reason,
                }
                continue
            if decision.outcome == "deny":
                decisions[call["id"]] = {
                    "allowed": False,
                    "outcome": "denied",
                    "note": f"NEGADO: {decision.reason}",
                }
                continue

            approval_id = await rt.ensure_approval(task_id, call, decision)
            answer = interrupt(
                {
                    "approval_id": approval_id,
                    "tool": call["name"],
                    "args": call["args"],
                    "impact": decision.impact,
                    "reason": decision.reason,
                }
            )
            response, note = answer["response"], answer.get("note") or ""
            if response in ("once", "session", "always"):
                if response == "session":
                    grants.append(grant_key(tool.spec.name, decision.impact))
                if response == "always":
                    await rt.set_tool_manual(project.id, tool.spec.name, "act")
                decisions[call["id"]] = {"allowed": True, "outcome": "approved", "note": response}
            else:
                text = "REJEITADO pelo analista."
                if response == "redirect" and note:
                    text += f" Instrução do analista: {note}"
                decisions[call["id"]] = {"allowed": False, "outcome": "rejected", "note": text}
        return {"decisions": decisions, "session_grants": grants}

    async def tools(state: AgentState, config) -> dict[str, Any]:
        task_id = task_id_of(config)
        last = state["messages"][-1]
        decisions = state.get("decisions", {})
        out: list[ToolMessage] = []
        finished = False
        for call in last.tool_calls:
            decision = decisions.get(
                call["id"],
                {"allowed": False, "outcome": "denied", "note": "sem decisão de política"},
            )
            if not decision["allowed"]:
                text, outcome = decision["note"], decision["outcome"]
            else:
                async with rt.tool_context(task_id) as ctx:
                    outcome, text = await run_tool(get_tool(call["name"]), ctx, call["args"])
                if call["name"] == "finish" and outcome == "executed":
                    finished = True
            await rt.record_action(task_id, call, outcome, text)
            out.append(ToolMessage(content=text, tool_call_id=call["id"], name=call["name"]))
        return {"messages": out, "finished": finished}

    def after_agent(state: AgentState) -> str:
        last = state["messages"][-1]
        if state.get("finished") or not getattr(last, "tool_calls", None):
            return END
        return "policy"

    def after_tools(state: AgentState) -> str:
        return END if state.get("finished") else "agent"

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent)
    graph.add_node("policy", policy)
    graph.add_node("tools", tools)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", after_agent, ["policy", END])
    graph.add_edge("policy", "tools")
    graph.add_conditional_edges("tools", after_tools, ["agent", END])
    return graph
