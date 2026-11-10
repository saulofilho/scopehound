# scopehound

**O farejador que nunca sai do escopo.** · [site](https://saulofilho.github.io/scopehound/) Agente de IA para pentest assistido
por humano, inspirado na lógica do [Burp AT](https://portswigger.net/burp/burp-at).
O modelo forma hipóteses e pede ações. **Escopo, permissões e limites são
impostos por uma camada separada do modelo**, e toda ação fica registrada no
projeto.

Roda **local** (um analista, na própria máquina) e foi desenhado para rodar
também **em servidor** (time, com login e projetos compartilhados, na Fase 5).

> ⚠️ **Uso autorizado apenas.** Aponte o scopehound só para sistemas seus ou
> com autorização por escrito. O arquivo de escopo é o contrato: o que não
> está nele é bloqueado antes de qualquer I/O.

---

## Sumário

1. [Status](#status)
2. [Como funciona](#como-funciona)
3. [Início rápido](#início-rápido)
4. [Tráfego e site map](#tráfego-e-site-map)
5. [Skills, /goal e subagentes](#skills-goal-e-subagentes)
6. [LLM: provedores e chave própria](#llm-provedores-e-chave-própria)
7. [Arquivo de escopo](#arquivo-de-escopo)
8. [Modos de autonomia e aprovações](#modos-de-autonomia-e-aprovações)
9. [Modelo de segurança](#modelo-de-segurança)
10. [Referência da CLI](#referência-da-cli)
11. [Referência da API](#referência-da-api)
12. [Configuração](#configuração)
13. [Estrutura do projeto](#estrutura-do-projeto)
14. [Desenvolvimento](#desenvolvimento)

---

## Status

| Fase | Conteúdo | Estado |
|---|---|---|
| 0 | Guardrails: escopo, política de IP, egress, orçamento, kill switch | ✅ |
| 1 | Núcleo do agente: policy engine, aprovações, ferramentas, API, chat | ✅ |
| 2 | Contexto de tráfego: proxy, importação HAR/Burp, site map | ✅ |
| 3 | Skills, `/goal` e subagentes | ✅ |
| 4 | Interface web | ✅ |
| 5 | Servidor: Docker, Postgres, SSO, listener OOB, ferramentas externas, CI | ✅ |

Plano completo: [docs/PLANO.md](docs/PLANO.md).

## Como funciona

```
  navegador ──▶ proxy ──┐      HAR / XML do Burp ──▶ import
                        ▼                                  │
                 histórico de tráfego + site map ◀─────────┘
                        ▲ (o agente lê)
  analista ──▶ chat / API
                  │
                  ▼
   ┌──────────── agente (LangGraph) ─────────────┐
   │                                              │
   │  agent ──▶ policy ──▶ tools ──┐              │
   │    ▲          │ pede aprovação │              │
   │    │          ▼ (pausa)        │              │
   │    └──────────────────────────┘              │
   └───────────────┬──────────────────────────────┘
                   ▼
   guardrails: escopo · política de IP · orçamento · kill switch · rate limit
                   ▼
              egress (único caminho de rede) ──▶ alvo autorizado
                   │
                   ▼
   banco do projeto: tarefas · aprovações · ações · leads · auditoria
```

1. **agent**: o modelo lê a conversa e pede ferramentas. Cada chamada
   consome passos e tokens do orçamento da tarefa.
2. **policy**: cada pedido é decidido pelo policy engine: passa, pede
   aprovação ou é negado. Quando pede aprovação, a tarefa **pausa**. A pausa
   fica salva em checkpoint e sobrevive a reinícios do processo.
3. **tools**: só o que foi permitido executa. Toda requisição passa pelo
   egress. Respostas do alvo voltam ao modelo marcadas como **dados não
   confiáveis**.

Como no Burp AT, achados nascem como **leads**. Só viram **confirmados**
quando `verify_finding` reexecuta a prova de conceito e a evidência bate.

| Burp AT | scopehound |
|---|---|
| Ferramentas do Burp | `send_request`, `search_traffic`, `get_request`, `site_map`, `diff_responses`, `save_lead`, `verify_finding`, `finish` |
| Proxy history e site map | `scopehound proxy` + histórico + site map normalizado (`/api/Users/{id}`) |
| Contexto do projeto (site map, tráfego) | O agente consulta o histórico antes de enviar requisições |
| Skills bank (metodologias) | Skills em arquivo; `use_skill` carrega a metodologia e foca as ferramentas |
| `/goal` e subagentes | Loop `/goal` e `spawn_subagent` com orçamento dividido |
| Scope do Burp, checado antes de agir | `Scope` + `check_url` + política de IP, no egress |
| Manual / Smart / Autonomous | Mesmos modos, no policy engine |
| Ask / Act por ferramenta | `scopehound project tool` / `PUT /projects/{id}/tools/{tool}` |
| Approve / session / always / reject / redirect | Mesmas respostas, com as mesmas regras |
| Arquivo de projeto e Logger | Banco SQLite com ações, aprovações, leads e auditoria de cada decisão |
| Tasks e conversa | Tarefas com conversa contínua (CLI `chat` ou API) |

## Início rápido

Requisitos: Python 3.12+ e [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/saulofilho/scopehound.git
cd scopehound
uv sync
cp .env.example .env          # configure o LLM (veja a próxima seção)
cp scope.example.yaml scope.yaml
```

Suba um alvo de laboratório, por exemplo o OWASP Juice Shop:

```bash
docker run --rm -p 3000:3000 bkimminich/juice-shop
```

Confira se o escopo libera o alvo. Esse comando não envia nada:

```bash
uv run scopehound check http://localhost:3000/rest/products/search --scope scope.yaml
```

Crie o projeto e converse com o agente:

```bash
uv run scopehound project create lab --scope scope.yaml
```

```bash
uv run scopehound chat lab --mode smart
```

```
você › mapeie a API de produtos em http://localhost:3000 e procure IDOR

scopehound › Vou começar pela listagem de produtos.
  ↳ send_request {"url": "http://localhost:3000/api/Products"}
  ⇠ send_request: <dados_do_alvo nao_confiaveis> GET ... -> 200 ...

⚠ aprovação: send_request (intrusive) — impacto intrusive: confirme antes de executar
  {"method": "POST", "url": "http://localhost:3000/api/BasketItems", ...}
  [o] aprovar uma vez [s] aprovar para a sessão (smart) [a] sempre aprovar (manual) [r] rejeitar [d] rejeitar e redirecionar
```

No chat, `/mode manual|smart|autonomous` troca o modo da tarefa e `/sair`
encerra. Para continuar depois: `scopehound chat lab --task <id>`.

Ou abra a **interface web**, que o próprio `serve` disponibiliza:

```bash
uv run scopehound serve
```

- Interface: `http://127.0.0.1:8787/app/` — painel de tarefas, conversa em
  tempo real, cartões de aprovação e abas de site map, tráfego, achados,
  escopo, ferramentas e auditoria.
- API e documentação interativa: `http://127.0.0.1:8787/docs`.

A interface é um app de página única em JavaScript puro (sem etapa de build e
sem CDN), servido pela própria API e falando com ela por `fetch` e SSE.

## Tráfego e site map

O agente trabalha melhor com contexto: o que você já navegou no app. O
histórico do projeto junta três origens, e **só guarda o que está no escopo**:

| Origem | Como |
|---|---|
| Proxy | `scopehound proxy lab` e navegue com o navegador apontado para ele |
| Importação | `scopehound import lab arquivo.har` ou o XML do Burp ("Save items") |
| Agente | Toda requisição do agente entra no histórico, com o id da tarefa |

**Proxy de captura** (requer `scopehound serve` rodando):

```bash
uv sync --extra proxy
```

```bash
uv run scopehound serve
```

```bash
uv run scopehound proxy lab --port 8081
```

Configure o navegador (ou uma extensão como FoxyProxy) para usar
`127.0.0.1:8081` e instale o certificado do mitmproxy em `http://mitm.it`
para capturar HTTPS. O proxy escuta só em 127.0.0.1 e repassa toda a sua
navegação, mas o projeto só guarda o que estiver no escopo. O agente nunca
usa o proxy: ele fala com a rede apenas pelo egress.

**Importar o que o time já capturou no Burp**: em Proxy › HTTP history,
selecione os itens › botão direito › *Save items* (com "Base64-encode"
marcado). Depois:

```bash
uv run scopehound import lab itens-burp.xml
```

O XML é lido com `defusedxml`: entidades externas (XXE) são recusadas.

**Site map**: paths com segmentos variáveis são normalizados (`{id}`,
`{uuid}`, `{hash}`, `{token}`) e os parâmetros observados ficam anotados
com a origem (`path`, `query`, `form`, `json`, `cookie`). `#num` indica que
todos os valores vistos eram numéricos, um bom ponto de partida para IDOR.

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

**Ferramentas do agente** (todas de leitura, liberadas no modo smart):

| Ferramenta | Faz |
|---|---|
| `site_map` | Mapa do alvo com endpoints, métodos e parâmetros |
| `search_traffic` | Busca por texto, host, método, path, status, parâmetro ou origem |
| `get_request` | Requisição e resposta completas de uma troca (id ou prefixo de 8+) |
| `diff_responses` | Compara duas respostas: status, tamanho, cabeçalhos e corpo |

> O histórico guarda cookies e tokens da sua navegação, e as ferramentas os
> mostram ao modelo. Com dados reais, use um LLM local (`--local-only`).

## Skills, /goal e subagentes

**Skills** são metodologias prontas para classes de vulnerabilidade
(equivalente ao banco de skills do Burp AT). Cada uma é um arquivo Markdown
com frontmatter: nome, descrição e as ferramentas que ela usa. O agente vê só
o catálogo (nome + descrição); ao escolher uma com `use_skill`, ele carrega a
metodologia **e as ferramentas ficam restritas às daquela skill** — tanto no
que o modelo enxerga quanto no que o policy engine deixa executar.

```bash
uv run scopehound skills
# content-discovery  Encontra endpoints, arquivos e áreas não lincadas ...
# idor               Testa acesso indevido a objetos de outro usuário ...
# race-condition     Testa condições de corrida enviando requisições concorrentes
```

Skills embutidas: `content-discovery`, `idor`, `race-condition`. Para
adicionar as suas, aponte `SCOPEHOUND_SKILL_DIRS` para um diretório com
arquivos `.md` (uma skill com o mesmo nome sobrescreve a embutida).

**Sessões de autenticação** alimentam a skill de IDOR: a `replay_as` repete
uma requisição do histórico como outra identidade. Cadastre pelo menos duas:

```bash
uv run scopehound session add lab userA -H "Cookie: token=aaa"
uv run scopehound session add lab userB -H "Cookie: token=bbb"
```

Os valores são guardados criptografados e nunca devolvidos pela API.

**`/goal`**: uma tarefa iniciada com `/goal <critério>` entra em um laço que
persegue o objetivo por vários passos, parando quando o agente chama `finish`,
quando o critério é cumprido ou quando o orçamento acaba.

```
você › /goal encontrar um IDOR na API de cestas
```

**Subagentes**: para investigações amplas, o agente pode chamar
`spawn_subagent`, que roda uma subtarefa paralela com orçamento próprio,
**descontado do orçamento do pai**. O resumo e os leads da subtarefa voltam
para o agente principal.

**Ferramentas desta fase**:

| Ferramenta | Impacto | Faz |
|---|---|---|
| `use_skill` | leitura | Carrega uma skill e restringe as ferramentas |
| `replay_as` | active | Repete uma troca como outra sessão (controle de acesso) |
| `content_discovery` | intrusive | Procura caminhos ocultos (wordlist) |
| `race_request` | intrusive | N requisições concorrentes (condição de corrida) |
| `read_source` | leitura | Lê um arquivo do código do alvo (dentro da raiz configurada) |
| `spawn_subagent` | active | Cria uma subtarefa paralela |

`read_source` só funciona se você apontar a raiz do código:
`scopehound project source lab /caminho/do/repo`. A leitura é confinada a essa
raiz (sem `..`).

## LLM: provedores e chave própria

O scopehound fala com qualquer provedor **compatível com a API da OpenAI**.
Trocar de modelo é só configuração.

| Provedor | `SCOPEHOUND_LLM_BASE_URL` | Custo | Quando usar |
|---|---|---|---|
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | free tier | Desenvolvimento e laboratório |
| Groq | `https://api.groq.com/openai/v1` | free tier | Alternativa / reserva |
| OpenRouter | `https://openrouter.ai/api/v1` | modelos `:free` | Alternativa / reserva |
| Ollama | `http://localhost:11434/v1` | grátis, local | **Dados sensíveis**: nada sai da máquina |

> ⚠️ Em free tiers, o provedor pode usar os dados enviados para treinar
> modelos. Use só com alvos de laboratório. Para tráfego real, use Ollama.

**Padrão para todos os projetos**, no `.env`:

```ini
SCOPEHOUND_LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
SCOPEHOUND_LLM_MODEL=gemini-2.5-flash   # confira o nome atual no Google AI Studio
SCOPEHOUND_LLM_API_KEY=sua-chave
```

**Por projeto, com a sua própria chave.** A chave é pedida sem eco no
terminal, guardada **criptografada** (Fernet) e **nunca devolvida** pela API:

```bash
uv run scopehound project llm lab --model gemini-2.5-flash --api-key
```

```bash
uv run scopehound project llm lab --base-url http://localhost:11434/v1 --model qwen3:8b
```

```bash
uv run scopehound project llm lab --clear-api-key
```

**Projetos com dados sensíveis** recusam qualquer LLM que não rode na sua
máquina:

```bash
uv run scopehound project create cliente-x --scope scope.yaml --local-only
```

## Arquivo de escopo

```yaml
allowed_hosts:
  - localhost
  - "*.lab"            # curinga só no formato *.sufixo (nada de *.com)
allowed_cidrs: []      # necessário para alvos em rede interna no modo servidor
allowed_ports: [3000, 8080]
allowed_schemes: [http, https]
allowed_paths: ["/*"]
exclude_paths:         # também bloqueia variações: /Logout, //logout, /%6cogout, /logout;x
  - /logout
  - /admin/delete
allowed_methods: [GET, HEAD, OPTIONS, POST, PUT, PATCH]
max_requests_per_second: 5
authorized_by: voce@empresa.com     # obrigatório
authorization_ref: TICKET-SEC-123
```

Escopos amplos demais são recusados: `*`, `*.com`, `0.0.0.0/0`, faixas
maiores que /8 (IPv4) ou /32 (IPv6).

## Modos de autonomia e aprovações

| Modo | Comportamento |
|---|---|
| `manual` | Cada ferramenta segue a configuração do projeto: **Ask** (pergunta) ou **Act** (executa) |
| `smart` (padrão) | Leituras e requisições sem efeito colateral (GET/HEAD/OPTIONS) passam; o resto pergunta |
| `autonomous` | Não pergunta, exceto em ferramentas que sempre exigem aprovação |

Regras que valem em qualquer modo:

- Ferramenta **desabilitada** nunca roda.
- Ferramenta **`always_ask`** (ex.: rodar script, alterar escopo) sempre
  pergunta e não pode virar Act.
- Pedidos de aprovação esperam indefinidamente.

| Resposta | Efeito | Disponível |
|---|---|---|
| `once` | Aprova só este pedido | sempre |
| `session` | Aprova esta ferramenta, neste nível de impacto, até o fim da tarefa | só `smart` |
| `always` | Muda a ferramenta para Act no projeto | só `manual` |
| `reject` | Recusa; o agente é informado | sempre |
| `redirect` | Recusa e envia uma instrução ao agente | sempre |

## Modelo de segurança

Nenhuma destas regras depende do modelo, e nenhum prompt as altera.

| Regra | Onde | O que garante |
|---|---|---|
| Escopo | `guardrails/scope.py` | Host, porta, esquema, path e método autorizados. O path é normalizado (`%XX`, `..`, `;params`, barras duplas) antes da comparação. Codificação dupla e credenciais na URL são recusadas |
| Política de IP | `guardrails/ippolicy.py` | Metadados de nuvem e faixas reservadas sempre bloqueados, inclusive em formas IPv6 (mapeado, NAT64, 6to4). Redes internas bloqueadas no modo servidor, salvo `allowed_cidrs` |
| Egress | `guardrails/egress.py` | Único caminho de rede. Conecta no IP validado (DNS pinning) com Host/SNI do nome original. Ignora proxy do ambiente, não segue redirect sozinho, limita o tamanho da resposta e registra cada decisão |
| Cabeçalho Host | `Egress._prepare_headers` | Não pode ser trocado: num IP permitido, um proxy reverso poderia encaminhar a requisição para fora do escopo |
| Redirects | `Egress.send_following_redirects` | Cada salto passa por todas as regras; credenciais não seguem para outro host |
| Policy engine | `policy/engine.py` | Modos, Ask/Act, ferramentas desabilitadas e `always_ask` |
| Orçamento | `guardrails/budget.py` | Passos, requisições e tokens por tarefa |
| Kill switch | `guardrails/killswitch.py` | Parada de emergência por projeto, persistida no banco |
| Rate limit | `guardrails/ratelimit.py` | Token bucket por projeto |
| Dados do alvo | `tools/registry.py` | Respostas chegam ao modelo marcadas como não confiáveis (defesa contra prompt injection) |
| Argumentos externos | `guardrails/toolargs.py` | Allowlist de flags do sqlmap (para a Fase 5) |
| Verificação de PoC | `guardrails/verification.py` | Achado só é confirmado com reexecução real |
| Segredos | `secrets.py` | Chaves de LLM dos projetos criptografadas; `secret.key` criado com permissão 0600 |

## Referência da CLI

| Comando | Faz |
|---|---|
| `scopehound check URL [-s scope.yaml] [-X MÉTODO]` | Diz se a requisição passaria e para qual IP iria, sem enviar nada |
| `scopehound project create NOME [-s scope.yaml] [--local-only]` | Cria um projeto a partir do escopo |
| `scopehound project list` | Lista os projetos |
| `scopehound project llm PROJETO [--base-url] [--model] [--api-key] [--clear-api-key]` | Define o LLM do projeto, inclusive com a sua chave |
| `scopehound project tool PROJETO FERRAMENTA [--enable/--disable] [--manual ask\|act]` | Liga/desliga ferramentas e define Ask/Act |
| `scopehound project source PROJETO [CAMINHO]` | Raiz de código para read_source (vazio remove) |
| `scopehound skills` | Lista as skills disponíveis |
| `scopehound session add PROJETO NOME -H 'Cookie: ...'` | Cadastra uma sessão de autenticação |
| `scopehound session list PROJETO` | Lista as sessões (sem valores) |
| `scopehound chat PROJETO [--task ID] [--mode MODO]` | Conversa no terminal, com aprovações interativas |
| `scopehound proxy PROJETO [--port 8081] [--api URL]` | Proxy de captura (extra `proxy`; requer `serve`) |
| `scopehound import PROJETO ARQUIVO [--format har\|burp]` | Importa HAR ou XML do Burp |
| `scopehound sitemap PROJETO [--host]` | Mostra o site map |
| `scopehound traffic PROJETO [-t TEXTO] [--limit N]` | Lista o histórico |
| `scopehound serve [--host] [--port]` | Sobe a API (no modo local, só em 127.0.0.1) |
| `scopehound run PROJETO --goal G [--fail-on SEV] [--sarif ARQ]` | Execução de CI (SARIF, exit code) |
| `scopehound version` | Mostra a versão |

## Referência da API

| Método e rota | Faz |
|---|---|
| `GET /health` | Estado do serviço |
| `POST /projects` · `GET /projects` · `GET /projects/{id}` | Projetos |
| `PUT /projects/{id}/llm` | LLM do projeto (`api_key` só de escrita) |
| `GET /projects/{id}/tools` · `PUT /projects/{id}/tools/{tool}` | Ferramentas (enabled, Ask/Act) |
| `POST /projects/{id}/kill` · `POST /projects/{id}/revive` | Kill switch |
| `GET /projects/{id}/leads` · `GET /projects/{id}/audit` | Leads e auditoria |
| `POST /projects/{id}/traffic` | Recebe trocas (usado pelo proxy; até 500 por chamada) |
| `POST /projects/{id}/traffic/import?filename=&format=` | Importa HAR ou XML do Burp (corpo da requisição) |
| `GET /projects/{id}/traffic` · `GET /projects/{id}/traffic/{troca}` | Histórico (filtros: `text`, `host`, `method`, `path_contains`, `status`, `param`, `source`) |
| `GET /projects/{id}/sitemap[?host=]` | Site map em JSON |
| `POST /projects/{id}/tasks` · `GET /projects/{id}/tasks` | Tarefas (rodam em segundo plano) |
| `GET /tasks/{id}` · `PATCH /tasks/{id}` | Tarefa e troca de modo |
| `GET /tasks/{id}/messages` · `POST /tasks/{id}/messages` | Conversa |
| `GET /tasks/{id}/actions` | Ações executadas, rejeitadas ou bloqueadas |
| `GET /tasks/{id}/approvals[?status=pending]` · `POST /approvals/{id}` | Aprovações |
| `GET /tasks/{id}/events` | Eventos em tempo real (SSE): mensagens, aprovações, status |
| `GET /tasks/{id}/subtasks` | Subtarefas de uma tarefa |
| `GET /skills` | Catálogo de skills |
| `GET /projects/{id}/sessions` · `PUT /projects/{id}/sessions` | Sessões de autenticação (valores só de escrita) |
| `PUT /projects/{id}/source` | Raiz de código do read_source |

Status de tarefa: `idle` · `running` · `waiting_approval` · `done` ·
`stopped` · `failed`.

> A API ainda não tem autenticação (chega na Fase 5). No modo local ela só
> escuta em 127.0.0.1; não exponha o modo servidor em rede antes disso.

## Modo servidor e deploy

O mesmo código roda para o time inteiro. `deploy/docker-compose.yml` sobe a
API com Postgres; preencha `deploy/.env` (veja `deploy/.env.example`).

```bash
cp deploy/.env.example deploy/.env   # senha do banco, SECRET_KEY, OIDC, LLM
docker compose -f deploy/docker-compose.yml up --build
```

Diferenças do modo servidor (`SCOPEHOUND_MODE=server`):

- **Autenticação (OIDC):** cada requisição traz um Bearer JWT, validado contra
  o JWKS do provedor (Keycloak, Okta, Google Workspace…). Papéis por nível:
  `viewer` (lê), `tester` (cria tarefas e age) e `admin` (muda escopo, LLM,
  ferramentas, kill switch). O papel vem da claim `scopehound_role`/`role`.
- **Rede interna bloqueada:** redes privadas e metadados de nuvem ficam
  bloqueados por padrão (anti-SSRF). `SCOPEHOUND_HARD_DENY_CIDRS` define faixas
  que **nenhum projeto** pode liberar, como a rede do cluster.
- **Postgres** no lugar do SQLite; **SECRET_KEY** obrigatório (criptografa as
  sessões de autenticação e as chaves de LLM dos projetos).
- **Mascaramento de dados:** quando o LLM não é local, o tráfego que vai para o
  modelo tem credenciais e PII mascaradas (`SCOPEHOUND_REDACT=auto`). O que é
  enviado ao alvo e o que fica guardado no projeto não mudam.

As rotas `/health`, `/oob/*` e a interface `/app` ficam abertas; o resto exige
token.

## Listener OOB

Equivalente simplificado ao Collaborator. `oob_payload` gera uma URL única; se
o alvo a acessar (SSRF, XXE, injeção cega), `oob_poll` mostra o callback. O
listener é a rota `/oob/{token}` da própria API; defina
`SCOPEHOUND_OOB_BASE_URL` com a URL externa pela qual o alvo a alcança. (DNS
OOB fica para depois.)

## Ferramentas externas

`nuclei`, `ffuf` e `sqlmap` são um segundo portão: **desligadas por padrão**
(`SCOPEHOUND_ENABLE_EXTERNAL_TOOLS=true` para habilitar) e não vêm instaladas
na imagem. São checadas contra o escopo; o `sqlmap` passa pela allowlist de
flags (força `--batch --risk=1 --level=1`, recusa `--os-shell`, `-u` para
outro alvo etc.) e **sempre pede aprovação**.

## Modo CI

```bash
uv run scopehound run demo --goal "encontrar IDOR na API" --fail-on high --sarif out.sarif
```

Roda uma tarefa `/goal` sem interação, imprime os leads, escreve SARIF 2.1.0
(consumível pelo GitHub code scanning) e sai com código ≠ 0 se houver achado
na severidade mínima. Use um LLM local no CI para não enviar tráfego para fora.

## Configuração

Variáveis de ambiente com prefixo `SCOPEHOUND_` (ou no `.env`; veja
[.env.example](.env.example)).

| Variável | Padrão | Descrição |
|---|---|---|
| `MODE` | `local` | `server` bloqueia redes internas por padrão e exige `SECRET_KEY` |
| `DATA_DIR` | `.scopehound` | Banco, checkpoints e `secret.key` |
| `DATABASE_URL` | SQLite em `DATA_DIR` | URL SQLAlchemy assíncrona |
| `HOST` / `PORT` | `127.0.0.1` / `8787` | Endereço da API |
| `SECRET_KEY` | gerada no modo local | Chave Fernet para criptografar segredos |
| `LLM_PROVIDER` | `openai_compat` | Provedor de LLM |
| `LLM_BASE_URL` | Gemini | URL compatível com OpenAI |
| `LLM_MODEL` | — | Nome do modelo |
| `LLM_API_KEY` | — | Chave padrão (projetos podem ter a própria) |
| `LLM_TEMPERATURE` | `0.1` | |
| `TASK_MAX_STEPS` | `30` | Passos do agente por tarefa |
| `TASK_MAX_REQUESTS` | `200` | Requisições por tarefa |
| `TASK_MAX_TOKENS` | `500000` | Tokens por tarefa |
| `SKILL_DIRS` | `[]` | Diretórios com skills do usuário (JSON) |
| `INTERNAL_DENY_CIDRS` | depende do modo | JSON, ex.: `["10.0.0.0/8"]` |
| `HARD_DENY_CIDRS` | `[]` | Faixas que nenhum projeto pode liberar |
| `VERIFY_TLS` | `true` | |
| `REDACT` | `auto` | Mascara dados ao LLM: `auto`/`on`/`off` ou categorias |
| `ENABLE_EXTERNAL_TOOLS` | `false` | Habilita nuclei/ffuf/sqlmap |
| `OOB_BASE_URL` | — | URL externa do listener OOB |
| `OIDC_ISSUER` / `OIDC_AUDIENCE` / `OIDC_JWKS_URL` | — | OIDC (modo servidor) |
| `REQUEST_TIMEOUT` | `15` | Segundos |
| `MAX_RESPONSE_BYTES` | `2000000` | Limite do corpo da resposta |

## Estrutura do projeto

```
src/scopehound/
├── guardrails/   escopo, política de IP, egress, orçamento, kill switch, rate limit
├── policy/       modos de autonomia, Ask/Act, regras de aprovação
├── tools/        ferramentas do agente (schema + impacto + execução)
├── traffic/      histórico, importadores HAR/Burp, site map, addon do mitmproxy
├── skills/       carregador de skills + skills embutidas (.md)
├── redact.py     mascaramento de dados enviados ao LLM
├── oob.py        registro do listener OOB
├── report.py     SARIF e resumo (modo CI)
├── api/auth.py   autenticação OIDC e papéis
├── agent/        grafo LangGraph, prompt, provedor de LLM, modelo roteirizado
├── core/         runtime, casos de uso, execução de tarefas, eventos
├── store/        modelos SQLAlchemy e migrações Alembic
├── api/          FastAPI
├── web/          interface (HTML/CSS/JS, sem build)
├── chat.py       chat de terminal
├── secrets.py    criptografia de segredos
├── config.py     configuração
└── cli.py        CLI
deploy/           Dockerfile, docker-compose, .env de exemplo
docs/PLANO.md     plano das fases
tests/            testes (LLM roteirizado e alvo simulado; não gastam tokens)
```

## Desenvolvimento

```bash
uv sync
uv run ruff check && uv run ruff format --check && uv run pytest
```

Os testes não usam LLM real nem rede externa. O agente roda com um modelo
roteirizado (`agent/fake.py`) e o alvo é simulado. Um dos testes cobre o
critério de pronto de cada fase: na Fase 1, pedir aprovação, pausar, reiniciar
o processo, retomar e registrar um lead; na Fase 2, responder quais endpoints
recebem IDs numéricos usando só o tráfego do projeto; na Fase 3, um `/goal`
que persegue o objetivo por vários passos e um subagente que divide o orçamento;
na Fase 4, a interface é servida e usa só endpoints já existentes; na Fase 5,
o mascaramento, a allowlist do sqlmap, os papéis de acesso e o SARIF do CI.

Nova migração depois de alterar `store/models.py`:

```bash
uv run python -c "from alembic import command; from scopehound.store.db import alembic_config; command.revision(alembic_config('sqlite:///.scopehound/scopehound.db'), message='descricao', autogenerate=True)"
```
