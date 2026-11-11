# scopehound

**Português:** [README.md](README.md) · **English:** this file

**The hound that never leaves the scope.** · [site](https://saulofilho.github.io/scopehound/)
A human-led pentest AI agent, inspired by the logic of
[Burp AT](https://portswigger.net/burp/burp-at). The model forms hypotheses and
requests actions. **Scope, permissions and limits are enforced by a layer
separate from the model**, and every action is recorded in the project.

It runs **local** (one analyst, on their own machine) and is designed to run
**on a server** too (a team, with login and shared projects).

> ⚠️ **Authorized use only.** Point scopehound only at systems you own or have
> written authorization to test. The scope file is the contract: anything not
> in it is blocked before any I/O.

> 🌐 **Language.** The UI messages and the agent's answers follow
> `SCOPEHOUND_LANGUAGE` (`pt` or `en`, default `pt`).

---

## Contents

1. [Status](#status)
2. [How it works](#how-it-works)
3. [Quick start](#quick-start)
4. [Traffic and site map](#traffic-and-site-map)
5. [Skills, /goal and subagents](#skills-goal-and-subagents)
6. [Workspace and file tools](#workspace-and-file-tools)
7. [LLM: providers and your own key](#llm-providers-and-your-own-key)
8. [Scope file](#scope-file)
9. [Autonomy modes and approvals](#autonomy-modes-and-approvals)
10. [Security model](#security-model)
11. [CLI reference](#cli-reference)
12. [API reference](#api-reference)
13. [Configuration](#configuration)
14. [Project layout](#project-layout)
15. [Development](#development)

---

## Status

| Phase | Content | State |
|---|---|---|
| 0 | Guardrails: scope, IP policy, egress, budget, kill switch | ✅ |
| 1 | Agent core: policy engine, approvals, tools, API, chat | ✅ |
| 2 | Traffic context: proxy, HAR/Burp import, site map | ✅ |
| 3 | Skills, `/goal` and subagents | ✅ |
| 4 | Web interface | ✅ |
| 5 | Server: Docker, Postgres, SSO, OOB listener, external tools, CI | ✅ |

Full plan (in Portuguese): [docs/PLANO.md](docs/PLANO.md).

## How it works

```
  browser ──▶ proxy ──┐      HAR / Burp XML ──▶ import
                      ▼                               │
               traffic history + site map ◀──────────┘
                      ▲ (the agent reads)
  analyst ──▶ chat / API
                 │
                 ▼
   ┌──────────── agent (LangGraph) ──────────────┐
   │                                              │
   │  agent ──▶ policy ──▶ tools ──┐              │
   │    ▲          │ asks approval  │              │
   │    │          ▼ (pauses)       │              │
   │    └──────────────────────────┘              │
   └───────────────┬──────────────────────────────┘
                   ▼
   guardrails: scope · IP policy · budget · kill switch · rate limit
                   ▼
              egress (the only network path) ──▶ authorized target
                   │
                   ▼
   project store: tasks · approvals · actions · leads · audit
```

1. **agent**: the model reads the conversation and requests tools. Each call
   consumes steps and tokens from the task budget.
2. **policy**: every request is decided by the policy engine — allow, ask for
   approval, or deny. When it asks, the task **pauses**. The pause is saved in
   a checkpoint and survives process restarts.
3. **tools**: only what was allowed runs. Every request goes through the
   egress. Target responses come back to the model tagged as **untrusted
   data**.

As in Burp AT, findings start as **leads**. They only become **confirmed**
when `verify_finding` re-runs the proof of concept and the evidence matches.

| Burp AT | scopehound |
|---|---|
| Burp's tools | `send_request`, `search_traffic`, `get_request`, `site_map`, `diff_responses`, `save_lead`, `verify_finding`, `finish` |
| Proxy history and site map | `scopehound proxy` + history + normalized site map (`/api/Users/{id}`) |
| Project context (site map, traffic) | The agent consults the history before sending requests |
| Skills bank (methodologies) | File-based skills; `use_skill` loads the methodology and focuses the tools |
| `/goal` and subagents | `/goal` loop and `spawn_subagent` with a split budget |
| Burp scope, checked before acting | `Scope` + `check_url` + IP policy, at the egress |
| Manual / Smart / Autonomous | Same modes, in the policy engine |
| Ask / Act per tool | `scopehound project tool` / `PUT /projects/{id}/tools/{tool}` |
| Approve / session / always / reject / redirect | Same responses, same rules |
| Project file and Logger | SQLite store with actions, approvals, leads and an audit of every decision |
| Tasks and conversation | Tasks with a continuous conversation (CLI `chat` or API) |

## Quick start

Requirements: Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/saulofilho/scopehound.git
cd scopehound
uv sync
cp .env.example .env          # configure the LLM (see the next section)
cp scope.example.yaml scope.yaml
```

Bring up a lab target, e.g. OWASP Juice Shop:

```bash
docker run --rm -p 3000:3000 bkimminich/juice-shop
```

Check that the scope allows the target. This command sends nothing:

```bash
uv run scopehound check http://localhost:3000/rest/products/search --scope scope.yaml
```

Before running a task, verify the LLM connection:

```bash
uv run scopehound doctor
```

Create the project and chat with the agent:

```bash
uv run scopehound project create lab --scope scope.yaml
```

```bash
uv run scopehound chat lab --mode smart
```

Or open the **web interface**, served by `serve` itself:

```bash
uv run scopehound serve
```

- Interface: `http://127.0.0.1:8787/app/` — task panel, live conversation,
  approval cards and tabs for site map, traffic, findings, scope, tools and
  audit.
- API and interactive docs: `http://127.0.0.1:8787/docs`.

The interface is a single-page vanilla-JS app (no build step, no CDN), served
by the API itself and talking to it over `fetch` and SSE.

## Traffic and site map

The agent works better with context: what you already browsed in the app. The
project history combines three sources, and **only keeps what is in scope**:

| Source | How |
|---|---|
| Proxy | `scopehound proxy lab` and browse with your browser pointed at it |
| Import | `scopehound import lab file.har` or the Burp XML ("Save items") |
| Agent | Every agent request enters the history, tagged with the task id |

**Capture proxy** (requires `scopehound serve` running):

```bash
uv sync --extra proxy
```

```bash
uv run scopehound serve
```

```bash
uv run scopehound proxy lab --port 8081
```

Point your browser (or an extension like FoxyProxy) at `127.0.0.1:8081` and
install the mitmproxy certificate at `http://mitm.it` to capture HTTPS. The
proxy only listens on 127.0.0.1 and relays all of your browsing, but the
project only stores what is in scope. The agent never uses the proxy: it only
reaches the network through the egress.

**Import what the team already captured in Burp**: in Proxy › HTTP history,
select the items › right-click › *Save items* (with "Base64-encode" checked).
Then:

```bash
uv run scopehound import lab burp-items.xml
```

The XML is parsed with `defusedxml`: external entities (XXE) are rejected.

**Site map**: variable path segments are normalized (`{id}`, `{uuid}`,
`{hash}`, `{token}`) and observed parameters are annotated with their location
(`path`, `query`, `form`, `json`, `cookie`). `#num` means every value seen was
numeric — a good starting point for IDOR.

```
$ uv run scopehound sitemap lab
http://localhost:3000
  POST    /api/BasketItems  ×1 [201] ex:a650caf71b06
          params: BasketId[json#num], ProductId[json#num], quantity[json#num]
  GET     /api/Products/{id}  ×2 [200] ex:249047589553
          params: {id}#3[path#num]
  GET     /rest/products/search  ×1 [200] ex:189017d53cc2
          params: q[query]
```

**Agent tools** (all read-only, allowed in smart mode):

| Tool | What it does |
|---|---|
| `site_map` | Target map with endpoints, methods and parameters |
| `search_traffic` | Search by text, host, method, path, status, parameter or source |
| `get_request` | Full request and response of an exchange (id or 8+ char prefix) |
| `diff_responses` | Compare two responses: status, size, headers and body |

> The history keeps cookies and tokens from your browsing, and the tools show
> them to the model. With real data, use a local LLM (`--local-only`).

## Skills, /goal and subagents

**Skills** are ready-made methodologies for vulnerability classes (the
equivalent of Burp AT's skills bank). Each is a Markdown file with frontmatter:
name, description and the tools it uses. The agent only sees the catalog
(name + description); when it picks one with `use_skill`, it loads the
methodology **and the tools are restricted to that skill** — both in what the
model sees and in what the policy engine lets it run.

```bash
uv run scopehound skills
```

Built-in skills: `content-discovery`, `idor`, `race-condition`. To add your
own, point `SCOPEHOUND_SKILL_DIRS` at a folder of `.md` files (a skill with the
same name overrides the built-in one).

**Auth sessions** feed the IDOR skill: `replay_as` repeats a history request as
another identity. Register at least two:

```bash
uv run scopehound session add lab userA -H "Cookie: token=aaa"
uv run scopehound session add lab userB -H "Cookie: token=bbb"
```

The values are stored encrypted and never returned by the API.

**`/goal`**: a task started with `/goal <criteria>` enters a loop that pursues
the objective across several steps, stopping when the agent calls `finish`,
when the criteria are met, or when the budget runs out.

```
you › /goal find an IDOR in the baskets API
```

**Subagents**: for broad investigations, the agent can call `spawn_subagent`,
which runs a parallel subtask with its own budget, **deducted from the
parent's**. The subtask's summary and leads come back to the main agent.

**Tools in this phase**:

| Tool | Impact | What it does |
|---|---|---|
| `use_skill` | read | Load a skill and restrict the tools |
| `replay_as` | active | Replay an exchange as another session (access control) |
| `content_discovery` | intrusive | Look for hidden paths (wordlist) |
| `race_request` | intrusive | N concurrent requests (race condition) |
| `read_source` | read | Read a file from the target source (within the configured root) |
| `spawn_subagent` | active | Create a parallel subtask |

`read_source` only works if you point it at the source root:
`scopehound project source lab /path/to/repo`. Reads are confined to that root
(no `..`, no symlink escape).

## Workspace and file tools

The **workspace** is an opt-in read-write folder the agent uses for inputs and
outputs (target lists, wordlists, findings, notes):

```bash
uv run scopehound project workspace lab /path/to/folder
```

| Tool | Impact | What it does |
|---|---|---|
| `list_files`, `read_file` | read | List and read files in the workspace |
| `write_file` | intrusive | Write a file in the workspace (requires approval) |

Everything is confined by `fsguard`: no `..`, no absolute path, no symlink
escape (on reads and on the write's parent directory), never the scopehound
data folder, and writing rejects executable extensions (`.sh`, `.py`…). In
server mode the file tools are off by default (`SCOPEHOUND_FILE_TOOLS=true` to
enable them).

## LLM: providers and your own key

scopehound talks to any provider **compatible with the OpenAI API**. Switching
model is just configuration.

| Provider | `SCOPEHOUND_LLM_BASE_URL` | Cost | When to use |
|---|---|---|---|
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | free tier | Development and lab |
| Groq | `https://api.groq.com/openai/v1` | free tier | Alternative / backup |
| OpenRouter | `https://openrouter.ai/api/v1` | `:free` models | Alternative / backup |
| Ollama | `http://localhost:11434/v1` | free, local | **Sensitive data**: nothing leaves the machine |

> ⚠️ On free tiers the provider may use the data you send to train models. Use
> them only with lab targets. For real traffic, use Ollama.

**Default for every project**, in `.env`:

```ini
SCOPEHOUND_LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
SCOPEHOUND_LLM_MODEL=gemini-2.5-flash   # check the current name in Google AI Studio
SCOPEHOUND_LLM_API_KEY=your-key
```

**Per project, with your own key.** The key is prompted without echo, stored
**encrypted** (Fernet) and **never returned** by the API:

```bash
uv run scopehound project llm lab --model gemini-2.5-flash --api-key
```

```bash
uv run scopehound project llm lab --base-url http://localhost:11434/v1 --model qwen3:8b
```

```bash
uv run scopehound project llm lab --clear-api-key
```

**Projects with sensitive data** refuse any LLM that is not local to your
machine:

```bash
uv run scopehound project create client-x --scope scope.yaml --local-only
```

If a task fails with `OpenAIModelNotFoundError` / 404, the model name almost
always is the cause: on Ollama it needs the exact tag from `ollama list` (e.g.
`qwen3:8b`, not `qwen3`), and the model must have been pulled with
`ollama pull`. `scopehound doctor` reports exactly what to fix.

## Scope file

```yaml
allowed_hosts:
  - localhost
  - "*.lab"            # wildcard only as *.suffix (no *.com)
allowed_cidrs: []      # needed for internal-network targets in server mode
allowed_ports: [3000, 8080]
allowed_schemes: [http, https]
allowed_paths: ["/*"]
exclude_paths:         # also blocks variants: /Logout, //logout, /%6cogout, /logout;x
  - /logout
  - /admin/delete
allowed_methods: [GET, HEAD, OPTIONS, POST, PUT, PATCH]
max_requests_per_second: 5
authorized_by: you@company.com     # required
authorization_ref: TICKET-SEC-123
```

Scopes that are too broad are rejected: `*`, `*.com`, `0.0.0.0/0`, ranges
larger than /8 (IPv4) or /32 (IPv6).

## Autonomy modes and approvals

| Mode | Behavior |
|---|---|
| `manual` | Each tool follows the project setting: **Ask** (prompts) or **Act** (runs) |
| `smart` (default) | Reads and side-effect-free requests (GET/HEAD/OPTIONS) pass; the rest ask |
| `autonomous` | Does not ask, except for tools that always require approval |

Rules that hold in any mode:

- A **disabled** tool never runs.
- An **`always_ask`** tool (e.g. run a script, change scope, sqlmap) always
  asks and cannot become Act.
- Approval requests wait indefinitely.

| Response | Effect | Available |
|---|---|---|
| `once` | Approves this request only | always |
| `session` | Approves this tool, at this impact, until the task ends | `smart` only |
| `always` | Switches the tool to Act for the project | `manual` only |
| `reject` | Refuses; the agent is told | always |
| `redirect` | Refuses and sends an instruction to the agent | always |

## Security model

None of these rules depend on the model, and no prompt changes them.

| Rule | Where | What it guarantees |
|---|---|---|
| Scope | `guardrails/scope.py` | Authorized host, port, scheme, path and method. The path is normalized (`%XX`, `..`, `;params`, double slashes) before matching. Double encoding and credentials in the URL are rejected |
| IP policy | `guardrails/ippolicy.py` | Cloud metadata and reserved ranges always blocked, including IPv6 forms (mapped, NAT64, 6to4). Internal networks blocked in server mode, unless in `allowed_cidrs` |
| Egress | `guardrails/egress.py` | The only network path. Connects to the validated IP (DNS pinning) with the original name's Host/SNI. Ignores the environment proxy, does not follow redirects on its own, caps the response size, and records every decision |
| Host header | `Egress._prepare_headers` | Cannot be changed: on an allowed IP, a reverse proxy could forward the request out of scope |
| Redirects | `Egress.send_following_redirects` | Each hop passes every rule; credentials do not follow to another host |
| Policy engine | `policy/engine.py` | Modes, Ask/Act, disabled tools and `always_ask` |
| Budget | `guardrails/budget.py` | Steps, requests and tokens per task |
| Kill switch | `guardrails/killswitch.py` | Per-project emergency stop, persisted in the store |
| Rate limit | `guardrails/ratelimit.py` | Per-project token bucket |
| Target data | `tools/registry.py` | Responses reach the model tagged as untrusted (prompt-injection defense) |
| External args | `guardrails/toolargs.py` | sqlmap flag allowlist |
| File confinement | `fsguard.py` | Workspace/source reads and writes confined (no `..`, no symlink escape, no reserved folders) |
| PoC verification | `guardrails/verification.py` | A finding is confirmed only with a real re-run |
| Secrets | `secrets.py` | Project LLM keys and auth sessions encrypted; `secret.key` created 0600 |

## CLI reference

| Command | Does |
|---|---|
| `scopehound check URL [-s scope.yaml] [-X METHOD]` | Says whether the request would pass and to which IP, sending nothing |
| `scopehound doctor [--project P]` | Test the LLM connection (provider, model, credential) |
| `scopehound project create NAME [-s scope.yaml] [--local-only]` | Create a project from the scope |
| `scopehound project list` | List the projects |
| `scopehound project llm PROJECT [--base-url] [--model] [--api-key] [--clear-api-key]` | Set the project LLM, including your key |
| `scopehound project tool PROJECT TOOL [--enable/--disable] [--manual ask\|act]` | Enable/disable tools and set Ask/Act |
| `scopehound project source PROJECT [PATH]` | Source root for read_source (empty removes) |
| `scopehound project workspace PROJECT [PATH]` | Read-write folder for the file tools |
| `scopehound skills` | List the available skills |
| `scopehound session add PROJECT NAME -H 'Cookie: ...'` | Register an auth session |
| `scopehound session list PROJECT` | List the sessions (no values) |
| `scopehound proxy PROJECT [--port 8081] [--api URL]` | Capture proxy (extra `proxy`; needs `serve`) |
| `scopehound import PROJECT FILE [--format har\|burp]` | Import HAR or Burp XML |
| `scopehound sitemap PROJECT [--host]` | Show the site map |
| `scopehound traffic PROJECT [-t TEXT] [--limit N]` | List the history |
| `scopehound chat PROJECT [--task ID] [--mode MODE]` | Chat in the terminal, with interactive approvals |
| `scopehound serve [--host] [--port]` | Start the API (local mode binds 127.0.0.1 only) |
| `scopehound run PROJECT --goal G [--fail-on SEV] [--sarif FILE]` | CI run (SARIF, exit code) |
| `scopehound version` | Show the version |

## API reference

| Method and route | Does |
|---|---|
| `GET /health` | Service state |
| `POST /projects` · `GET /projects` · `GET /projects/{id}` | Projects |
| `PUT /projects/{id}/llm` | Project LLM (`api_key` write-only) |
| `GET /projects/{id}/tools` · `PUT /projects/{id}/tools/{tool}` | Tools (enabled, Ask/Act) |
| `PUT /projects/{id}/source` · `PUT /projects/{id}/workspace` | Source root and workspace |
| `POST /projects/{id}/kill` · `POST /projects/{id}/revive` | Kill switch |
| `GET /projects/{id}/leads` · `GET /projects/{id}/audit` | Leads and audit |
| `POST /projects/{id}/traffic` | Receive exchanges (used by the proxy; up to 500 per call) |
| `POST /projects/{id}/traffic/import?filename=&format=` | Import HAR or Burp XML (request body) |
| `GET /projects/{id}/traffic` · `GET /projects/{id}/traffic/{exchange}` | History (filters: `text`, `host`, `method`, `path_contains`, `status`, `param`, `source`) |
| `GET /projects/{id}/sitemap[?host=]` | Site map as JSON |
| `POST /projects/{id}/tasks` · `GET /projects/{id}/tasks` | Tasks (run in the background) |
| `GET /tasks/{id}` · `PATCH /tasks/{id}` | Task and mode change |
| `GET /tasks/{id}/messages` · `POST /tasks/{id}/messages` | Conversation |
| `GET /tasks/{id}/actions` | Actions executed, rejected or blocked |
| `GET /tasks/{id}/approvals[?status=pending]` · `POST /approvals/{id}` | Approvals |
| `GET /tasks/{id}/subtasks` | A task's subtasks |
| `GET /tasks/{id}/events` | Live events (SSE): messages, approvals, status |
| `GET /skills` | Skills catalog |
| `GET /projects/{id}/sessions` · `PUT /projects/{id}/sessions` | Auth sessions (write-only values) |

Task status: `idle` · `running` · `waiting_approval` · `done` · `stopped` ·
`failed`.

> The API has no authentication in local mode (it binds 127.0.0.1 only). In
> server mode it validates an OIDC Bearer JWT; do not expose server mode on a
> network without it.

## Configuration

Environment variables prefixed with `SCOPEHOUND_` (or in `.env`; see
[.env.example](.env.example)).

| Variable | Default | Description |
|---|---|---|
| `MODE` | `local` | `server` blocks internal networks by default and requires `SECRET_KEY` |
| `LANGUAGE` | `pt` | UI and agent language (`pt` or `en`) |
| `DATA_DIR` | `.scopehound` | Store, checkpoints and `secret.key` |
| `DATABASE_URL` | SQLite in `DATA_DIR` | Async SQLAlchemy URL |
| `HOST` / `PORT` | `127.0.0.1` / `8787` | API address |
| `SECRET_KEY` | generated in local mode | Fernet key to encrypt secrets |
| `LLM_PROVIDER` | `openai_compat` | LLM provider |
| `LLM_BASE_URL` | Gemini | OpenAI-compatible URL |
| `LLM_MODEL` | — | Model name |
| `LLM_API_KEY` | — | Default key (projects can have their own) |
| `LLM_TEMPERATURE` | `0.1` | |
| `TASK_MAX_STEPS` | `30` | Agent steps per task |
| `TASK_MAX_REQUESTS` | `200` | Requests per task |
| `TASK_MAX_TOKENS` | `500000` | Tokens per task |
| `INTERNAL_DENY_CIDRS` | mode-dependent | JSON, e.g. `["10.0.0.0/8"]` |
| `HARD_DENY_CIDRS` | `[]` | Ranges no project can allow |
| `VERIFY_TLS` | `true` | |
| `REDACT` | `auto` | Mask data to the LLM: `auto`/`on`/`off` or categories |
| `ENABLE_EXTERNAL_TOOLS` | `false` | Enable nuclei/ffuf/sqlmap |
| `FILE_TOOLS` | auto | File tools: on local, off server |
| `OOB_BASE_URL` | — | External URL of the OOB listener |
| `SKILL_DIRS` | `[]` | Folders with user skills (JSON) |
| `OIDC_ISSUER` / `OIDC_AUDIENCE` / `OIDC_JWKS_URL` | — | OIDC (server mode) |

## Project layout

```
src/scopehound/
├── guardrails/   scope, IP policy, egress, budget, kill switch, rate limit
├── policy/       autonomy modes, Ask/Act, approval rules
├── tools/        agent tools (schema + impact + execution)
├── traffic/      history, HAR/Burp importers, site map, mitmproxy addon
├── skills/       skill loader + built-in skills (.md)
├── agent/        LangGraph graph, prompt, LLM provider, scripted model
├── core/         runtime, use cases, task execution, events
├── store/        SQLAlchemy models and Alembic migrations
├── api/          FastAPI (api/auth.py: OIDC and roles)
├── web/          interface (HTML/CSS/JS, no build)
├── i18n.py       UI language (pt/en)
├── redact.py     masking of data sent to the LLM
├── oob.py        OOB listener registry
├── report.py     SARIF and summary (CI mode)
├── fsguard.py    path confinement for the file tools
├── secrets.py    secret encryption
├── config.py     configuration
└── cli.py        CLI
deploy/           Dockerfile, docker-compose, sample .env
docs/PLANO.md     phase plan (Portuguese)
tests/            tests (scripted LLM and simulated target; spend no tokens)
```

## Development

```bash
uv sync
uv run ruff check && uv run ruff format --check && uv run pytest
```

The tests use no real LLM and no external network. The agent runs with a
scripted model (`agent/fake.py`) and the target is simulated.

Source comments and docstrings are in English; user-facing text is bilingual
through `i18n.t(pt, en)`.

New migration after changing `store/models.py`:

```bash
uv run python -c "from alembic import command; from scopehound.store.db import alembic_config; command.revision(alembic_config('sqlite:///.scopehound/scopehound.db'), message='description', autogenerate=True)"
```
