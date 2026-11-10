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


# ---- Fase 1: runtime com LLM roteirizado e rede simulada -------------------
import httpx  # noqa: E402

from scopehound.agent.fake import ScriptedChatModel  # noqa: E402
from scopehound.config import Settings  # noqa: E402
from scopehound.core import Runtime  # noqa: E402

PUBLIC_IP = "93.184.215.14"


class FakeTarget:
    """Alvo simulado: registra as requisições recebidas."""

    def __init__(self, handler=None):
        self.requests: list[httpx.Request] = []
        self.handler = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.handler is not None:
            return self.handler(request)
        if request.url.path == "/api/users/2":
            return httpx.Response(200, json={"id": 2, "email": "outro@lab"})
        return httpx.Response(200, text="ok")


def make_settings(tmp_path, **overrides) -> Settings:
    base = {
        "data_dir": tmp_path / "data",
        "llm_provider": "fake",
        "llm_base_url": "",
        "llm_model": "scripted",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


class Harness:
    def __init__(self, tmp_path, **settings):
        self.tmp_path = tmp_path
        self.settings = make_settings(tmp_path, **settings)
        self.target = FakeTarget()
        self.model = ScriptedChatModel()

    def runtime(self) -> Runtime:
        return Runtime(
            self.settings,
            llm_factory=lambda cfg: self.model,
            transport=httpx.MockTransport(self.target),
            resolver=fixed_resolver({"app.lab": [PUBLIC_IP]}),
        )


@pytest.fixture
def harness(tmp_path) -> Harness:
    return Harness(tmp_path)


LAB_SCOPE = {
    "allowed_hosts": ["app.lab"],
    "exclude_paths": ["/logout"],
    "max_requests_per_second": 1000,
    "authorized_by": "tester@example.com",
    "authorization_ref": "LAB-1",
}
