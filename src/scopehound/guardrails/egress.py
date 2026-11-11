"""Egress: o único caminho de rede do scopehound.

Seguindo a lógica do Burp AT, o modelo só *pede* uma requisição; quem decide
e executa é esta camada, separada do modelo. Toda requisição passa por:

1. kill switch;
2. escopo (URL, porta, path, método) e cabeçalho Host;
3. resolução DNS e política de IP. A conexão é feita no IP validado (DNS
   pinning), com Host e SNI do nome original, para que uma segunda resolução
   não leve a outro lugar (DNS rebinding);
4. orçamento e rate limit;
5. envio sem seguir redirects, sem proxy do ambiente e com corpo limitado.

Cada decisão gera um `AuditEvent`, para o registro do projeto.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

import httpx

from ..i18n import t
from .budget import Budget
from .errors import EgressDenied, EgressNetworkError, GuardrailError, ScopeViolation
from .ippolicy import IpPolicy
from .killswitch import KillSwitch
from .ratelimit import RateLimiter
from .scope import IPAddress, Scope, Target, check_method, check_url

Resolver = Callable[[str, int], Awaitable[list[IPAddress]]]

REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
_CREDENTIAL_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization"})


async def system_resolver(host: str, port: int) -> list[IPAddress]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ips: list[IPAddress] = []
    for info in infos:
        ip = ipaddress.ip_address(str(info[4][0]).split("%", 1)[0])
        if ip not in ips:
            ips.append(ip)
    return ips


@dataclass(frozen=True)
class AuditEvent:
    kind: Literal["denied", "dry_run", "sent", "error"]
    method: str
    url: str
    detail: str = ""
    resolved_ip: str | None = None
    status: int | None = None


@dataclass(frozen=True)
class EgressResult:
    method: str
    url: str
    resolved_ip: str
    dry_run: bool
    status: int | None = None
    headers: httpx.Headers = field(default_factory=httpx.Headers)
    body: bytes = b""
    truncated: bool = False
    encoding: str | None = None
    elapsed_ms: float = 0.0

    @property
    def text(self) -> str:
        return self.body.decode(self.encoding or "utf-8", errors="replace")


@dataclass(frozen=True)
class RedirectChain:
    hops: list[EgressResult]
    blocked: GuardrailError | None = None
    exceeded: bool = False

    @property
    def final(self) -> EgressResult:
        return self.hops[-1]


class Egress:
    def __init__(
        self,
        scope: Scope,
        *,
        budget: Budget,
        ip_policy: IpPolicy | None = None,
        kill_switch: KillSwitch | None = None,
        rate_limiter: RateLimiter | None = None,
        resolver: Resolver = system_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
        verify_tls: bool = True,
        timeout: float = 15.0,
        max_response_bytes: int = 2_000_000,
        user_agent: str = "scopehound/0.1 (+authorized-testing)",
        dry_run: bool = False,
        audit: Callable[[AuditEvent], None] | None = None,
    ) -> None:
        self.scope = scope
        self.budget = budget
        self.ip_policy = ip_policy or IpPolicy()
        self.kill_switch = kill_switch or KillSwitch()
        self.rate_limiter = rate_limiter or RateLimiter(scope.max_requests_per_second)
        self.resolver = resolver
        self.max_response_bytes = max_response_bytes
        self.user_agent = user_agent
        self.dry_run = dry_run
        self._audit = audit
        # trust_env=False: um HTTP_PROXY no ambiente desviaria o tráfego e
        # anularia o pinning de IP.
        self._client = httpx.AsyncClient(
            transport=transport,
            verify=verify_tls,
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        )

    async def __aenter__(self) -> Egress:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    def _emit(self, event: AuditEvent) -> None:
        if self._audit is not None:
            self._audit(event)

    def _prepare_headers(self, target: Target, headers: Mapping[str, str] | None) -> dict[str, str]:
        prepared = {"User-Agent": self.user_agent}
        for name, value in (headers or {}).items():
            if name.lower() == "host":
                # Trocar o Host num IP permitido pode fazer um proxy reverso
                # encaminhar para um destino fora do escopo.
                if value.strip().lower() != target.host_header.lower():
                    raise ScopeViolation(
                        t(
                            f"cabeçalho Host '{value}' difere do alvo",
                            f"Host header '{value}' differs from the target",
                        )
                    )
                continue
            prepared[name] = value
        prepared["Host"] = target.host_header
        return prepared

    async def _resolve(self, target: Target) -> list[IPAddress]:
        if target.host_ip is not None:
            ips = [target.host_ip]
        else:
            try:
                ips = await self.resolver(target.host, target.port)
            except OSError as exc:
                raise EgressDenied(
                    t(
                        f"falha ao resolver {target.host}: {exc}",
                        f"failed to resolve {target.host}: {exc}",
                    )
                ) from exc
        if not ips:
            raise EgressDenied(
                t(
                    f"{target.host} não resolveu para nenhum IP",
                    f"{target.host} did not resolve to any IP",
                )
            )
        # Todos os IPs precisam passar: se só um passasse, a escolha do IP na
        # conexão decidiria se o bloqueio vale.
        for ip in ips:
            self.ip_policy.check(ip, self.scope)
        return ips

    async def send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        content: bytes | str | None = None,
    ) -> EgressResult:
        """Envia uma requisição, se todas as regras permitirem."""
        try:
            self.kill_switch.check()
            target = check_url(self.scope, url)
            method = check_method(self.scope, method)
            prepared = self._prepare_headers(target, headers)
            ips = await self._resolve(target)
        except GuardrailError as exc:
            self._emit(AuditEvent("denied", method.upper(), str(url), str(exc)))
            raise

        if self.dry_run:
            self._emit(AuditEvent("dry_run", method, str(url), resolved_ip=str(ips[0])))
            return EgressResult(method=method, url=str(url), resolved_ip=str(ips[0]), dry_run=True)

        try:
            self.budget.consume_request()
            await self.rate_limiter.acquire()
            self.kill_switch.check()
        except GuardrailError as exc:
            self._emit(AuditEvent("denied", method, str(url), str(exc)))
            raise

        extensions = {"sni_hostname": target.host} if target.scheme == "https" else {}
        started = time.perf_counter()
        last_error: httpx.HTTPError | None = None
        for ip in ips:
            request = self._client.build_request(
                method,
                target.url.copy_with(host=str(ip)),
                headers=prepared,
                content=content,
                extensions=extensions,
            )
            try:
                result = await self._exchange(request, method, str(url), str(ip), started)
            except httpx.ConnectError as exc:
                last_error = exc  # tenta o próximo IP (todos já validados)
                continue
            except httpx.HTTPError as exc:
                last_error = exc
                break
            self._emit(
                AuditEvent("sent", method, str(url), resolved_ip=str(ip), status=result.status)
            )
            return result

        self._emit(AuditEvent("error", method, str(url), str(last_error)))
        raise EgressNetworkError(f"{method} {url}: {last_error}") from last_error

    async def _exchange(
        self, request: httpx.Request, method: str, url: str, ip: str, started: float
    ) -> EgressResult:
        response = await self._client.send(request, stream=True)
        try:
            chunks: list[bytes] = []
            size = 0
            truncated = False
            async for chunk in response.aiter_bytes():
                room = self.max_response_bytes - size
                if len(chunk) > room:
                    chunks.append(chunk[:room])
                    truncated = True
                    break
                chunks.append(chunk)
                size += len(chunk)
        finally:
            await response.aclose()
        return EgressResult(
            method=method,
            url=url,
            resolved_ip=ip,
            dry_run=False,
            status=response.status_code,
            headers=response.headers,
            body=b"".join(chunks),
            truncated=truncated,
            encoding=response.charset_encoding,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )

    async def send_following_redirects(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        content: bytes | str | None = None,
        max_redirects: int = 5,
    ) -> RedirectChain:
        """Segue redirects manualmente, aplicando todas as regras a cada salto.

        Um salto bloqueado encerra a cadeia (`blocked`) sem levantar exceção,
        para que quem chama veja até onde chegou. Credenciais não são
        repassadas quando o host muda.
        """
        hops: list[EgressResult] = []
        current_method, current_url, current_content = method.upper(), url, content
        current_headers = dict(headers or {})
        origin_host = httpx.URL(url).host
        for _ in range(max_redirects + 1):
            try:
                result = await self.send(
                    current_method, current_url, headers=current_headers, content=current_content
                )
            except GuardrailError as exc:
                if not hops:
                    raise
                return RedirectChain(hops, blocked=exc)
            hops.append(result)
            location = result.headers.get("location")
            if result.dry_run or result.status not in REDIRECT_CODES or not location:
                return RedirectChain(hops)
            next_url = httpx.URL(current_url).join(location)
            if next_url.host != origin_host:
                current_headers = {
                    k: v for k, v in current_headers.items() if k.lower() not in _CREDENTIAL_HEADERS
                }
            if result.status == 303 or (result.status in (301, 302) and current_method == "POST"):
                current_method, current_content = "GET", None
            current_url = str(next_url)
        return RedirectChain(hops, exceeded=True)
