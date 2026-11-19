"""Fora da Coleira: minijogo de terminal sobre escopo (``scopehound play``).

A lógica (``Game``) é independente da interface e espelha ``docs/game/game.js``.
As fases ficam em ``levels.json``, compartilhado com a versão web.
"""

from __future__ import annotations

import json
from importlib.resources import files

WALL, FLOOR, OUT, TRAP, LEAD, ASK, EXIT, START = "#", ".", "~", "X", "L", "A", "E", "S"
MAX_STRIKES = 3
FOG = 2


def load_levels() -> list[dict]:
    return json.loads(files(__package__).joinpath("levels.json").read_text("utf-8"))


class Game:
    def __init__(self, level: dict) -> None:
        self.level = level
        self.grid = [list(row) for row in level["map"]]
        for y, row in enumerate(self.grid):
            for x, c in enumerate(row):
                if c == START:
                    self.pos = (x, y)
                    row[x] = FLOOR
        self.budget: int = level["budget"]
        self.asks = list(level.get("asks", []))
        self.leads_left = sum(row.count(LEAD) for row in self.grid)
        self.score = 0
        self.strikes = 0
        self.seen: set[tuple[int, int]] = set()
        self.pending: dict | None = None
        self.state = "play"  # play | ask | won | lost
        self.message = level.get("intro", "")
        self._reveal()

    def _reveal(self) -> None:
        px, py = self.pos
        for y in range(py - FOG, py + FOG + 1):
            for x in range(px - FOG, px + FOG + 1):
                if 0 <= y < len(self.grid) and 0 <= x < len(self.grid[y]):
                    self.seen.add((x, y))

    def _lose(self, why: str) -> None:
        self.state = "lost"
        self.message = why

    def move(self, dx: int, dy: int) -> None:
        if self.state != "play":
            return
        nx, ny = self.pos[0] + dx, self.pos[1] + dy
        c = self.grid[ny][nx]
        if c == WALL:
            self.message = "Parede."
            return
        self.budget -= 1
        if c == OUT:
            self.strikes += 1
            self.score -= 25
            self.message = (
                "Bloqueado pelo guardrail: fora do escopo. "
                f"Advertência {self.strikes}/{MAX_STRIKES}."
            )
            if self.strikes >= MAX_STRIKES:
                self._lose("Autorização revogada: tentativas demais fora do escopo.")
        else:
            self.pos = (nx, ny)
            self._reveal()
            self.message = ""
            if c == TRAP:
                self._lose("Caminho excluído do escopo. Sessão derrubada.")
            elif c == LEAD:
                self.grid[ny][nx] = FLOOR
                self.leads_left -= 1
                self.score += 100
                self.message = f"Lead encontrado! +100. Faltam {self.leads_left}."
            elif c == ASK:
                self.grid[ny][nx] = FLOOR
                self.pending = self.asks.pop(0)
                self.state = "ask"
                self.message = f"O farejador pede aprovação: {self.pending['t']}"
            elif c == EXIT:
                if self.leads_left:
                    self.message = f"Ainda faltam {self.leads_left} lead(s) para o relatório."
                else:
                    self.state = "won"
                    self.score += self.budget * 5
                    self.message = f"Relatório entregue! Bônus de orçamento: +{self.budget * 5}."
        if self.state in ("play", "ask") and self.budget <= 0:
            self._lose("Orçamento esgotado.")

    def answer(self, approve: bool) -> None:
        if self.state != "ask" or self.pending is None:
            return
        ok = self.pending["ok"]
        self.pending = None
        self.state = "play"
        if approve and not ok:
            self._lose("Você aprovou uma ação fora do escopo. Auditoria reprovada.")
        elif approve == ok:
            self.score += 50
            self.message = "Decisão correta. +50." + (" Ação executada." if ok else " Ação negada.")
        else:
            self.message = "Ação legítima negada: oportunidade perdida."

    def cell(self, x: int, y: int) -> str:
        if (x, y) == self.pos:
            return "@"
        if (x, y) not in self.seen:
            return " "
        return self.grid[y][x]


# ---------------------------------------------------------------- interface curses

_GLYPH = {WALL: "█", OUT: "░", FLOOR: "·", " ": " "}
_KEYS = {
    "KEY_UP": (0, -1),
    "KEY_DOWN": (0, 1),
    "KEY_LEFT": (-1, 0),
    "KEY_RIGHT": (1, 0),
    "w": (0, -1),
    "s": (0, 1),
    "a": (-1, 0),
    "d": (1, 0),
    "k": (0, -1),
    "j": (0, 1),
    "h": (-1, 0),
    "l": (1, 0),
}


def _draw(scr, game: Game, idx: int, total_levels: int, total: int) -> None:
    scr.erase()
    lv = game.level
    scr.addstr(0, 0, f"SCOPEHOUND · FORA DA COLEIRA   fase {idx + 1}/{total_levels}: {lv['name']}")
    for y, row in enumerate(game.grid):
        line = "".join(_GLYPH.get(c, c) for c in (game.cell(x, y) for x in range(len(row))))
        scr.addstr(2 + y, 0, line)
    col = len(game.grid[0]) + 3
    info = [
        "scope.yaml",
        *[f"  {s}" for s in lv["scope"]],
        "",
        f"orçamento   {game.budget}",
        f"advertência {game.strikes}/{MAX_STRIKES}",
        f"leads       {game.leads_left}",
        f"pontos      {total + game.score}",
        "",
        "@ você  L lead  A aprovação",
        "E relatório  X excluído  ░ fora",
    ]
    for i, s in enumerate(info):
        scr.addstr(2 + i, col, s)
    y = 3 + max(len(game.grid), len(info))
    scr.addstr(y, 0, game.message[: max(10, scr.getmaxyx()[1] - 1)])
    hint = {
        "play": "setas/wasd mover · r reiniciar · q sair",
        "ask": "aprovar? [y] sim  [n] não",
        "won": "enter: próxima fase · q sair",
        "lost": "r: tentar de novo · q sair",
    }[game.state]
    scr.addstr(y + 2, 0, hint)
    scr.refresh()


def _loop(scr) -> int:
    import curses

    curses.curs_set(0)
    levels = load_levels()
    idx, total = 0, 0
    game = Game(levels[idx])
    while True:
        _draw(scr, game, idx, len(levels), total)
        key = scr.getkey()
        if key in ("q", "Q"):
            return total + game.score
        if game.state == "ask" and key in ("y", "n"):
            game.answer(key == "y")
        elif game.state == "won" and key in ("\n", " ", "KEY_ENTER"):
            total += game.score
            idx += 1
            if idx >= len(levels):
                return total
            game = Game(levels[idx])
        elif key == "r" and game.state != "won":
            game = Game(levels[idx])
        elif key in _KEYS:
            game.move(*_KEYS[key])


def play() -> None:
    import curses

    score = curses.wrapper(_loop)
    print(f"Pontuação final: {score}. Bom farejo, e nunca fora do escopo.")
