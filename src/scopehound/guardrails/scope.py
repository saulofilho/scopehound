"""Escopo autorizado e validação de URLs.

O escopo é o contrato de autorização de um projeto. `check_url` é chamado
antes de qualquer I/O e falha fechado: em caso de dúvida, bloqueia.

A validação usa o mesmo parser de URL (httpx) que envia a requisição, para
evitar divergência entre o que foi checado e o que sai pela rede.
"""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Literal
from urllib.parse import unquote

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .errors import ScopeViolation

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# Sufixos de um rótulo que podem receber curinga (*.lab). Qualquer outro
# curinga precisa de pelo menos dois rótulos (*.empresa.com), para evitar
# escopos como *.com.
DEV_SUFFIXES = frozenset(
    {"localhost", "test", "lab", "local", "internal", "lan", "example", "invalid"}
)
HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"})
DEFAULT_METHODS = ["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH"]
DEFAULT_PORTS = {"http": 80, "https": 443}
MAX_URL_LENGTH = 8192

_LABEL = re.compile(r"^[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?$")
_PERCENT_ESCAPE = re.compile(r"%[0-9a-fA-F]{2}")
_FORBIDDEN_URL_CHARS = re.compile(r"[\s\\\x00-\x1f\x7f]")


def _normalize_host(host: str) -> str:
    return host.strip().lower().rstrip(".")


def _parse_ip(value: str) -> IPAddress | None:
    try:
        return ipaddress.ip_address(value.strip("[]"))
    except ValueError:
        return None


