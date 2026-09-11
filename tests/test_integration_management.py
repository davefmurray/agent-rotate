import json
import plistlib
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp import web

from agent_rotate.dashboard import snapshot
from agent_rotate.launcher import run
from agent_rotate.service import manage


async def test_http_failover_cannot_escape_pool(store, router_factory, aiohttp_server):
    for name in ("one", "two", "outside"):
        store.add("codex", name, "/fake/" + name)
    store.set_pool("codex", "work", ["one", "two"])
    calls = []

    async def handle(request):
        calls.append(request.headers["Authorization"])
        return web.Response(status=429, headers={"Retry-After": "20"})

    app = web.Application()
    app.router.add_post("/responses", handle)
    upstream = await aiohttp_server(app)
    router = await router_factory("codex", upstream.make_url(""), pool="work", strategy="ordered")
    async with aiohttp.ClientSession() as client:
        async with client.post(
            router.url + "/responses",
            json={"model": "m"},
            headers={"x-agent-rotate-key": router.key},
        ) as response:
            assert response.status == 429
    assert calls == ["Bearer test-token-one", "Bearer test-token-two"]
    data = snapshot(store, session=router.session_id)
    assert data["current_session"]["reason"] == "exhausted"
    assert router.key not in json.dumps(data)
    assert "test-token" not in json.dumps(data)


async def test_rejected_refresh_is_quarantined_without_replaying_same_request(
    store, router_factory, aiohttp_server
):
    store.add("codex", "one", "/fake/one")
    calls = 0

    async def handle(request):
        nonlocal calls
        calls += 1
        return web.Response(status=401)

    app = web.Application()
    app.router.add_post("/responses", handle)
    upstream = await aiohttp_server(app)
    router = await router_factory("codex", upstream.make_url(""))
    async with aiohttp.ClientSession() as client:
        async with client.post(
            router.url + "/responses", json={}, headers={"x-agent-rotate-key": router.key}
        ) as response:
            assert response.status == 401
    assert calls == 2
    assert store.health(store.accounts()[0])["state"] == "relogin_required"


async def test_codex_directory_flag_resolves_mapping_before_launch(store, tmp_path):
    store.add("codex", "one", "/fake/one")
    store.set_pool("codex", "work", ["one"])
    target = tmp_path / "sub"
    target.mkdir()
    store.map_pool("codex", "work", target)
    store.remove_pool("codex", "work")
    # A launch with -C must see the removed mapping, never widen to all accounts.
    with pytest.raises(ValueError, match="pool"):
        await run(store, "codex", ["-C", "sub"], cwd=tmp_path)


def test_service_uses_own_files_and_safe_arguments_only(store, monkeypatch, tmp_path):
    monkeypatch.setattr("agent_rotate.service.sys.platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        "agent_rotate.service.shutil.which", lambda _: "/app with spaces/agent-rotate"
    )
    calls = []

    def call(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("agent_rotate.service.subprocess.run", call)
    result = manage(store, "install", "daemon")
    data = plistlib.loads(Path(result["path"]).read_bytes())
    assert data["ProgramArguments"] == ["/app with spaces/agent-rotate", "daemon"]
    assert data["EnvironmentVariables"]["AGENT_ROTATE_HOME"] == str(store.root)
    assert data["StandardOutPath"] == "/dev/null"
    assert all(args[0] == "launchctl" for args in calls)
    manage(store, "remove", "daemon")
    assert not Path(result["path"]).exists()
