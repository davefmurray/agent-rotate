from __future__ import annotations

import asyncio
import gzip
import json
import time

import aiohttp
import pytest
from aiohttp import web

from agent_rotate.credentials import Credential
from agent_rotate.proxy import cooldown_until, initial_quota_event


async def upstream(aiohttp_server, handler):
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handler)
    return await aiohttp_server(app)


def add_pool(store, provider):
    for name in ("one", "two"):
        store.add(provider, name, f"/fake/{provider}/{name}")


@pytest.mark.parametrize("provider,path", [("claude", "/v1/messages"), ("codex", "/responses")])
async def test_native_request_survives_quota_without_changing_body(
    store, router_factory, aiohttp_server, provider, path
):
    add_pool(store, provider)
    seen = []
    payload = b'{"model":"test-model","messages":[{"role":"user","content":"hello"}]}'
    stream = b'event: message\ndata: {"text":"completed once"}\n\n'

    async def handle(request):
        seen.append((request.headers["Authorization"], dict(request.headers), await request.read()))
        if len(seen) == 1:
            return web.json_response(
                {"error": {"code": "usage_limit_reached"}},
                status=429,
                headers={"Retry-After": "90"},
            )
        return web.Response(body=stream, headers={"Content-Type": "text/event-stream"})

    server = await upstream(aiohttp_server, handle)
    router = await router_factory(provider, server.make_url(""))
    async with aiohttp.ClientSession() as client:
        for _ in range(2):
            async with client.post(
                router.url + path,
                data=payload,
                headers={
                    "x-agent-rotate-key": router.key,
                    "Authorization": "Bearer must-not-forward",
                    "ChatGPT-Account-Id": "wrong-org",
                    "Cookie": "secret-cookie",
                    "x-codex-turn-state": "old-account-routing",
                },
            ) as response:
                assert response.status == 200
                assert await response.read() == stream
    assert len(seen) == 3
    assert seen[0][0] != seen[1][0] == seen[2][0]  # sticky after the switch
    assert all(item[2] == payload for item in seen)
    assert all("Cookie" not in item[1] and "x-agent-rotate-key" not in item[1] for item in seen)
    assert all("x-codex-turn-state" not in item[1] for item in seen)
    if provider == "codex":
        assert seen[0][1]["ChatGPT-Account-Id"] != seen[1][1]["ChatGPT-Account-Id"]
    else:
        assert all("oauth-2025-04-20" in item[1]["anthropic-beta"] for item in seen)
    history = json.dumps(store.events())
    assert "test-token" not in history and "hello" not in history
    assert any(e["kind"] == "switch" for e in store.events())


@pytest.mark.parametrize("provider,path", [("claude", "/v1/messages"), ("codex", "/responses")])
async def test_exhaustion_is_bounded_and_cooldowns_shared(
    store, router_factory, aiohttp_server, provider, path
):
    add_pool(store, provider)
    calls = 0

    async def handle(_):
        nonlocal calls
        calls += 1
        return web.json_response(
            {"error": {"type": "rate_limit_error"}}, status=429, headers={"Retry-After": "120"}
        )

    server = await upstream(aiohttp_server, handle)
    for _ in range(2):
        router = await router_factory(provider, server.make_url(""))
        async with aiohttp.ClientSession() as client:
            async with client.post(
                router.url + path,
                json={"model": "same-model"},
                headers={"x-agent-rotate-key": router.key},
            ) as response:
                assert response.status == 429
                assert int(response.headers["Retry-After"]) > 100
    assert calls == 2  # second router uses the first router's cooldowns


@pytest.mark.parametrize("status", [400, 403, 500, 503])
async def test_nonquota_http_error_never_switches(store, router_factory, aiohttp_server, status):
    add_pool(store, "claude")
    calls = 0

    async def handle(_):
        nonlocal calls
        calls += 1
        return web.Response(status=status, text="upstream failure")

    server = await upstream(aiohttp_server, handle)
    router = await router_factory("claude", server.make_url(""))
    async with aiohttp.ClientSession() as client:
        async with client.post(
            router.url + "/v1/messages", json={}, headers={"x-agent-rotate-key": router.key}
        ) as response:
            assert response.status == status
    assert calls == 1


