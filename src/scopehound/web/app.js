"use strict";
// Interface do scopehound: app de página única, sem build, contra a API local.

const api = {
  async req(method, path, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch {}
      throw new Error(detail);
    }
    return res.status === 204 ? null : res.json();
  },
  get: (p) => api.req("GET", p),
  post: (p, b) => api.req("POST", p, b),
  put: (p, b) => api.req("PUT", p, b),
  patch: (p, b) => api.req("PATCH", p, b),
};

const state = {
  projectId: null,
  project: null,
  taskId: null,
  task: null,
  events: null,
  messageCount: 0,
};

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};

function toast(msg, isError) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show" + (isError ? " err" : "");
  setTimeout(() => (t.className = ""), 3200);
}

// ---- projetos -------------------------------------------------------------
async function loadProjects() {
  const projects = await api.get("/projects");
  const sel = $("#project-select");
  sel.innerHTML = "";
  if (!projects.length) {
    sel.appendChild(el("option", null, "(nenhum projeto — use a CLI)"));
    return;
  }
  for (const p of projects) {
    const opt = el("option", null, p.name);
    opt.value = p.id;
    sel.appendChild(opt);
  }
  await selectProject(projects[0].id);
}

async function selectProject(id) {
  state.projectId = id;
  $("#project-select").value = id;
  state.project = await api.get(`/projects/${id}`);
  $("#killed-pill").hidden = !state.project.killed_reason;
  await loadTasks();
  await loadTab(currentTab);
}

// ---- tarefas --------------------------------------------------------------
async function loadTasks() {
  const tasks = await api.get(`/projects/${state.projectId}/tasks`);
  const list = $("#task-list");
  list.innerHTML = "";
  for (const t of tasks) {
    if (t.parent_id) continue; // subtarefas aparecem embutidas
    const li = el("li");
    li.dataset.id = t.id;
    if (t.id === state.taskId) li.classList.add("active");
    li.appendChild(el("span", "t-title", t.title));
    const meta = el("span", "muted");
    meta.appendChild(el("span", "pill " + t.status, t.status));
    li.appendChild(meta);
    li.onclick = () => openTask(t.id);
    list.appendChild(li);
  }
}

async function openTask(id) {
  state.taskId = id;
  state.messageCount = 0;
  $("#messages").innerHTML = "";
  $("#approval-area").innerHTML = "";
  $("#empty-center").classList.add("hidden");
  $("#conversation").classList.remove("hidden");
  document.querySelectorAll("#task-list li").forEach((li) =>
    li.classList.toggle("active", li.dataset.id === id)
  );
  await refreshTask();
  await loadMessages();
  await refreshApprovals();
  subscribe(id);
}

async function refreshTask() {
  state.task = await api.get(`/tasks/${state.taskId}`);
  $("#task-title").textContent = state.task.title;
  $("#task-mode").value = state.task.mode;
  const s = $("#task-status");
  s.textContent = state.task.status;
  s.className = "pill " + state.task.status;
  $("#task-budget").textContent =
    `${state.task.steps_used} passos · ${state.task.requests_used} req`;
}

async function loadMessages() {
  const messages = await api.get(`/tasks/${state.taskId}/messages`);
  $("#messages").innerHTML = "";
  state.messageCount = 0;
  for (const m of messages) renderMessage(m);
}

function renderMessage(m) {
  state.messageCount++;
  const box = el("div", "msg " + m.role);
  box.appendChild(el("div", "role", m.role === "human" ? "você" : m.role === "ai" ? "scopehound" : m.name));
  if (m.content) box.appendChild(el("div", null, m.content));
  for (const call of m.tool_calls || []) {
    box.appendChild(el("div", "tool-call", `↳ ${call.name}(${JSON.stringify(call.args)})`));
  }
  const msgs = $("#messages");
  msgs.appendChild(box);
  msgs.scrollTop = msgs.scrollHeight;
}

// ---- SSE ------------------------------------------------------------------
function subscribe(taskId) {
  if (state.events) state.events.close();
  const ev = new EventSource(`/tasks/${taskId}/events`);
  state.events = ev;
  ev.onmessage = (e) => {
    const data = JSON.parse(e.data);
    if (data.type === "message") renderMessage(data.message);
    else if (data.type === "status") { refreshTask(); loadTasks(); }
    else if (data.type === "approval") refreshApprovals();
  };
  ev.onerror = () => $("#status-dot").classList.remove("ok");
}

