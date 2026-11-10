"""Autenticação e papéis.

- Modo local: sem autenticação (a API só escuta em 127.0.0.1).
- Modo servidor: cada requisição traz um Bearer JWT validado contra o JWKS do
  provedor OIDC. O papel do usuário por projeto decide o que ele pode fazer.

O verificador de token é injetável, para testes não dependerem de um provedor
real. A verificação de assinatura real usa PyJWT + JWKS.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

# papéis, do mais fraco ao mais forte
ROLES = ("viewer", "tester", "admin")
# o que cada rota exige
READ = "viewer"
ACT = "tester"
ADMIN = "admin"


@dataclass(frozen=True)
class Principal:
    subject: str
    email: str = ""
    role: str = "viewer"  # papel efetivo (do token/claims)

    def can(self, required: str) -> bool:
        return ROLES.index(self.role) >= ROLES.index(required)


LOCAL_PRINCIPAL = Principal(subject="local", email="local", role="admin")

TokenVerifier = Callable[[str], Awaitable[Principal]]


async def _reject(_: str) -> Principal:
    raise HTTPException(401, "autenticação não configurada")


class AuthContext:
    def __init__(self, *, mode: str, verifier: TokenVerifier | None = None) -> None:
        self.mode = mode
        self.verifier = verifier or _reject

    async def principal(self, request: Request) -> Principal:
        if self.mode == "local":
            return LOCAL_PRINCIPAL
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise HTTPException(401, "token Bearer ausente")
        return await self.verifier(header.split(" ", 1)[1].strip())


def require(context: AuthContext, level: str) -> Callable:
    async def dependency(request: Request) -> Principal:
        principal = await context.principal(request)
        if not principal.can(level):
            raise HTTPException(403, f"ação requer papel '{level}' (você é '{principal.role}')")
        return principal

    return Depends(dependency)


def build_oidc_verifier(issuer: str, audience: str, jwks_url: str) -> TokenVerifier:
    """Verificador real OIDC (PyJWT + JWKS). Importado só no modo servidor."""
    import jwt
    from jwt import PyJWKClient

    jwk_client = PyJWKClient(jwks_url)

    async def verify(token: str) -> Principal:
        try:
            signing_key = jwk_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "ES256"],
                audience=audience,
                issuer=issuer,
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(401, f"token inválido: {exc}") from exc
        role = claims.get("scopehound_role") or claims.get("role") or "viewer"
        if role not in ROLES:
            role = "viewer"
        return Principal(subject=claims.get("sub", "?"), email=claims.get("email", ""), role=role)

    return verify
