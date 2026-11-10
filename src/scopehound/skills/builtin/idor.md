---
name: idor
description: Testa acesso indevido a objetos de outro usuário trocando identificadores e sessões
tools: [site_map, search_traffic, get_request, replay_as, diff_responses, send_request]
---
# IDOR / Broken Object Level Authorization

Objetivo: verificar se um usuário consegue ler ou alterar objetos que
pertencem a outro, trocando identificadores ou a sessão.

## Pré-requisitos
- Pelo menos duas sessões de autenticação cadastradas (ex.: `userA`, `userB`).
  Sem isso, só dá para testar acesso anônimo a objeto de usuário.

## Passos
1. No `site_map`, procure endpoints com parâmetros marcados `#num` (IDs
   numéricos) em path, query ou corpo: são os candidatos mais diretos.
2. Pegue com `get_request` uma requisição autenticada que retorne um objeto do
   próprio usuário (ex.: `GET /api/basket/6` como `userA`).
3. Use `replay_as` para repetir essa requisição como `userB`. Compare com
   `diff_responses`:
   - mesma resposta (200 com os dados de A) → IDOR de leitura;
   - 403/404 → autorização provavelmente correta.
4. Teste também trocar só o ID mantendo a sessão (`6` → `7`, `8`), com
   `send_request`. E repita para métodos de escrita (PUT/PATCH/DELETE), que
   exigem aprovação.
5. Procure IDs não óbvios: em corpos JSON (`UserId`, `ownerId`), em cookies e
   em parâmetros de query.

## Sinais de achado
- `userB` obtém os dados de `userA` (status e corpo iguais ao acesso legítimo).
- Alterar o ID devolve objeto de outro dono.

## Falsos positivos
- Objeto realmente público (catálogo, post público).
- Resposta genérica igual para existente e inexistente (não confirma acesso).

Só registre como confirmado via `verify_finding`, com uma prova reproduzível
(status + trecho do corpo que é do outro usuário).
