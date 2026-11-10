import http.server
import threading

import httpx
import pytest
from conftest import fixed_resolver, make_scope

from scopehound.guardrails import (
    DEFAULT_INTERNAL,
    Budget,
    BudgetExhausted,
    Egress,
    EgressDenied,
    IpPolicy,
    KillSwitch,
    KillSwitchTripped,
    ScopeViolation,
)

PUBLIC = "93.184.215.14"


class Recorder:
    def __init__(self, handler=None):
        self.requests: list[httpx.Request] = []
        self.handler = handler or (lambda r: httpx.Response(200, text="ok"))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)


def make_egress(recorder, *, resolver=None, scope=None, budget=None, **kw):
    events = []
    egress = Egress(
        scope or make_scope(),
        budget=budget or Budget(max_steps=10, max_requests=10, max_tokens=10),
        resolver=resolver or fixed_resolver({"app.lab": [PUBLIC], "api.example.com": [PUBLIC]}),
        transport=httpx.MockTransport(recorder),
        audit=events.append,
        **kw,
    )
    return egress, events


async def test_connects_to_pinned_ip_with_original_host_and_sni():
    rec = Recorder()
    egress, events = make_egress(rec)
    res = await egress.send("GET", "https://app.lab:8443/api?q=1")
    sent = rec.requests[0]
    assert sent.url.host == PUBLIC
    assert sent.url.port == 8443
    assert sent.headers["host"] == "app.lab:8443"
    assert sent.extensions["sni_hostname"] == "app.lab"
    assert res.status == 200 and res.text == "ok" and res.resolved_ip == PUBLIC
    assert [e.kind for e in events] == ["sent"]


async def test_dns_rebinding_to_metadata_is_blocked():
    rec = Recorder()
    egress, events = make_egress(rec, resolver=fixed_resolver({"app.lab": ["169.254.169.254"]}))
    with pytest.raises(EgressDenied):
        await egress.send("GET", "http://app.lab/")
    assert rec.requests == []
    assert events[0].kind == "denied"


async def test_any_bad_ip_blocks_request():
    rec = Recorder()
    egress, _ = make_egress(
        rec,
        resolver=fixed_resolver({"app.lab": [PUBLIC, "10.0.0.1"]}),
        ip_policy=IpPolicy.build(internal_deny=DEFAULT_INTERNAL),
    )
    with pytest.raises(EgressDenied):
        await egress.send("GET", "http://app.lab/")
    assert rec.requests == []


async def test_server_mode_blocks_localhost():
    egress, _ = make_egress(
        Recorder(),
        resolver=fixed_resolver({"localhost": ["127.0.0.1"]}),
        ip_policy=IpPolicy.build(internal_deny=DEFAULT_INTERNAL),
    )
    with pytest.raises(EgressDenied):
        await egress.send("GET", "http://localhost/")


async def test_unresolvable_host_denied():
    egress, _ = make_egress(Recorder())
    with pytest.raises(EgressDenied):
        await egress.send("GET", "http://other.lab/")


async def test_host_header_override_rejected():
    rec = Recorder()
    egress, _ = make_egress(rec)
    with pytest.raises(ScopeViolation):
        await egress.send("GET", "http://app.lab/", headers={"Host": "internal.admin"})
    await egress.send("GET", "http://app.lab/", headers={"host": "APP.LAB"})
    assert rec.requests[0].headers["host"] == "app.lab"


async def test_out_of_scope_and_method_blocked_before_io():
    rec = Recorder()
    egress, _ = make_egress(rec)
    with pytest.raises(ScopeViolation):
        await egress.send("GET", "http://evil.com/")
    with pytest.raises(ScopeViolation):
        await egress.send("DELETE", "http://app.lab/")
    assert rec.requests == []


async def test_budget_charged_and_enforced():
    rec = Recorder()
    budget = Budget(max_steps=1, max_requests=2, max_tokens=1)
    egress, events = make_egress(rec, budget=budget)
    await egress.send("GET", "http://app.lab/")
    await egress.send("GET", "http://app.lab/")
    with pytest.raises(BudgetExhausted):
        await egress.send("GET", "http://app.lab/")
    assert len(rec.requests) == 2
    assert events[-1].kind == "denied"


async def test_kill_switch_stops_traffic():
    rec = Recorder()
    ks = KillSwitch()
    egress, _ = make_egress(rec, kill_switch=ks)
    ks.trip("teste")
    with pytest.raises(KillSwitchTripped):
        await egress.send("GET", "http://app.lab/")
    assert rec.requests == []


async def test_dry_run_sends_nothing_and_costs_nothing():
    rec = Recorder()
    budget = Budget(max_steps=1, max_requests=1, max_tokens=1)
    egress, events = make_egress(rec, budget=budget, dry_run=True)
    res = await egress.send("POST", "http://app.lab/", content=b"x")
    assert res.dry_run and res.status is None
    assert rec.requests == [] and budget.requests == 0
    assert events[0].kind == "dry_run"


async def test_response_body_capped():
    egress, _ = make_egress(
        Recorder(lambda r: httpx.Response(200, content=b"A" * 5000)), max_response_bytes=1000
    )
    res = await egress.send("GET", "http://app.lab/")
    assert len(res.body) == 1000 and res.truncated


async def test_redirect_out_of_scope_is_blocked():
    def handler(request):
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data"})

    rec = Recorder(handler)
    egress, _ = make_egress(rec)
    chain = await egress.send_following_redirects("GET", "http://app.lab/")
    assert len(chain.hops) == 1
    assert isinstance(chain.blocked, ScopeViolation)
    assert len(rec.requests) == 1


async def test_redirect_in_scope_followed_with_rules_per_hop():
    def handler(request):
        if request.url.path == "/login":
            return httpx.Response(303, headers={"Location": "http://api.example.com/home"})
        return httpx.Response(200, text="home")

    rec = Recorder(handler)
    egress, _ = make_egress(rec)
    chain = await egress.send_following_redirects(
        "POST", "http://app.lab/login", headers={"Cookie": "s=1"}, content=b"u=a"
    )
    assert chain.final.text == "home" and chain.blocked is None
    second = rec.requests[1]
    assert second.method == "GET"
    assert second.headers["host"] == "api.example.com"
    assert "cookie" not in second.headers  # credencial não segue para outro host


async def test_redirect_loop_stops():
    rec = Recorder(lambda r: httpx.Response(302, headers={"Location": "/again"}))
    egress, _ = make_egress(rec)
    chain = await egress.send_following_redirects("GET", "http://app.lab/", max_redirects=3)
    assert chain.exceeded and len(rec.requests) == 4


# Integração real: servidor HTTP local, resolução DNS do sistema ------------
class _Handler(http.server.BaseHTTPRequestHandler):
    seen_hosts: list[str] = []

    def do_GET(self):
        _Handler.seen_hosts.append(self.headers["Host"])
        body = b"hello"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def local_server():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()


async def test_real_request_ignores_proxy_env(local_server, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    async with Egress(make_scope(), budget=Budget(1, 1, 1)) as egress:
        res = await egress.send("GET", f"http://localhost:{local_server}/x")
    assert res.status == 200 and res.text == "hello"
    assert res.resolved_ip == "127.0.0.1"
    assert _Handler.seen_hosts[-1] == f"localhost:{local_server}"
