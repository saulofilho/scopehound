---
name: race-condition
description: Testa condições de corrida (limit overrun) enviando requisições concorrentes
tools: [site_map, search_traffic, get_request, race_request, send_request]
---
# Condição de corrida (limit overrun)

Objetivo: verificar se uma operação que deveria ter limite pode ser excedida
enviando várias requisições ao mesmo tempo, antes de o estado ser atualizado.

## Onde procurar
- Resgatar cupom/voucher uma vez só.
- Debitar saldo, estornar, transferir.
- Aplicar desconto, aumentar quantidade de item.
- Qualquer verificação do tipo "só pode uma vez" / "só se houver saldo".

## Passos
1. No `site_map`/`search_traffic`, identifique a ação com limite e capture uma
   requisição válida dela com `get_request`.
2. Garanta o pré-requisito (ex.: um cupom ainda não usado, saldo disponível).
3. Use `race_request` com a mesma requisição e `count` moderado (10–20) para
   dispará-las em paralelo. (É intrusive: pede aprovação.)
4. Analise: se mais de uma requisição "venceu" (status de sucesso repetido,
   respostas divergentes), há indício de corrida.
5. Confirme o efeito no estado: consulte o saldo/contador depois com
   `send_request` e veja se passou do limite.

## Sinais de achado
- Mais de um sucesso onde só deveria haver um.
- Saldo/contador final inconsistente com o limite.
- Respostas de tamanhos ou status diferentes entre as concorrentes.

## Cuidados
- Isto altera o estado do alvo. Só em ambiente autorizado e, de preferência,
  com dados descartáveis. Nunca em produção sem autorização explícita.
- Não aumente `count` para valores altos: o objetivo é provar o defeito, não
  sobrecarregar o alvo.

Registre com `save_lead` e confirme o efeito com uma consulta posterior.
