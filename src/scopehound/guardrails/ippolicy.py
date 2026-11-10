"""Política de destino por IP (proteção contra SSRF e DNS rebinding).

O escopo valida *nomes*. Esta política valida para onde o nome realmente
aponta, depois da resolução DNS:

- `ALWAYS_DENIED`: metadados de nuvem, multicast, endereços reservados.
  Nunca liberados, nem pelo escopo.
- `hard_deny`: faixas definidas pelo operador do servidor (ex.: a rede do
  cluster). Nunca liberadas pelo escopo.
- `internal_deny`: redes internas (loopback, RFC 1918...). No modo servidor
  ficam bloqueadas, a menos que o escopo do projeto as liste em `allowed_cidrs`.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from dataclasses import dataclass

from .errors import EgressDenied
from .scope import IPAddress, Scope

Network = ipaddress.IPv4Network | ipaddress.IPv6Network

ALWAYS_DENIED: tuple[Network, ...] = tuple(
    ipaddress.ip_network(c)
    for c in (
        "0.0.0.0/8",
        "169.254.169.254/32",  # metadados AWS/GCP/Azure/OpenStack
        "169.254.170.2/32",  # credenciais de task do ECS
        "100.100.100.200/32",  # metadados Alibaba Cloud
        "224.0.0.0/4",
        "240.0.0.0/4",
        "::/128",
        "fd00:ec2::254/128",  # metadados AWS (IPv6)
        "ff00::/8",
    )
)

DEFAULT_INTERNAL: tuple[str, ...] = (
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
    "100.64.0.0/10",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
)

_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def canonical_ip(ip: IPAddress) -> IPAddress:
    """Extrai o IPv4 embutido em formas IPv6 (mapeado, NAT64, 6to4)."""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return ip.ipv4_mapped
        if ip in _NAT64:
            return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        if ip.sixtofour is not None:
            return ip.sixtofour
    return ip


def _networks(cidrs: Iterable[str]) -> tuple[Network, ...]:
    return tuple(ipaddress.ip_network(c, strict=False) for c in cidrs)


@dataclass(frozen=True)
class IpPolicy:
    hard_deny: tuple[Network, ...] = ()
    internal_deny: tuple[Network, ...] = ()

    @classmethod
    def build(cls, *, hard_deny: Iterable[str] = (), internal_deny: Iterable[str] = ()) -> IpPolicy:
        return cls(hard_deny=_networks(hard_deny), internal_deny=_networks(internal_deny))

    def check(self, ip: IPAddress, scope: Scope) -> None:
        candidates = {ip, canonical_ip(ip)}
        for candidate in candidates:
            for net in (*ALWAYS_DENIED, *self.hard_deny):
                if candidate in net:
                    raise EgressDenied(f"destino {ip} proibido ({net})")
            for net in self.internal_deny:
                if candidate in net and not any(candidate in a for a in scope.networks()):
                    raise EgressDenied(
                        f"destino {ip} está em rede interna ({net}); "
                        "liste a faixa em allowed_cidrs para autorizar"
                    )
