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

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.types import interrupt

from ..i18n import t
from ..policy import decide, grant_key
from ..tools import get_tool, openai_tool_schemas, run_tool
from .llm import explain_llm_error
from .prompts import system_prompt

if TYPE_CHECKING:
    from ..core.runtime import Runtime


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    decisions: dict[str, dict[str, Any]]
    session_grants: list[str]
    active_skill: str | None
    goal: str | None
    goal_nudges: int
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
            return _stop(
                t(
                    f"Parado: kill switch acionado ({rt.kill_switch(project).reason}).",
                    f"Stopped: kill switch tripped ({rt.kill_switch(project).reason}).",
                )
            )
        s = rt.settings
        step_cap, _req_cap = rt.task_caps.get(task_id, (s.task_max_steps, s.task_max_requests))
        step_cap = min(step_cap, s.task_max_steps)
        if task.steps_used >= step_cap:
            return _stop(
                t(
                    f"Parado: orçamento de passos esgotado ({step_cap}).",
                    f"Stopped: step budget exhausted ({step_cap}).",
                )
            )
        if task.tokens_used >= s.task_max_tokens:
            return _stop(
                t(
                    f"Parado: orçamento de tokens esgotado ({s.task_max_tokens}).",
                    f"Stopped: token budget exhausted ({s.task_max_tokens}).",
                )
            )

        settings = project.tool_settings or {}
        active_skill = state.get("active_skill")
        skill = rt.library.get(active_skill) if active_skill else None
        allowed = skill.available_tools() if skill else None

        def enabled(name: str) -> bool:
            if settings.get(name, {}).get("enabled", True) is False:
                return False
            return allowed is None or name in allowed

        tools = openai_tool_schemas(enabled)
        model = rt.chat_model(project).bind_tools(tools)
        prompt = system_prompt(
            project.scope,
            task.mode,
            rt.library.catalog(),
            active_skill=active_skill,
            goal=state.get("goal"),
        )
        messages = [SystemMessage(prompt), *state["messages"]]
        try:
            response = await model.ainvoke(messages)
        except Exception as exc:  # noqa: BLE001 - traduzido para mensagem acionável
            raise explain_llm_error(exc, rt.llm_config(project)) from exc
        tokens = (response.usage_metadata or {}).get("total_tokens", 0)
        await rt.add_usage(task_id, steps=1, tokens=tokens)
        return {"messages": [response], "decisions": {}, "finished": False}

    async def policy(state: AgentState, config) -> dict[str, Any]:
        task_id = task_id_of(config)
        last = state["messages"][-1]
        grants = list(state.get("session_grants", []))
        decisions: dict[str, dict[str, Any]] = {}
        active_skill = state.get("active_skill")
        skill = rt.library.get(active_skill) if active_skill else None
        for call in last.tool_calls:
            task, project = await rt.load_task(task_id)
            tool = get_tool(call["name"])
            if tool is None:
                decisions[call["id"]] = {
                    "allowed": False,
                    "outcome": "denied",
                    "note": t(
                        f"ferramenta desconhecida: {call['name']}",
                        f"unknown tool: {call['name']}",
                    ),
                }
                continue
            if skill is not None and call["name"] not in skill.available_tools():
                decisions[call["id"]] = {
                    "allowed": False,
                    "outcome": "denied",
                    "note": t(
                        f"ferramenta fora da skill ativa '{active_skill}'",
                        f"tool outside the active skill '{active_skill}'",
                    ),
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
                    "note": t(f"NEGADO: {decision.reason}", f"DENIED: {decision.reason}"),
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
                text = t("REJEITADO pelo analista.", "REJECTED by the analyst.")
                if response == "redirect" and note:
                    text += t(f" Instrução do analista: {note}", f" Analyst instruction: {note}")
                decisions[call["id"]] = {"allowed": False, "outcome": "rejected", "note": text}
        return {"decisions": decisions, "session_grants": grants}

    async def tools(state: AgentState, config) -> dict[str, Any]:
        task_id = task_id_of(config)
        last = state["messages"][-1]
        decisions = state.get("decisions", {})
        out: list[ToolMessage] = []
        finished = False
        updates: dict[str, Any] = {}
        for call in last.tool_calls:
            decision = decisions.get(
                call["id"],
                {
                    "allowed": False,
                    "outcome": "denied",
                    "note": t("sem decisão de política", "no policy decision"),
                },
            )
            if not decision["allowed"]:
                text, outcome = decision["note"], decision["outcome"]
            else:
                async with rt.tool_context(task_id) as ctx:
                    outcome, text = await run_tool(get_tool(call["name"]), ctx, call["args"])
                if call["name"] == "finish" and outcome == "executed":
                    finished = True
                if call["name"] == "use_skill" and outcome == "executed":
                    updates["active_skill"] = call["args"].get("name")
            await rt.record_action(task_id, call, outcome, text)
            out.append(ToolMessage(content=text, tool_call_id=call["id"], name=call["name"]))
        return {"messages": out, "finished": finished, **updates}

    MAX_GOAL_NUDGES = 3

    async def agent_router(state: AgentState, config) -> dict[str, Any]:
        """Entre agent e o fim: implementa o loop do /goal."""
        last = state["messages"][-1]
        if state.get("finished") or getattr(last, "tool_calls", None):
            return {}
        goal = state.get("goal")
        nudges = state.get("goal_nudges", 0)
        if goal and nudges < MAX_GOAL_NUDGES:
            return {
                "messages": [
                    HumanMessage(
                        t(
                            f"Objetivo ainda em aberto: {goal}\n"
                            "Continue perseguindo-o com as ferramentas, ou chame finish "
                            "se já o cumpriu ou se não há mais o que fazer.",
                            f"Goal still open: {goal}\n"
                            "Keep pursuing it with the tools, or call finish if you have "
                            "met it or there is nothing left to do.",
                        )
                    )
                ],
                "goal_nudges": nudges + 1,
            }
        return {"finished": True}

    def after_tools(state: AgentState) -> str:
        return END if state.get("finished") else "agent"

    def route_after_agent(state: AgentState) -> str:
        last = state["messages"][-1]
        if state.get("finished"):
            return END
        if getattr(last, "tool_calls", None):
            return "policy"
        # Sem tool calls: numa tarefa com /goal, o router decide se insiste ou
        # encerra; numa conversa normal, a vez volta ao analista (status idle).
        if state.get("goal"):
            return "router"
        return END

    def route_after_router(state: AgentState) -> str:
        return "agent" if not state.get("finished") else END

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent)
    graph.add_node("router", agent_router)
    graph.add_node("policy", policy)
    graph.add_node("tools", tools)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_after_agent, ["policy", "router", END])
    graph.add_conditional_edges("router", route_after_router, ["agent", END])
    graph.add_edge("policy", "tools")
    graph.add_conditional_edges("tools", after_tools, ["agent", END])
    return graph
