"""Meta-ferramentas: escolher uma skill e criar subagentes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from ..i18n import t

if TYPE_CHECKING:
    from .registry import ToolContext


class UseSkillArgs(BaseModel):
    name: str = Field(description="Name of a skill from the catalog")


class SpawnSubagentArgs(BaseModel):
    title: str = Field(description="Short title of the subtask")
    prompt: str = Field(description="Self-contained goal of the subtask")
    skill: str = Field(default="", description="Skill to use in the subtask (optional)")
    max_steps: int = Field(default=10, ge=1, le=50)
    max_requests: int = Field(default=40, ge=1, le=500)


async def use_skill(ctx: ToolContext, a: UseSkillArgs) -> str:
    skill = ctx.library.get(a.name)
    if skill is None:
        names = ", ".join(s["name"] for s in ctx.library.catalog())
        return t(
            f"Skill {a.name!r} não existe. Disponíveis: {names}",
            f"Skill {a.name!r} does not exist. Available: {names}",
        )
    tools = ", ".join(sorted(skill.available_tools()))
    header = t(
        f"Skill ativa: {skill.name}. Ferramentas disponíveis agora: {tools}.",
        f"Active skill: {skill.name}. Tools available now: {tools}.",
    )
    return f"{header}\n\n{skill.body}"


async def spawn_subagent(ctx: ToolContext, a: SpawnSubagentArgs) -> str:
    if ctx.spawn is None:
        return t(
            "subagentes não disponíveis neste contexto.", "subagents unavailable in this context."
        )
    return await ctx.spawn(
        title=a.title,
        prompt=a.prompt,
        skill=a.skill or None,
        max_steps=a.max_steps,
        max_requests=a.max_requests,
    )
