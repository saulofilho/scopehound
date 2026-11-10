"""Meta-ferramentas: escolher uma skill e criar subagentes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .registry import ToolContext


class UseSkillArgs(BaseModel):
    name: str = Field(description="Nome de uma skill do catálogo")


class SpawnSubagentArgs(BaseModel):
    title: str = Field(description="Título curto da subtarefa")
    prompt: str = Field(description="Objetivo da subtarefa, autossuficiente")
    skill: str = Field(default="", description="Skill a usar na subtarefa (opcional)")
    max_steps: int = Field(default=10, ge=1, le=50)
    max_requests: int = Field(default=40, ge=1, le=500)


async def use_skill(ctx: ToolContext, a: UseSkillArgs) -> str:
    skill = ctx.library.get(a.name)
    if skill is None:
        names = ", ".join(s["name"] for s in ctx.library.catalog())
        return f"Skill {a.name!r} não existe. Disponíveis: {names}"
    tools = ", ".join(sorted(skill.available_tools()))
    return f"Skill ativa: {skill.name}. Ferramentas disponíveis agora: {tools}.\n\n{skill.body}"


async def spawn_subagent(ctx: ToolContext, a: SpawnSubagentArgs) -> str:
    if ctx.spawn is None:
        return "subagentes não disponíveis neste contexto."
    return await ctx.spawn(
        title=a.title,
        prompt=a.prompt,
        skill=a.skill or None,
        max_steps=a.max_steps,
        max_requests=a.max_requests,
    )
