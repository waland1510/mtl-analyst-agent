import asyncio

import httpx
import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MTL_RUNS_DIR", str(tmp_path / "runs"))
    import importlib

    import mtl_analyst.api as api

    importlib.reload(api)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://t")


async def wait(client, run_id):
    for _ in range(100):
        payload = (await client.get(f"/runs/{run_id}")).json()
        if not payload["in_flight"] and payload["run"]["status"] != "Running":
            return payload["run"]
        await asyncio.sleep(0.05)
    raise AssertionError("run did not finish")


async def test_page_boroughs_and_a_background_run(client):
    async with client:
        assert "mtl-analyst-agent" in (await client.get("/")).text
        assert "Ville-Marie" in (await client.get("/boroughs")).json()
        started = await client.post("/scopes/city/runs", json={"question": "Which borough was the busiest in 2025?"})
        assert started.status_code == 202
        run = await wait(client, started.json()["id"])
        assert run["status"] == "Completed"
        assert run["kept"] and run["chart"]
        assert "paused_session" not in run


async def test_malformed_scope_is_a_bad_request(client):
    async with client:
        assert (await client.post("/scopes/x'%20or%201=1/runs", json={"question": "q"})).status_code == 400


async def test_approvals_over_http(client):
    async with client:
        started = await client.post(
            "/scopes/city/runs", json={"question": "How many trips in total? Then export it.", "allow_export": True}
        )
        run = await wait(client, started.json()["id"])
        assert run["status"] == "AwaitingApproval"
        approval = run["approvals"][0]["id"]
        assert (
            await client.post(f"/runs/{run['id']}/approvals/{approval}", json={"approved": True})
        ).status_code == 202
        run = await wait(client, run["id"])
        assert run["status"] == "Completed"
        assert (
            await client.post(f"/runs/{run['id']}/approvals/{approval}", json={"approved": True})
        ).status_code == 409
