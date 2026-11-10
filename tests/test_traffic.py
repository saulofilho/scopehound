import httpx
import pytest
from conftest import LAB_SCOPE
from langchain_core.messages import AIMessage
from mitmproxy.test import tflow, tutils
from traffic_fixtures import XXE, burp_xml, juice_har

from scopehound.agent.fake import tool_call
from scopehound.api import create_app
from scopehound.core import Conflict
from scopehound.core import service as svc
from scopehound.traffic import extract_params, path_template, render_sitemap
from scopehound.traffic.importers import parse_burp_xml, parse_har, parse_raw_http
from scopehound.traffic.proxy import CaptureAddon, flow_to_exchange


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/Users/12", "/api/Users/{id}"),
        ("/rest/basket/6/checkout", "/rest/basket/{id}/checkout"),
        ("/api/Users/a3f1c2d4-1111-2222-3333-444455556666", "/api/Users/{uuid}"),
        ("/files/9f86d081884c7d659a2feaa0c55ad015", "/files/{hash}"),
        ("/reset/AbCdEf0123456789xyzTOKEN", "/reset/{token}"),
        ("/api/Products", "/api/Products"),
        ("/", "/"),
    ],
)
def test_path_template(path, expected):
    assert path_template(path) == expected


def test_extract_params():
    params = extract_params(
        "http://a/x/7?page=2&q=apple",
        [("Content-Type", "application/json"), ("Cookie", "token=abc; lang=en")],
        '{"BasketId": "6", "item": {"ProductId": 1}, "tags": [{"id": 3}]}',
    )
    found = {(p.name, p.location, p.value) for p in params}
    assert ("{id}#2", "path", "7") in found
    assert ("page", "query", "2") in found
    assert ("BasketId", "json", "6") in found
    assert ("item.ProductId", "json", "1") in found
    assert ("tags.[].id", "json", "3") in found
    assert ("token", "cookie", "") in found


def test_parse_har_and_burp():
    har = parse_har(juice_har())
    assert len(har) == 10
    assert har[2].response_body == '{"id":24}'  # base64 decodificado
    assert har[-1].status is None  # status 0 = sem resposta
    burp = parse_burp_xml(burp_xml())
    assert burp[0].method == "GET" and burp[0].status == 200
    assert ("Authorization", "Bearer t") in burp[0].request_headers
    assert burp[0].response_body == '{"id":3,"role":"admin"}'
    assert burp[1].request_body == "UserId=3&rating=5" and burp[1].status is None


def test_raw_http_with_lf_only():
    line, headers, body = parse_raw_http(b"GET / HTTP/1.1\nHost: a\n\nbody")
    assert line == "GET / HTTP/1.1" and headers == [("Host", "a")] and body == "body"


async def test_import_filters_scope_and_builds_sitemap(harness):
    async with harness.runtime() as rt:
        project = await svc.create_project(rt, name="lab", scope=LAB_SCOPE)
        result = await svc.import_traffic(rt, project.id, juice_har(), filename="juice.har")
        assert (result.stored, result.skipped_out_of_scope) == (8, 2)
        result = await svc.import_traffic(rt, project.id, burp_xml(), filename="burp.xml")
        assert result.stored == 2

        site = await svc.sitemap(rt, project.id)
        [origin] = site
        endpoints = {(e.method, e.template): e for e in site[origin]}
        products = endpoints[("GET", "/api/Products/{id}")]
        assert products.count == 2
        assert {p.name: p.numeric for p in products.numeric_params} == {"{id}#3": True}
        basket_items = endpoints[("POST", "/api/BasketItems")]
        numeric = {p.name for p in basket_items.numeric_params}
        assert numeric == {"ProductId", "BasketId", "quantity"}
        feedback = endpoints[("POST", "/api/Feedbacks")]
        assert {p.name for p in feedback.numeric_params} == {"UserId", "rating"}
        login = endpoints[("POST", "/rest/user/login")]
        assert login.numeric_params == []
        assert ("GET", "/api/Users/{uuid}") in endpoints
        text = render_sitemap(site)
        assert "/api/Users/{id}" in text and "BasketId[json#num]" in text

        rows = await svc.search_traffic(rt, project.id, param="BasketId")
        assert [r.path for r in rows] == ["/api/BasketItems"]
        rows = await svc.search_traffic(rt, project.id, text="role")
        assert [r.path for r in rows] == ["/api/Users/3"]
        assert await svc.search_traffic(rt, project.id, text="%") == []
        row = await svc.get_exchange(rt, project.id, rows[0].id[:10])
        assert row.status == 200


async def test_xxe_rejected(harness):
    async with harness.runtime() as rt:
        project = await svc.create_project(rt, name="lab", scope=LAB_SCOPE)
        with pytest.raises(Conflict):
            await svc.import_traffic(rt, project.id, XXE, filename="evil.xml")