async def test_401_refreshes_once_without_switch(store, router_factory, aiohttp_server):
    add_pool(store, "codex")
    tokens = []

    async def handle(request):
        tokens.append(request.headers["Authorization"])
        return web.Response(status=401)

    server = await upstream(aiohttp_server, handle)
    router = await router_factory("codex", server.make_url(""))
    async with aiohttp.ClientSession() as client:
        async with client.post(
            router.url + "/responses", json={}, headers={"x-agent-rotate-key": router.key}
        ) as response:
            assert response.status == 401
    assert len(tokens) == 2 and tokens[1] == tokens[0] + "-fresh"


async def test_partial_stream_quota_is_not_replayed(store, router_factory, aiohttp_server):
    add_pool(store, "claude")
    calls = 0
    body = (
        b'data: {"type":"content_block_delta","text":"tool already started"}\n\n'
        b'data: {"type":"error","error":{"type":"rate_limit_error"}}\n\n'
    )

    async def handle(_):
        nonlocal calls
        calls += 1
        return web.Response(body=body, content_type="text/event-stream")

    server = await upstream(aiohttp_server, handle)
    router = await router_factory("claude", server.make_url(""))
    async with aiohttp.ClientSession() as client:
        async with client.post(
            router.url + "/v1/messages", json={}, headers={"x-agent-rotate-key": router.key}
        ) as response:
            assert await response.read() == body
    assert calls == 1


async def test_initial_structured_sse_quota_can_switch(store, router_factory, aiohttp_server):
    add_pool(store, "claude")
    calls = 0

    async def handle(_):
        nonlocal calls
        calls += 1
        body = (
            b'data: {"type":"error","error":{"type":"rate_limit_error"}}\n\n'
            if calls == 1
            else b'data: {"type":"message","text":"ok"}\n\n'
        )
        return web.Response(body=body, content_type="text/event-stream")

    server = await upstream(aiohttp_server, handle)
    router = await router_factory("claude", server.make_url(""))
    async with aiohttp.ClientSession() as client:
        async with client.post(
            router.url + "/v1/messages", json={}, headers={"x-agent-rotate-key": router.key}
        ) as response:
            assert b'"ok"' in await response.read()
    assert calls == 2


async def test_security_boundary_rejects_untrusted_requests(store, router_factory, aiohttp_server):
    calls = 0

    async def handle(_):
        nonlocal calls
        calls += 1
        return web.Response()

    server = await upstream(aiohttp_server, handle)
    router = await router_factory("claude", server.make_url(""))
    async with aiohttp.ClientSession() as client:
        for path, headers, status in [
            ("/v1/messages", {}, 401),
            ("/v1/messages", {"x-agent-rotate-key": "wrong"}, 401),
            (
                "/v1/messages",
                {"x-agent-rotate-key": router.key, "Origin": "https://evil.test"},
                401,
            ),
            ("/arbitrary", {"x-agent-rotate-key": router.key}, 404),
        ]:
            async with client.post(router.url + path, headers=headers) as response:
                assert response.status == status
    assert calls == 0


async def test_credentials_never_follow_redirects(store, router_factory, aiohttp_server):
    add_pool(store, "codex")
    stolen = []

    async def steal(request):
        stolen.append(dict(request.headers))
        return web.Response()

    target = await upstream(aiohttp_server, steal)

    async def redirect(_):
        return web.Response(status=307, headers={"Location": str(target.make_url("/steal"))})

    server = await upstream(aiohttp_server, redirect)
    router = await router_factory("codex", server.make_url(""))
    async with aiohttp.ClientSession() as client:
        async with client.post(
            router.url + "/responses",
            json={},
            allow_redirects=False,
            headers={"x-agent-rotate-key": router.key},
        ) as response:
            assert response.status == 502
            assert "Location" not in response.headers
    assert not stolen


async def test_incremental_codex_request_is_not_switched(store, router_factory, aiohttp_server):
    add_pool(store, "codex")
    calls = 0

    async def handle(_):
        nonlocal calls
        calls += 1
        return web.Response(status=429)

    server = await upstream(aiohttp_server, handle)
    router = await router_factory("codex", server.make_url(""))
    async with aiohttp.ClientSession() as client:
        async with client.post(
            router.url + "/responses",
            json={"previous_response_id": "old-id"},
            headers={"x-agent-rotate-key": router.key},
        ) as response:
            assert response.status == 429
    assert calls == 1


