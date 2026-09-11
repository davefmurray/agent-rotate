from __future__ import annotations

import os
import sys

import aiohttp
import pytest
from aiohttp import web

from agent_rotate.credentials import Credential
from agent_rotate.launcher import run
from agent_rotate.proxy import Router


@pytest.mark.parametrize("provider", ["claude", "codex"])
async def test_real_subprocess_keeps_running_through_quota_then_router_closes(
    tmp_path, store, monkeypatch, aiohttp_server, provider
):
    for name in ("one", "two"):
        store.add(provider, name, f"/fake/{name}")

    class Auth:
        async def get(self, account, *, refresh=False):
            return Credential("fake-" + account.name, "id-" + account.name)

        async def usage(self, account):
            return []

    requests = []

    async def handle(request):
        requests.append((request.headers["Authorization"], await request.read()))
        if len(requests) == 1:
            return web.json_response({"error": {"type": "rate_limit_error"}}, status=429)
        return web.Response(text="native-session-still-running")

    app = web.Application()
    app.router.add_post("/{path:.*}", handle)
    upstream = await aiohttp_server(app)
    routers = []

    def factory(*args, **kwargs):
        router = Router(*args, **kwargs, upstream=str(upstream.make_url("")))
        routers.append(router)
        return router

    monkeypatch.setattr("agent_rotate.launcher.Credentials", Auth)
    monkeypatch.setattr("agent_rotate.launcher.Router", factory)
    binary = tmp_path / provider
    binary.write_text(
        f"#!{sys.executable}\n"
        + """
import json, os, sys, urllib.request
provider = os.path.basename(sys.argv[0])
if provider == "claude":
    base = os.environ["ANTHROPIC_BASE_URL"]
    route = "/v1/messages"
else:
    value = next(a for a in sys.argv if a.startswith("model_providers.agent_rotate.base_url="))
    base = json.loads(value.split("=", 1)[1])
    assert "model_providers.agent_rotate.supports_websockets=false" in sys.argv
    route = "/responses"
data = b'{"model":"test-model","input":"one logical request"}'
request = urllib.request.Request(base+route, data=data, headers={
    "x-agent-rotate-key": os.environ["AGENT_ROTATE_PROXY_KEY"]
})
with urllib.request.urlopen(request) as response:
    assert response.read() == b"native-session-still-running"
sys.exit(7)
"""
    )
    binary.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    assert await run(store, provider, []) == 7
    assert len(requests) == 2
    assert requests[0][0] != requests[1][0]
    assert requests[0][1] == requests[1][1]
    async with aiohttp.ClientSession() as client:
        with pytest.raises(aiohttp.ClientConnectorError):
            await client.get(routers[0].url)
