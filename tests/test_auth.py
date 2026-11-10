import httpx
from conftest import LAB_SCOPE

from scopehound.api import create_app
from scopehound.api.auth import AuthContext, Principal


def server_auth(role):
    async def verifier(token):
        if token != "valid":
            from fastapi import HTTPException

            raise HTTPException(401, "token inválido")
        return Principal(subject="u1", email="u@x", role=role)

    return AuthContext(mode="server", verifier=verifier)


async def client_for(rt, role):
    app = create_app(rt, manage_runtime=False, auth=server_auth(role))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_local_mode_needs_no_token(harness):
    async with harness.runtime() as rt:
        app = create_app(rt, manage_runtime=False)  # local
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as c:
            assert (
                await c.post("/projects", json={"name": "a", "scope": LAB_SCOPE})
            ).status_code == 201


async def test_server_mode_rejects_without_token(harness):
    async with harness.runtime() as rt, await client_for(rt, "admin") as c:
        assert (await c.get("/projects")).status_code == 401
        r = await c.get("/projects", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401


async def test_roles(harness):
    async with harness.runtime() as rt:
        auth = {"Authorization": "Bearer valid"}
        # viewer: lê, mas não cria
        async with await client_for(rt, "viewer") as c:
            assert (await c.get("/projects", headers=auth)).status_code == 200
            assert (
                await c.post("/projects", json={"name": "a", "scope": LAB_SCOPE}, headers=auth)
            ).status_code == 403
        # tester: cria tarefa, mas não muda config (admin)
        async with await client_for(rt, "tester") as c:
            pid = (
                await c.post("/projects", json={"name": "b", "scope": LAB_SCOPE}, headers=auth)
            ).json()
            # criar projeto é ACT (tester pode)
            assert "id" in pid
            r = await c.put(f"/projects/{pid['id']}/llm", json={"model": "x"}, headers=auth)
            assert r.status_code == 403  # mudar LLM é admin
        # admin: tudo
        async with await client_for(rt, "admin") as c:
            pid = (
                await c.post("/projects", json={"name": "c", "scope": LAB_SCOPE}, headers=auth)
            ).json()["id"]
            assert (
                await c.put(f"/projects/{pid}/llm", json={"model": "x"}, headers=auth)
            ).status_code == 200


async def test_oob_and_health_are_open_in_server_mode(harness):
    async with harness.runtime() as rt:
        token = rt.oob.new_token("p")
        async with await client_for(rt, "viewer") as c:
            assert (await c.get("/health")).status_code == 200
            assert (await c.get(f"/oob/{token}")).status_code == 200


def test_principal_can():
    assert Principal(subject="x", role="admin").can("tester")
    assert not Principal(subject="x", role="viewer").can("tester")