async def test_successful_stream_is_delivered_before_upstream_finishes(
    store, router_factory, aiohttp_server
):
    add_pool(store, "claude")
    release = asyncio.Event()

    async def handle(request):
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await response.write(b'data: {"text":"first"}\n\n')
        await release.wait()
        await response.write(b'data: {"text":"last"}\n\n')
        return response

    server = await upstream(aiohttp_server, handle)
    router = await router_factory("claude", server.make_url(""))
    async with aiohttp.ClientSession() as client:
        async with client.post(
            router.url + "/v1/messages", json={}, headers={"x-agent-rotate-key": router.key}
        ) as response:
            async with asyncio.timeout(2):
                first = await response.content.readuntil(b"\n\n")
            assert b"first" in first
            release.set()
            assert b"last" in await response.read()


def test_retry_after_and_body_reset():
    now = time.time()
    assert cooldown_until({"Retry-After": "120"}, b"{}", now) == now + 120
    assert (
        cooldown_until({}, json.dumps({"error": {"resets_at": now + 600}}).encode(), now)
        == now + 600
    )
    assert cooldown_until({"Retry-After": "garbage"}, b"invalid", now) == now + 60


def test_only_structured_first_error_is_quota():
    assert initial_quota_event(b'data: {"type":"error","error":{"type":"rate_limit_error"}}\n\n')
    assert not initial_quota_event(b'data: {"type":"message","text":"HTTP 429 quota exceeded"}\n\n')
    assert not initial_quota_event(b"HTTP 429")


async def test_compressed_body_is_forwarded_but_not_replayed(store, router_factory, aiohttp_server):
    add_pool(store, "codex")
    calls = 0
    body = b'{"previous_response_id":"account-bound-id","model":"test-model"}'

    async def handle(request):
        nonlocal calls
        calls += 1
        assert request.headers["Content-Encoding"] == "gzip"
        assert await request.read() == body  # fake upstream decompresses as a provider would
        return web.Response(status=429)

    server = await upstream(aiohttp_server, handle)
    router = await router_factory("codex", server.make_url(""))
    async with aiohttp.ClientSession() as client:
        async with client.post(
            router.url + "/responses",
            data=gzip.compress(body),
            headers={
                "x-agent-rotate-key": router.key,
                "Content-Encoding": "gzip",
            },
        ) as response:
            assert response.status == 429
    assert calls == 1


async def test_two_handles_for_same_identity_do_not_get_two_attempts(
    store, router_factory, aiohttp_server
):
    add_pool(store, "codex")
    calls = 0

    async def handle(_):
        nonlocal calls
        calls += 1
        return web.Response(status=429)

    class SameIdentity:
        async def get(self, account, *, refresh=False):
            return Credential("synthetic-" + account.name, "same-subscription-id")

    server = await upstream(aiohttp_server, handle)
    router = await router_factory("codex", server.make_url(""))
    router.credentials = SameIdentity()
    async with aiohttp.ClientSession() as client:
        async with client.post(
            router.url + "/responses",
            json={},
            headers={
                "x-agent-rotate-key": router.key,
            },
        ) as response:
            assert response.status == 429
    assert calls == 1


async def test_hard_account_restriction_never_falls_back(store, router_factory, aiohttp_server):
    add_pool(store, "claude")
    tokens = []

    async def handle(request):
        tokens.append(request.headers["Authorization"])
        return web.Response(status=429)

    server = await upstream(aiohttp_server, handle)
    router = await router_factory("claude", server.make_url(""), account="one")
    async with aiohttp.ClientSession() as client:
        async with client.post(
            router.url + "/v1/messages",
            json={},
            headers={
                "x-agent-rotate-key": router.key,
            },
        ) as response:
            assert response.status == 429
    assert tokens == ["Bearer test-token-one"]


async def test_broken_partial_stream_is_not_replayed(store, router_factory, aiohttp_server):
    add_pool(store, "claude")
    calls = 0

    async def handle(request):
        nonlocal calls
        calls += 1
        stream = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await stream.prepare(request)
        await stream.write(b'data: {"type":"content_block_delta","text":"first"}\n\n')
        await asyncio.sleep(0.01)
        request.transport.close()
        return stream

    server = await upstream(aiohttp_server, handle)
    router = await router_factory("claude", server.make_url(""))
    async with aiohttp.ClientSession() as client:
        async with client.post(
            router.url + "/v1/messages",
            json={},
            headers={
                "x-agent-rotate-key": router.key,
            },
        ) as response:
            with pytest.raises(aiohttp.ClientPayloadError):
                await response.read()
    assert calls == 1