// ---- aprovações -----------------------------------------------------------
async function refreshApprovals() {
  const area = $("#approval-area");
  area.innerHTML = "";
  if (!state.taskId) return;
  const pending = await api.get(`/tasks/${state.taskId}/approvals?status=pending`);
  const mode = state.task ? state.task.mode : "smart";
  for (const a of pending) {
    const card = el("div", "approval");
    card.appendChild(el("div", null, `Aprovar ação`));
    const tool = el("div", "tool", `${a.tool} · ${a.impact}`);
    card.appendChild(tool);
    card.appendChild(el("div", "muted", a.reason));
    const pre = el("pre", null, JSON.stringify(a.args, null, 2));
    card.appendChild(pre);
    const actions = el("div", "actions");
    const opts = [["once", "Aprovar"]];
    if (mode === "smart") opts.push(["session", "Aprovar na sessão"]);
    if (mode === "manual") opts.push(["always", "Sempre aprovar"]);
    opts.push(["reject", "Rejeitar"], ["redirect", "Rejeitar + instrução"]);
    const note = el("textarea");
    note.placeholder = "Instrução (para rejeitar + redirecionar)";
    note.hidden = true;
    for (const [resp, label] of opts) {
      const btn = el("button", resp === "once" ? "small primary" : "small", label);
      btn.onclick = async () => {
        if (resp === "redirect" && note.hidden) { note.hidden = false; return; }
        try {
          await api.post(`/approvals/${a.id}`, { response: resp, note: note.value || "" });
          area.innerHTML = "";
        } catch (e) { toast(e.message, true); }
      };
      actions.appendChild(btn);
    }
    card.appendChild(actions);
    card.appendChild(note);
    area.appendChild(card);
  }
}

// ---- abas de contexto -----------------------------------------------------
let currentTab = "sitemap";
const tabs = {
  async sitemap(c) {
    const data = await api.get(`/projects/${state.projectId}/sitemap`);
    if (!Object.keys(data).length) { c.appendChild(el("div", "muted", "Sem tráfego ainda. Use o proxy ou importe um HAR.")); return; }
    for (const [origin, endpoints] of Object.entries(data)) {
      c.appendChild(el("div", "row", origin));
      for (const e of endpoints) {
        const row = el("div", "row");
        row.innerHTML = `<code>${e.method} ${e.path}</code> <span class="badge">×${e.count}</span> `
          + `<span class="muted">${e.statuses.join(",")}</span>`;
        const numeric = e.params.filter((p) => p.numeric && p.location !== "cookie").map((p) => p.name);
        if (numeric.length) row.appendChild(el("div", "muted", "num: " + numeric.join(", ")));
        c.appendChild(row);
      }
    }
  },
  async traffic(c) {
    const rows = await api.get(`/projects/${state.projectId}/traffic?limit=100`);
    if (!rows.length) { c.appendChild(el("div", "muted", "Sem tráfego.")); return; }
    for (const r of rows) {
      const row = el("div", "row");
      row.innerHTML = `<code>${r.method} ${r.path}</code> <span class="muted">→ ${r.status || "-"} ${r.response_size}B [${r.source}]</span>`;
      c.appendChild(row);
    }
  },
  async leads(c) {
    const leads = await api.get(`/projects/${state.projectId}/leads`);
    if (!leads.length) { c.appendChild(el("div", "muted", "Nenhum achado ainda.")); return; }
    for (const l of leads) {
      const row = el("div", "row");
      row.innerHTML = `<span class="sev ${l.severity}">${l.severity}</span> ${l.title} `
        + `<span class="badge">${l.status}</span><br><code>${l.url}</code>`;
      const ev = el("pre", "muted"); ev.textContent = l.evidence;
      row.appendChild(ev);
      c.appendChild(row);
    }
  },
  async scope(c) {
    c.appendChild(el("pre", null, JSON.stringify(state.project.scope, null, 2)));
    const kill = el("button", "small", state.project.killed_reason ? "Reativar projeto" : "Kill switch");
    kill.onclick = async () => {
      const path = state.project.killed_reason ? "revive" : "kill";
      await api.post(`/projects/${state.projectId}/${path}`, { reason: "via interface" });
      await selectProject(state.projectId);
      loadTab("scope");
    };
    c.appendChild(kill);
  },
  async tools(c) {
    const settings = await api.get(`/projects/${state.projectId}/tools`);
    for (const [name, cfg] of Object.entries(settings)) {
      const row = el("div", "tool-setting");
      const label = el("span", "name", name);
      label.appendChild(el("span", " badge", cfg.impact));
      row.appendChild(label);
      const enabled = el("input"); enabled.type = "checkbox"; enabled.checked = cfg.enabled;
      enabled.title = "habilitada";
      enabled.onchange = () => putTool(name, { enabled: enabled.checked });
      row.appendChild(enabled);
      if (!cfg.always_ask) {
        const manual = el("select");
        for (const v of ["ask", "act"]) {
          const o = el("option", null, v); o.value = v; if (cfg.manual === v) o.selected = true;
          manual.appendChild(o);
        }
        manual.title = "modo manual: ask/act";
        manual.onchange = () => putTool(name, { manual: manual.value });
        row.appendChild(manual);
      } else {
        row.appendChild(el("span", "muted", "sempre pergunta"));
      }
      c.appendChild(row);
    }
  },
  async audit(c) {
    const rows = await api.get(`/projects/${state.projectId}/audit?limit=120`);
    for (const r of rows) {
      const row = el("div", "row");
      row.innerHTML = `<span class="muted">${(r.created_at || "").slice(11, 19)}</span> `
        + `<code>${r.kind}</code> <span class="badge">${r.actor}</span><br>`
        + `${r.detail || ""} ${r.url ? `<span class="muted">${r.method || ""} ${r.url} → ${r.status_code ?? ""}</span>` : ""}`;
      c.appendChild(row);
    }
  },
};

