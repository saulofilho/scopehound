"""LLM roteirizado para testes e demonstrações (não gasta tokens)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

Step = AIMessage | Callable[[Sequence[BaseMessage]], AIMessage]


class ScriptedChatModel(BaseChatModel):
    script: list[Any] = Field(default_factory=list)
    calls: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedChatModel:  # type: ignore[override]
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls.append(list(messages))
        if not self.script:
            message = AIMessage(content="(roteiro encerrado)")
        else:
            step = self.script.pop(0)
            message = step(messages) if callable(step) else step
        if message.usage_metadata is None:
            message.usage_metadata = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        return ChatResult(generations=[ChatGeneration(message=message)])


def tool_call(name: str, args: dict[str, Any], call_id: str, content: str = "") -> AIMessage:
    return AIMessage(
        content=content,
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )
