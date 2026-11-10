# scopehound

O farejador que nunca sai do escopo. Agente de IA para pentest assistido por
humano, inspirado na lógica do [Burp AT](https://portswigger.net/burp/burp-at):
o modelo forma hipóteses e pede ações; **escopo, permissões e limites são
impostos por uma camada separada do modelo**, e toda ação fica registrada.

> ⚠️ Uso autorizado apenas. O arquivo de escopo é o contrato: o que não está
> nele é bloqueado antes de qualquer I/O.

Plano completo: [docs/PLANO.md](docs/PLANO.md). Estado atual: **Fase 1 (núcleo do agente)**.

## Guardrails (Fase 0)

| Regra | Onde | O que garante |
|---|---|---|
| Escopo | `guardrails/scope.py` | Host, porta, esquema, path e método autorizados. Path normalizado (`%XX`, `..`, `;params`, barras duplas) antes da comparação; codificação dupla e credenciais na URL são recusadas |
| Política de IP | `guardrails/ippolicy.py` | Metadados de nuvem e faixas reservadas sempre bloqueados; redes internas bloqueadas no modo servidor, salvo `allowed_cidrs` |
| Egress | `guardrails/egress.py` | Único caminho de rede. DNS pinning (conecta no IP validado, Host/SNI do nome original), sem proxy do ambiente, sem redirect automático, corpo limitado, evento de auditoria por decisão |
| Redirects | `Egress.send_following_redirects` | Cada salto passa por todas as regras; credenciais não seguem para outro host |
| Orçamento | `guardrails/budget.py` | Passos, requisições e tokens, com orçamentos filhos para subagentes |
| Kill switch | `guardrails/killswitch.py` | Parada de emergência do projeto |
| Rate limit | `guardrails/ratelimit.py` | Token bucket por projeto (`max_requests_per_second`) |
| Argumentos externos | `guardrails/toolargs.py` | Allowlist de flags do sqlmap |
| Verificação de PoC | `guardrails/verification.py` | Achado só é confirmado com reexecução real |

## Agente (Fase 1)

O modelo pede ações; o policy engine decide; só então as ferramentas executam.

- **Modos** (como no Burp AT): `manual` (cada ferramenta Ask/Act), `smart`
  (padrão: leituras e GET passam, o resto pergunta), `autonomous`.
  Ferramentas desabilitadas nunca rodam; ferramentas `always_ask` sempre perguntam.
- **Aprovações**: aprovar uma vez · para a sessão (smart) · sempre (manual) ·
  rejeitar · rejeitar e redirecionar. A pausa sobrevive a reinícios (checkpoint).
- **Ferramentas**: `send_request`, `save_lead`, `verify_finding`, `finish`.
- **Registro**: ações, aprovações, leads e cada decisão de egress ficam no banco.

### LLM

Qualquer provedor compatível com a API da OpenAI: Gemini (free tier),
Groq, OpenRouter ou Ollama (local). Configure no `.env` (veja `.env.example`)
ou por projeto, **com a sua própria chave** (guardada criptografada, nunca
devolvida pela API):

```bash
uv run scopehound project llm lab --model gemini-2.5-flash --api-key
```

Projetos com dados sensíveis: `project create --local-only` recusa qualquer
LLM que não rode na sua máquina.

## Uso

```bash
uv sync
cp scope.example.yaml scope.yaml
uv run scopehound check http://localhost:3000/api/users --scope scope.yaml
```

`check` não envia nada: só diz se a requisição passaria e para qual IP iria.

```bash
uv run scopehound project create lab --scope scope.yaml
uv run scopehound chat lab --mode smart     # conversa com aprovações no terminal
uv run scopehound serve                     # API em http://127.0.0.1:8787/docs
```

## Configuração

| Variável | Padrão | |
|---|---|---|
| `SCOPEHOUND_MODE` | `local` | `server` bloqueia redes internas por padrão |
| `SCOPEHOUND_INTERNAL_DENY_CIDRS` | depende do modo | JSON, ex.: `["10.0.0.0/8"]` |
| `SCOPEHOUND_HARD_DENY_CIDRS` | `[]` | faixas que nenhum projeto pode liberar |
| `SCOPEHOUND_VERIFY_TLS` | `true` | |

## Desenvolvimento

```bash
uv run ruff check && uv run ruff format --check && uv run pytest
```
