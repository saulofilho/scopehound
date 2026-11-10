"""Listener out-of-band (equivalente simplificado ao Collaborator).

Gera URLs únicas; quando o alvo as acessa (SSRF, XXE, injeção que faz
callback), o acesso é registrado e o agente consulta com oob_poll. É um
listener HTTP no próprio processo da API, exposto em /oob/{token}. DNS OOB
fica para depois.

O token não revela nada do projeto. Os hits guardam método, caminho, IP de
origem e um trecho dos cabeçalhos/corpo.
"""

from __future__ import annotations

import secrets
import time
from collections import defaultdict
from dataclasses import dataclass, field

TOKEN_BYTES = 12
MAX_HITS_PER_TOKEN = 50
MAX_BODY = 2000


@dataclass(frozen=True)
class OobHit:
    at: float
    method: str
    path: str
    source_ip: str
    headers: dict[str, str]
    body: str

    def to_json(self) -> dict:
        return {
            "at": self.at,
            "method": self.method,
            "path": self.path,
            "source_ip": self.source_ip,
            "headers": self.headers,
            "body": self.body,
        }


@dataclass
class OobRegistry:
    # token -> project_id (para isolar hits por projeto)
    tokens: dict[str, str] = field(default_factory=dict)
    hits: dict[str, list[OobHit]] = field(default_factory=lambda: defaultdict(list))

    def new_token(self, project_id: str) -> str:
        token = secrets.token_hex(TOKEN_BYTES)
        self.tokens[token] = project_id
        return token

    def record(self, token: str, hit: OobHit) -> bool:
        if token not in self.tokens:
            return False
        bucket = self.hits[token]
        if len(bucket) < MAX_HITS_PER_TOKEN:
            bucket.append(hit)
        return True

    def poll(self, token: str, project_id: str) -> list[OobHit] | None:
        if self.tokens.get(token) != project_id:
            return None
        return list(self.hits.get(token, []))


def make_hit(method: str, path: str, source_ip: str, headers: dict[str, str], body: str) -> OobHit:
    return OobHit(
        at=time.time(),
        method=method,
        path=path,
        source_ip=source_ip,
        headers={k: v for k, v in list(headers.items())[:20]},
        body=body[:MAX_BODY],
    )