class Scope(BaseModel):
    """Contrato de autorização de um projeto."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_hosts: list[str] = Field(default_factory=list)
    allowed_cidrs: list[str] = Field(default_factory=list)
    allowed_ports: list[int] | None = None
    allowed_schemes: list[Literal["http", "https"]] = Field(
        default_factory=lambda: ["http", "https"]
    )
    allowed_paths: list[str] = Field(default_factory=lambda: ["/*"])
    exclude_paths: list[str] = Field(default_factory=list)
    allowed_methods: list[str] = Field(default_factory=lambda: list(DEFAULT_METHODS))
    max_requests_per_second: float = Field(default=5.0, gt=0, le=1000)
    authorized_by: str = Field(min_length=1)
    authorization_ref: str = ""

    @field_validator("authorized_by")
    @classmethod
    def _authorized_by(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("authorized_by é obrigatório")
        return v.strip()

    @field_validator("allowed_hosts")
    @classmethod
    def _hosts(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for raw in v:
            host = _normalize_host(raw)
            ip = _parse_ip(host)
            if ip is not None:
                out.append(str(ip))
                continue
            if host.startswith("*."):
                suffix = host[2:]
                labels = suffix.split(".")
                if len(labels) < 2 and suffix not in DEV_SUFFIXES:
                    raise ValueError(f"curinga amplo demais: {raw!r}")
            else:
                suffix = host
            labels = suffix.split(".")
            if not suffix or not all(_LABEL.match(label) for label in labels):
                raise ValueError(f"host inválido: {raw!r} (curinga só no formato '*.dominio')")
            out.append(host)
        return out

    @field_validator("allowed_cidrs")
    @classmethod
    def _cidrs(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for raw in v:
            net = ipaddress.ip_network(raw, strict=False)
            minimum = 8 if net.version == 4 else 32
            if net.prefixlen < minimum:
                raise ValueError(f"faixa ampla demais: {raw!r} (mínimo /{minimum})")
            out.append(str(net))
        return out

    @field_validator("allowed_ports")
    @classmethod
    def _ports(cls, v: list[int] | None) -> list[int] | None:
        if v is not None and any(not 1 <= p <= 65535 for p in v):
            raise ValueError("porta fora de 1-65535")
        return v

    @field_validator("allowed_paths", "exclude_paths")
    @classmethod
    def _paths(cls, v: list[str]) -> list[str]:
        for p in v:
            if not p.startswith("/"):
                raise ValueError(f"path precisa começar com '/': {p!r}")
        return v

    @field_validator("allowed_methods")
    @classmethod
    def _methods(cls, v: list[str]) -> list[str]:
        out = [m.upper() for m in v]
        unknown = set(out) - HTTP_METHODS
        if unknown:
            raise ValueError(f"métodos não suportados: {sorted(unknown)}")
        return out

    def networks(self) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        return [ipaddress.ip_network(c) for c in self.allowed_cidrs]


@dataclass(frozen=True)
class Target:
    """URL já validada contra o escopo."""

    url: httpx.URL
    scheme: str
    host: str
    port: int
    path: str
    host_ip: IPAddress | None

    @property
    def host_header(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        if self.port == DEFAULT_PORTS[self.scheme]:
            return host
        return f"{host}:{self.port}"


def normalize_path(raw_path: str) -> str:
    """Normaliza o path para comparação com as regras do escopo.

    Decodifica %XX uma vez, remove parâmetros de matriz (`;jsessionid=...`),
    resolve `.`/`..` e colapsa barras. Codificação dupla e `..` acima da raiz
    são rejeitados, porque servidores diferentes interpretam isso de formas
    diferentes.
    """
    path = raw_path.split("?", 1)[0].split("#", 1)[0] or "/"
    decoded = unquote(path, errors="replace")
    if _PERCENT_ESCAPE.search(decoded):
        raise ScopeViolation(f"codificação dupla no path: {raw_path!r}")
    if _FORBIDDEN_URL_CHARS.search(decoded):
        raise ScopeViolation(f"caractere proibido no path: {raw_path!r}")
    segments: list[str] = []
    for raw_segment in decoded.split("/"):
        segment = raw_segment.split(";", 1)[0]
        if segment in ("", "."):
            continue
        if segment == "..":
            if not segments:
                raise ScopeViolation(f"path sobe acima da raiz: {raw_path!r}")
            segments.pop()
            continue
        segments.append(segment)
    normalized = "/" + "/".join(segments)
    if segments and decoded.endswith("/"):
        normalized += "/"
    return normalized


def _host_allowed(scope: Scope, host: str, ip: IPAddress | None) -> bool:
    if ip is not None:
        return str(ip) in scope.allowed_hosts or any(ip in net for net in scope.networks())
    for pattern in scope.allowed_hosts:
        if pattern.startswith("*."):
            if host.endswith(pattern[1:]):
                return True
        elif host == pattern:
            return True
    return False


def _excluded_by(path: str, patterns: list[str]) -> str | None:
    lowered = path.lower()
    trimmed = lowered.rstrip("/") or "/"
    for pattern in patterns:
        p = pattern.lower().rstrip("/") or "/"
        if (
            fnmatchcase(lowered, p)
            or fnmatchcase(trimmed, p)
            or fnmatchcase(lowered, p.rstrip("/") + "/*")
        ):
            return pattern
    return None


def check_url(scope: Scope, url: str | httpx.URL) -> Target:
    """Valida a URL contra o escopo. Levanta `ScopeViolation` se não passar."""
    text = str(url)
    if len(text) > MAX_URL_LENGTH:
        raise ScopeViolation("URL longa demais")
    if _FORBIDDEN_URL_CHARS.search(text):
        raise ScopeViolation(f"caractere proibido na URL: {text!r}")
    try:
        parsed = httpx.URL(text)
    except httpx.InvalidURL as exc:
        raise ScopeViolation(f"URL inválida: {exc}") from exc

    scheme = parsed.scheme.lower()
    if scheme not in scope.allowed_schemes:
        raise ScopeViolation(f"esquema '{scheme}' fora do escopo")
    if parsed.userinfo:
        raise ScopeViolation("URL com credenciais embutidas (user@host) não é permitida")

    host = _normalize_host(parsed.raw_host.decode("ascii"))
    if not host:
        raise ScopeViolation(f"URL sem host: {text!r}")
    ip = _parse_ip(host)
    if ip is not None:
        host = str(ip)
    if not _host_allowed(scope, host, ip):
        raise ScopeViolation(f"host '{host}' fora do escopo autorizado")

    port = parsed.port or DEFAULT_PORTS[scheme]
    if scope.allowed_ports is not None and port not in scope.allowed_ports:
        raise ScopeViolation(f"porta {port} fora do escopo")

    path = normalize_path(parsed.raw_path.decode("ascii"))
    if not any(fnmatchcase(path, p) for p in scope.allowed_paths):
        raise ScopeViolation(f"path '{path}' fora do escopo autorizado")
    excluded = _excluded_by(path, scope.exclude_paths)
    if excluded:
        raise ScopeViolation(f"path '{path}' explicitamente excluído ({excluded})")

    return Target(url=parsed, scheme=scheme, host=host, port=port, path=path, host_ip=ip)


def check_method(scope: Scope, method: str) -> str:
    normalized = method.upper()
    if normalized not in scope.allowed_methods:
        raise ScopeViolation(f"método '{normalized}' não permitido no escopo")
    return normalized


def load_scope(path: Path) -> Scope:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    return Scope.model_validate(data)
