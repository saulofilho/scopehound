"""Carregador de skills (equivalente ao banco de skills do Burp AT).

Cada skill é um arquivo Markdown com frontmatter YAML. O agente vê só nome e
descrição; o corpo (a metodologia) é carregado quando a skill é escolhida.
Uma skill também restringe quais ferramentas ficam disponíveis enquanto está
ativa, o que reduz o espaço de ação e o risco.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..tools import TOOLS

BUILTIN_DIR = Path(__file__).parent / "builtin"
_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
# Ferramentas sempre disponíveis, mesmo com uma skill restringindo o conjunto.
ALWAYS_AVAILABLE = frozenset(
    {"save_lead", "verify_finding", "finish", "site_map", "search_traffic", "get_request"}
)


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    tools: tuple[str, ...] = ()
    source: str = "builtin"

    def available_tools(self) -> set[str]:
        if not self.tools:
            return set(TOOLS)
        return (set(self.tools) & set(TOOLS)) | ALWAYS_AVAILABLE


def parse_skill(text: str, *, source: str = "builtin") -> Skill:
    match = _FRONTMATTER.match(text)
    if not match:
        raise ValueError("skill sem frontmatter YAML (--- ... ---)")
    meta = yaml.safe_load(match.group(1)) or {}
    if "name" not in meta or "description" not in meta:
        raise ValueError("skill precisa de 'name' e 'description'")
    tools = tuple(meta.get("tools", []) or ())
    unknown = set(tools) - set(TOOLS)
    if unknown:
        raise ValueError(f"skill referencia ferramentas inexistentes: {sorted(unknown)}")
    return Skill(
        name=str(meta["name"]),
        description=str(meta["description"]),
        body=match.group(2).strip(),
        tools=tools,
        source=source,
    )


@dataclass
class SkillLibrary:
    skills: dict[str, Skill] = field(default_factory=dict)

    def add(self, skill: Skill) -> None:
        self.skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        return self.skills.get(name)

    def catalog(self) -> list[dict[str, str]]:
        return [
            {"name": s.name, "description": s.description}
            for s in sorted(self.skills.values(), key=lambda s: s.name)
        ]

    def __len__(self) -> int:
        return len(self.skills)


def load_skills(extra_dirs: tuple[Path, ...] = ()) -> SkillLibrary:
    """Carrega as skills embutidas e, por cima, as de diretórios do usuário."""
    library = SkillLibrary()
    for directory, source in [(BUILTIN_DIR, "builtin"), *[(d, "user") for d in extra_dirs]]:
        if not directory or not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            library.add(parse_skill(path.read_text(encoding="utf-8"), source=source))
    return library
