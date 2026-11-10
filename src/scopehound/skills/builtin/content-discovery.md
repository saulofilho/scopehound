---
name: content-discovery
description: Encontra endpoints, arquivos e áreas não lincadas a partir do que já se conhece do alvo
tools: [site_map, search_traffic, get_request, content_discovery, send_request]
---
# Content discovery

Objetivo: ampliar a superfície conhecida do alvo encontrando caminhos que não
aparecem na navegação normal.

## Passos
1. Comece pelo `site_map`. Veja os prefixos já conhecidos (`/api`, `/rest`,
   `/admin`) e os padrões de nomes. Eles guiam onde vale procurar.
2. Rode `content_discovery` a partir das bases mais promissoras, não da raiz
   só. Teste também extensões coerentes com a stack observada
   (`.json`, `.bak`, `.old`) quando houver sinal dela.
3. Para cada caminho interessante, use `get_request`/`send_request` para
   confirmar: 200 com corpo útil, 401/403 (existe mas protegido), 500
   (comportamento inesperado). Trate 404 e 400 como ruído.
4. Priorize: painéis administrativos, documentação de API (`swagger`,
   `openapi.json`), endpoints de saúde/métricas que vazam versões, backups
   e arquivos de configuração.

## Sinais de achado
- Diretório ou arquivo acessível que não deveria ser público.
- Documentação de API que revela endpoints não mapeados.
- Diferença de status entre caminhos existentes e inexistentes (enumeração).

## Falsos positivos
- Páginas que respondem 200 para qualquer caminho (SPA com catch-all): compare
  o corpo com o de um caminho aleatório antes de registrar.
- Soft-404 (200 com página de "não encontrado").

Registre cada caminho relevante com `save_lead` (severidade pela sensibilidade
do que foi exposto). Confirme com `verify_finding` quando o acesso indevido
for reproduzível.