async def test_acceptance_agent_answers_from_project_data(harness):
    """Critério de pronto da Fase 2: o agente responde quais endpoints recebem
    IDs numéricos usando só os dados do projeto (sem enviar requisições)."""
    harness.model.script = [
        tool_call("site_map", {}, "c1"),
        tool_call("search_traffic", {"param": "BasketId"}, "c2"),
        lambda msgs: AIMessage("Endpoints com IDs numéricos: /api/Products/{id}, ..."),
    ]
    async with harness.runtime() as rt:
        project = await svc.create_project(rt, name="lab", scope=LAB_SCOPE)
        await svc.import_traffic(rt, project.id, juice_har(), filename="juice.har")
        task = await svc.create_task(
            rt, project.id, prompt="quais endpoints recebem IDs numéricos?", wait=True
        )
        assert task.status == "idle" and task.requests_used == 0
        assert harness.target.requests == []
        tool_outputs = [m for m in harness.model.calls[-1] if m.type == "tool"]
        sitemap_text, search_text = tool_outputs[0].content, tool_outputs[1].content
        for expected in (
            "/api/Products/{id}",
            "/rest/basket/{id}",
            "BasketId[json#num]",
            "ProductId[json#num]",
        ):
            assert expected in sitemap_text
        assert "/api/BasketItems" in search_text
        actions = [(a.tool, a.outcome) for a in await svc.list_actions(rt, task.id)]
        assert actions == [("site_map", "executed"), ("search_traffic", "executed")]


async def test_agent_requests_are_recorded_and_diffable(harness):
    def diff_step(msgs):
        ids = [m.content.split("[troca ")[1][:12] for m in msgs if m.type == "tool"]
        return tool_call("diff_responses", {"id_a": ids[0], "id_b": ids[1]}, "c3")

    harness.model.script = [
        tool_call("send_request", {"url": "http://app.lab/api/users/2"}, "c1"),
        tool_call("send_request", {"url": "http://app.lab/api/users/3"}, "c2"),
        diff_step,
        AIMessage("fim"),
    ]
    async with harness.runtime() as rt:
        project = await svc.create_project(rt, name="lab", scope=LAB_SCOPE)
        task = await svc.create_task(rt, project.id, prompt="x", wait=True)
        rows = await svc.search_traffic(rt, project.id, source="agent")
        assert len(rows) == 2 and all(r.task_id == task.id for r in rows)
        diff = harness.model.calls[-1][-1].content
        assert "status 200 → 200" in diff and "outro@lab" in diff


async def test_proxy_addon_posts_to_api(harness):
    async with harness.runtime() as rt:
        project = await svc.create_project(rt, name="lab", scope=LAB_SCOPE)
        app = create_app(rt, manage_runtime=False)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        addon = CaptureAddon("http://t", project.id, batch_size=2, client=client)

        def flow(url):
            f = tflow.tflow(resp=tutils.tresp(content=b'{"ok":1}'))
            f.request.url = url
            return f

        await addon.response(flow("http://app.lab/api/Quantitys/7"))
        await addon.response(flow("http://evil.com/ads"))
        await addon.done()
        assert (addon.stored, addon.skipped) == (1, 1)
        [row] = await svc.search_traffic(rt, project.id, source="proxy")
        assert row.path == "/api/Quantitys/7" and row.response_body == '{"ok":1}'


def test_flow_to_exchange_skips_connect():
    f = tflow.tflow()
    f.request.method = "CONNECT"
    assert flow_to_exchange(f) is None


async def test_traffic_api_routes(harness):
    async with harness.runtime() as rt:
        app = create_app(rt, manage_runtime=False)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as client:
            pid = (await client.post("/projects", json={"name": "lab", "scope": LAB_SCOPE})).json()[
                "id"
            ]
            r = await client.post(
                f"/projects/{pid}/traffic/import?filename=b.xml", content=burp_xml()
            )
            assert r.json() == {"stored": 2, "skipped_out_of_scope": 0}
            listing = (await client.get(f"/projects/{pid}/traffic")).json()
            assert len(listing) == 2 and "response_body" not in listing[0]
            one = (await client.get(f"/projects/{pid}/traffic/{listing[0]['id']}")).json()
            assert "response_body" in one
            site = (await client.get(f"/projects/{pid}/sitemap")).json()
            assert [e["path"] for e in site["http://app.lab"]] == [
                "/api/Feedbacks",
                "/api/Users/{id}",
            ]
            r = await client.post(
                f"/projects/{pid}/traffic", json={"exchanges": [], "source": "agent"}
            )
            assert r.status_code == 422
            r = await client.post(f"/projects/{pid}/traffic/import?filename=x.xml", content=XXE)
            assert r.status_code == 409
