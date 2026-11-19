"""Fases do minijogo: válidas, resolvíveis no orçamento e iguais às da versão web."""

from collections import deque
from itertools import permutations
from pathlib import Path

from scopehound.game import ASK, EXIT, LEAD, OUT, START, TRAP, WALL, Game, load_levels

LEVELS = load_levels()
BLOCKED = {WALL, OUT, TRAP}


def _dist(grid, a):
    d = {a: 0}
    q = deque([a])
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy)
            if n not in d and grid[n[1]][n[0]] not in BLOCKED:
                d[n] = d[(x, y)] + 1
                q.append(n)
    return d


def _find(grid, chars):
    return [(x, y) for y, r in enumerate(grid) for x, c in enumerate(r) if c in chars]


def test_web_copy_matches():
    web = Path(__file__).parents[1] / "docs/game/levels.json"
    src = Path(__file__).parents[1] / "src/scopehound/game/levels.json"
    assert web.read_text("utf-8") == src.read_text("utf-8")


def test_levels_are_solvable_within_budget():
    for lv in LEVELS:
        grid = lv["map"]
        assert len({len(r) for r in grid}) == 1, lv["name"]
        assert len(_find(grid, ASK)) == len(lv["asks"]), lv["name"]
        (start,) = _find(grid, START)
        (exit_,) = _find(grid, EXIT)
        stops = _find(grid, LEAD + ASK)
        dists = {p: _dist(grid, p) for p in [start, *stops]}
        for p in [*stops, exit_]:
            assert p in dists[start], f"{lv['name']}: {p} inalcançável"
        # Leads e aprovações precisam ser visitados; caminho mínimo por força bruta.
        leads = _find(grid, LEAD)
        best = min(
            sum(dists[a][b] for a, b in zip((start, *order), (*order, exit_), strict=True))
            for order in permutations(leads)
        )
        assert best < lv["budget"], f"{lv['name']}: mínimo {best} >= orçamento {lv['budget']}"


def test_out_of_scope_strikes_and_approval_rules():
    g = Game(
        {
            "name": "t",
            "budget": 20,
            "map": ["######", "#S~A.#", "#.L.E#", "######"],
            "asks": [{"t": "x", "ok": False}],
        }
    )
    g.move(1, 0)
    assert g.strikes == 1 and g.pos == (1, 1)
    g.move(0, 1)
    g.move(1, 0)
    assert g.leads_left == 0 and g.score == 75
    g.move(1, 0)
    g.move(0, -1)
    assert g.state == "ask"
    g.answer(True)
    assert g.state == "lost"
