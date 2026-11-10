import pytest

from scopehound.skills import load_skills
from scopehound.skills.loader import parse_skill
from scopehound.tools import TOOLS


def test_builtin_skills_load():
    lib = load_skills()
    assert {s["name"] for s in lib.catalog()} == {"content-discovery", "idor", "race-condition"}
    idor = lib.get("idor")
    assert "replay_as" in idor.available_tools()
    assert "content_discovery" not in idor.available_tools()  # fora do conjunto da skill
    assert "save_lead" in idor.available_tools()  # sempre disponível
    assert "Broken Object Level" in idor.body


def test_skill_without_tools_allows_all():
    skill = parse_skill("---\nname: x\ndescription: d\n---\ncorpo")
    assert skill.available_tools() == set(TOOLS)


@pytest.mark.parametrize(
    "text",
    [
        "sem frontmatter",
        "---\nname: x\n---\ncorpo",  # falta description
        "---\nname: x\ndescription: d\ntools: [inexistente]\n---\nc",
    ],
)
def test_invalid_skills_rejected(text):
    with pytest.raises(ValueError):
        parse_skill(text)


def test_user_skill_overrides_builtin(tmp_path):
    (tmp_path / "idor.md").write_text(
        "---\nname: idor\ndescription: versão do time\n---\nmeu método"
    )
    lib = load_skills((tmp_path,))
    assert lib.get("idor").description == "versão do time"
    assert lib.get("idor").source == "user"
    assert len(lib) == 3
