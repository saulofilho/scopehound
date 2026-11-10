import httpx
from conftest import LAB_SCOPE

from scopehound.api import create_app


async def test_static_ui_is_served(harness):
    async with harness.runtime() as rt:
        app = create_app(rt, manage_runtime=False)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as client:
            r = await client.get("/")
            assert r.status_code in (307, 308)
            assert r.headers["location"] == "/app/"
            page = await client.get("/app/")
            assert page.status_code == 200
            assert "scopehound" in page.text and 'src="app.js"' in page.text
            js = await client.get("/app/app.js")
            assert js.status_code == 200 and "EventSource" in js.text
            ctype = js.headers["content-type"]
            assert ctype.startswith(("text/javascript", "application/javascript"))
            css = await client.get("/app/styles.css")
            assert css.status_code == 200


async def test_ui_backing_endpoints(harness):
    """A UI só usa endpoints já existentes; confere que os principais respondem."""
    async with harness.runtime() as rt:
        app = create_app(rt, manage_runtime=False)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as client:
            created = await client.post("/projects", json={"name": "lab", "scope": LAB_SCOPE})
            pid = created.json()["id"]
            for path in (
                f"/projects/{pid}/sitemap",
                f"/projects/{pid}/traffic",
                f"/projects/{pid}/leads",
                f"/projects/{pid}/tools",
                f"/projects/{pid}/audit",
                "/skills",
            ):
                assert (await client.get(path)).status_code == 200
