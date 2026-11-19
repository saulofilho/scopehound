// Fora da Coleira — versão web. Espelha src/scopehound/game/__init__.py (classe Game).
const MAX_STRIKES = 3, FOG = 2;

class Game {
  constructor(level) {
    this.level = level;
    this.grid = level.map.map(r => [...r]);
    this.grid.forEach((row, y) => row.forEach((c, x) => {
      if (c === "S") { this.pos = [x, y]; row[x] = "."; }
    }));
    this.budget = level.budget;
    this.asks = [...(level.asks || [])];
    this.leadsLeft = this.grid.flat().filter(c => c === "L").length;
    this.score = 0; this.strikes = 0;
    this.seen = new Set(); this.pending = null;
    this.state = "play"; // play | ask | won | lost
    this.message = level.intro || "";
    this.reveal();
  }
  reveal() {
    const [px, py] = this.pos;
    for (let y = py - FOG; y <= py + FOG; y++)
      for (let x = px - FOG; x <= px + FOG; x++)
        if (this.grid[y]?.[x] !== undefined) this.seen.add(x + "," + y);
  }
  lose(why) { this.state = "lost"; this.message = why; }
  move(dx, dy) {
    if (this.state !== "play") return;
    const nx = this.pos[0] + dx, ny = this.pos[1] + dy, c = this.grid[ny][nx];
    if (c === "#") { this.message = "Parede."; return; }
    this.budget--;
    if (c === "~") {
      this.strikes++; this.score -= 25;
      this.message = `Bloqueado pelo guardrail: fora do escopo. Advertência ${this.strikes}/${MAX_STRIKES}.`;
      if (this.strikes >= MAX_STRIKES) this.lose("Autorização revogada: tentativas demais fora do escopo.");
    } else {
      this.pos = [nx, ny]; this.reveal(); this.message = "";
      if (c === "X") this.lose("Caminho excluído do escopo. Sessão derrubada.");
      else if (c === "L") {
        this.grid[ny][nx] = "."; this.leadsLeft--; this.score += 100;
        this.message = `Lead encontrado! +100. Faltam ${this.leadsLeft}.`;
      } else if (c === "A") {
        this.grid[ny][nx] = "."; this.pending = this.asks.shift(); this.state = "ask";
        this.message = `O farejador pede aprovação: ${this.pending.t}`;
      } else if (c === "E") {
        if (this.leadsLeft) this.message = `Ainda faltam ${this.leadsLeft} lead(s) para o relatório.`;
        else {
          this.state = "won"; this.score += this.budget * 5;
          this.message = `Relatório entregue! Bônus de orçamento: +${this.budget * 5}.`;
        }
      }
    }
    if ((this.state === "play" || this.state === "ask") && this.budget <= 0) this.lose("Orçamento esgotado.");
  }
  answer(approve) {
    if (this.state !== "ask" || !this.pending) return;
    const ok = this.pending.ok; this.pending = null; this.state = "play";
    if (approve && !ok) this.lose("Você aprovou uma ação fora do escopo. Auditoria reprovada.");
    else if (approve === ok) { this.score += 50; this.message = "Decisão correta. +50." + (ok ? " Ação executada." : " Ação negada."); }
    else this.message = "Ação legítima negada: oportunidade perdida.";
  }
  cell(x, y) {
    if (x === this.pos[0] && y === this.pos[1]) return "@";
    return this.seen.has(x + "," + y) ? this.grid[y][x] : " ";
  }
}

// ------------------------------------------------------------------ interface
const $ = id => document.getElementById(id);
const CLS = { "#": "wall", "~": "out", ".": "floor", " ": "fog", "@": "dog", L: "lead", A: "ask", E: "exit", X: "trap" };
const GLYPH = { "#": "", "~": "", ".": "·", " ": "", "@": "@", L: "L", A: "A", E: "E", X: "X" };
let levels = [], idx = 0, total = 0, game;

function start(i) { idx = i; game = new Game(levels[i]); render(); }

function render() {
  const g = game, lv = g.level;
  $("level").textContent = `fase ${idx + 1}/${levels.length} · ${lv.name}`;
  const map = $("map");
  map.style.gridTemplateColumns = `repeat(${g.grid[0].length}, 1fr)`;
  map.innerHTML = g.grid.map((row, y) => row.map((_, x) => {
    const c = g.cell(x, y);
    return `<span class="t ${CLS[c] || "floor"}">${GLYPH[c] ?? c}</span>`;
  }).join("")).join("");
  $("scope").textContent = "scope.yaml\n" + lv.scope.map(s => "  " + s).join("\n");
  $("budget").textContent = g.budget;
  $("strikes").textContent = `${g.strikes}/${MAX_STRIKES}`;
  $("leads").textContent = g.leadsLeft;
  $("score").textContent = total + g.score;
  $("msg").textContent = g.message;
  $("ask").hidden = g.state !== "ask";
  $("next").hidden = g.state !== "won";
  $("next").textContent = idx + 1 < levels.length ? "Próxima fase ▸" : `Fim! Pontuação: ${total + g.score} · jogar de novo`;
  $("retry").hidden = g.state !== "lost";
}

function next() {
  if (game.state !== "won") return;
  total += game.score;
  if (idx + 1 < levels.length) start(idx + 1);
  else { total = 0; start(0); }
}

const KEYS = { ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0], w: [0, -1], s: [0, 1], a: [-1, 0], d: [1, 0] };
document.addEventListener("keydown", e => {
  if (!game) return;
  const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
  if (game.state === "ask" && (k === "y" || k === "n")) game.answer(k === "y");
  else if (game.state === "won" && (k === "Enter" || k === " ")) return next(), e.preventDefault();
  else if (k === "r" && game.state !== "won") return start(idx);
  else if (KEYS[k]) { game.move(...KEYS[k]); e.preventDefault(); }
  else return;
  render();
});
document.querySelectorAll("[data-move]").forEach(b => b.addEventListener("click", () => {
  game.move(...b.dataset.move.split(",").map(Number)); render();
}));
$("yes").onclick = () => { game.answer(true); render(); };
$("no").onclick = () => { game.answer(false); render(); };
$("next").onclick = next;
$("retry").onclick = () => start(idx);

fetch("levels.json").then(r => r.json()).then(l => { levels = l; start(0); })
  .catch(() => { $("msg").textContent = "Não consegui carregar levels.json (abra via servidor HTTP)."; });
