from __future__ import annotations

import ipaddress

import pytest

from scopehound.guardrails import Scope


def make_scope(**overrides) -> Scope:
    base = {
        "allowed_hosts": ["localhost", "app.lab", "*.lab", "api.example.com"],
        "allowed_paths": ["/*"],
        "exclude_paths": ["/logout", "/admin/delete"],
        "max_requests_per_second": 1000,
        "authorized_by": "tester@example.com",
    }
    base.update(overrides)
    return Scope(**base)


def fixed_resolver(mapping: dict[str, list[str]]):
    async def resolve(host: str, port: int):
        if host not in mapping:
            raise OSError(f"NXDOMAIN {host}")
        return [ipaddress.ip_address(ip) for ip in mapping[host]]

    return resolve


@pytest.fixture
def scope() -> Scope:
    return make_scope()
