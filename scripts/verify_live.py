"""Opt-in native CLI smoke: inject one 429, then make one real provider request.

Run manually with --provider claude|codex. Not part of CI. Uses existing registered
accounts and their credential owners, isolated temporary routing metadata, and a
read-only/no-tools prompt. With --after-tool, allow one harmless printf diagnostic
and inject the rejection on the following model request. No credentials, bodies,
or native transcripts are saved.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import tempfile
from pathlib import Path

import aiohttp
from aiohttp import web

from agent_rotate.credentials import Credentials
from agent_rotate.launcher import invocation
from agent_rotate.proxy import INFERENCE, UPSTREAMS, Router, clean_headers
from agent_rotate.store import Store


def has_tool_result(value):
    """Recognize the diagnostic result, not the marker in a prompt/tool call."""
    if isinstance(value, dict):
        if value.get("type") == "tool_result":
            return "ROTATE_TOOL_OK" in json.dumps(value.get("content"))
        if value.get("type") in {"function_call_output", "custom_tool_call_output"}:
            return "ROTATE_TOOL_OK" in json.dumps(value.get("output"))
        return any(has_tool_result(v) for v in value.values())
    if isinstance(value, list):
        return any(has_tool_result(v) for v in value)
    return False


async def verify(provider: str, after_tool: bool = False):
    accounts = [a for a in Store().accounts(provider) if a.enabled]
    if len(accounts) < 2:
        raise RuntimeError("This verification requires two registered accounts")
    injected = 0
    upstream_success = 0
    inference_count = 0
    saw_tool_history = False
    async with aiohttp.ClientSession(
        auto_decompress=False,
        timeout=aiohttp.ClientTimeout(total=None, sock_connect=20, sock_read=90),
    ) as client:

        async def relay(request):
            nonlocal injected, upstream_success, inference_count, saw_tool_history
            inference = request.method == "POST" and request.path == INFERENCE[provider]
            body = await request.read()
            if inference:
                inference_count += 1
            contains_tool_result = False
            if after_tool and inference and inference_count > 1:
                # Check a tool result's presence, never persist or print the body.
                with contextlib.suppress(ValueError, UnicodeError):
                    contains_tool_result = has_tool_result(json.loads(body))
            if inference and inference_count == (2 if after_tool else 1):
                injected += 1
                return web.json_response(
                    {"error": {"type": "rate_limit_error", "code": "usage_limit_reached"}},
                    status=429,
                    headers={"Retry-After": "60"},
                )
            async with client.request(
                request.method,
                UPSTREAMS[provider] + str(request.rel_url),
                data=body,
                headers=clean_headers(request.headers),
                allow_redirects=False,
            ) as response:
                if inference and response.status == 200:
                    upstream_success += 1
                    saw_tool_history |= contains_tool_result
                stream = web.StreamResponse(
                    status=response.status, headers=clean_headers(response.headers)
                )
                await stream.prepare(request)
                async for chunk in response.content.iter_chunked(65536):
                    await stream.write(chunk)
                return stream

        app = web.Application(client_max_size=32 * 1024 * 1024)
        app.router.add_route("*", "/{path:.*}", relay)
        runner = web.AppRunner(app, access_log=None, auto_decompress=False)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        upstream = f"http://127.0.0.1:{runner.addresses[0][1]}"
        try:
            with tempfile.TemporaryDirectory(prefix="agent-rotate-live-") as directory:
                store = Store(Path(directory) / "state")
                for account in accounts[:2]:
                    store.add(account.provider, account.name, account.home)
                router = Router(store, provider, Credentials(), upstream=upstream)
                router.active = accounts[0].name
                process = None
                try:
                    await router.start()
                    prompt = "Reply exactly ROTATE_OK. Do not use tools or inspect files."
                    if after_tool:
                        prompt = (
                            "For this diagnostic, run the raw shell command printf ROTATE_TOOL_OK "
                            "exactly once, with no wrappers. Then reply exactly ROTATE_OK. "
                            "Do not inspect files or execute any other commands."
                        )
                    args = (
                        [
                            "-p",
                            "--tools",
                            "",
                            "--strict-mcp-config",
                            "--mcp-config",
                            '{"mcpServers":{}}',
                            "--",
                            prompt,
                        ]
                        if provider == "claude"
                        else ["exec", "--skip-git-repo-check", "--sandbox", "read-only", prompt]
                    )
                    if after_tool:
                        if provider == "claude":
                            args = [
                                "-p",
                                "--output-format",
                                "stream-json",
                                "--verbose",
                                "--model",
                                "sonnet",
                                "--tools",
                                "Bash",
                                "--allowedTools",
                                "Bash(printf *)",
                                "--strict-mcp-config",
                                "--mcp-config",
                                '{"mcpServers":{}}',
                                "--",
                                prompt,
                            ]
                        else:
                            args.insert(1, "--json")
                    command, env = invocation(provider, args, router.url, router.key)
                    env.pop("OPENAI_API_KEY", None)
                    env.pop("CODEX_API_KEY", None)
                    process = await asyncio.create_subprocess_exec(
                        *command,
                        env=env,
                        cwd=directory,
                        stdin=asyncio.subprocess.DEVNULL,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    async with asyncio.timeout(120):
                        output, _ = await process.communicate()
                    events = store.events()
                    switches = [e for e in events if e["kind"] == "switch"]
                    tool_calls = 0
                    reply_ok = b"ROTATE_OK" in output
                    if after_tool:
                        reply_ok = False
                        for line in output.splitlines():
                            with contextlib.suppress(ValueError, UnicodeError):
                                event = json.loads(line)
                                if event.get("type") == "item.completed":
                                    item = event.get("item", {})
                                    tool_calls += item.get("type") == "command_execution"
                                    if item.get("type") == "agent_message":
                                        reply_ok = item.get("text", "").strip() == "ROTATE_OK"
                                if event.get("type") == "assistant":
                                    tool_calls += sum(
                                        part.get("type") == "tool_use"
                                        for part in event.get("message", {}).get("content", [])
                                    )
                                if event.get("type") == "result":
                                    reply_ok = event.get("result", "").strip() == "ROTATE_OK"
                    result = {
                        "provider": provider,
                        "native_exit": process.returncode,
                        "initial_account": accounts[0].name,
                        "fallback_account": switches[0]["account"] if switches else None,
                        "injected_quota_rejections": injected,
                        "real_successful_requests": upstream_success,
                        "reply_ok": reply_ok,
                    }
                    if after_tool:
                        result.update(
                            tool_calls=tool_calls, tool_history_preserved=saw_tool_history
                        )
                    print(json.dumps(result))
                    if not (
                        process.returncode == 0
                        and result["reply_ok"]
                        and injected == 1
                        and upstream_success >= 1
                        and result["fallback_account"] != result["initial_account"]
                        and switches
                        and (
                            not after_tool
                            or (tool_calls == 1 and saw_tool_history and upstream_success >= 2)
                        )
                    ):
                        raise RuntimeError("Native failover verification did not pass")
                finally:
                    if process and process.returncode is None:
                        process.terminate()
                        with contextlib.suppress(TimeoutError):
                            await asyncio.wait_for(process.wait(), 3)
                        if process.returncode is None:
                            process.kill()
                            await process.wait()
                    await router.close()
        finally:
            await runner.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=["claude", "codex"])
    parser.add_argument("--after-tool", action="store_true")
    args = parser.parse_args()
    asyncio.run(verify(args.provider, args.after_tool))
