# scopehound

O farejador que nunca sai do escopo. Agente de IA para pentest assistido por
humano, inspirado na lógica do [Burp AT](https://portswigger.net/burp/burp-at):
o modelo forma hipóteses e pede ações; **escopo, permissões e limites são
impostos por uma camada separada do modelo**, e toda ação fica registrada.

> ⚠️ Uso autorizado apenas. O arquivo de escopo é o contrato: o que não está
> nele é bloqueado antes de qualquer I/O.

Plano completo: [docs/PLANO.md](docs/PLANO.md). Estado atual: **Fase 0 (guardrails)**.

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

## Uso

```bash
uv sync
cp scope.example.yaml scope.yaml
uv run scopehound check http://localhost:3000/api/users --scope scope.yaml
```

`check` não envia nada: só diz se a requisição passaria e para qual IP iria.

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