async function putTool(name, change) {
  try {
    await api.put(`/projects/${state.projectId}/tools/${name}`, change);
    toast("ferramenta atualizada");
  } catch (e) { toast(e.message, true); loadTab("tools"); }
}

async function loadTab(tab) {
  currentTab = tab;
  document.querySelectorAll("#tabs button").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === tab)
  );
  const c = $("#tab-content");
  c.innerHTML = "";
  if (!state.projectId) return;
  try { await tabs[tab](c); }
  catch (e) { c.appendChild(el("div", "muted", "erro: " + e.message)); }
}

// ---- bootstrap ------------------------------------------------------------
async function health() {
  try { await api.get("/health"); $("#status-dot").className = "dot ok"; }
  catch { $("#status-dot").className = "dot bad"; }
}

function wire() {
  $("#project-select").onchange = (e) => selectProject(e.target.value);
  document.querySelectorAll("#tabs button").forEach((b) => (b.onclick = () => loadTab(b.dataset.tab)));
  $("#new-task-btn").onclick = () => $("#new-task-dialog").showModal();
  $("#nt-create").onclick = async (e) => {
    const prompt = $("#nt-prompt").value.trim();
    if (!prompt) { e.preventDefault(); return; }
    try {
      const task = await api.post(`/projects/${state.projectId}/tasks`,
        { prompt, mode: $("#nt-mode").value });
      $("#nt-prompt").value = "";
      await loadTasks();
      await openTask(task.id);
    } catch (err) { toast(err.message, true); }
  };
  $("#task-mode").onchange = async (e) => {
    await api.patch(`/tasks/${state.taskId}`, { mode: e.target.value });
    refreshTask();
  };
  $("#composer").onsubmit = async (e) => {
    e.preventDefault();
    const input = $("#composer-input");
    const content = input.value.trim();
    if (!content) return;
    input.value = "";
    try { await api.post(`/tasks/${state.taskId}/messages`, { content }); }
    catch (err) { toast(err.message, true); }
  };
}

(async function init() {
  wire();
  await health();
  setInterval(health, 10000);
  try { await loadProjects(); }
  catch (e) { toast("falha ao carregar: " + e.message, true); }
})();
