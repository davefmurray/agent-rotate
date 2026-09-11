import asyncio
import json
import os
import sys
import uuid

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent_rotate.cli import parser, settings
from agent_rotate.completion import script
from agent_rotate.mcp_server import server
from agent_rotate.sessions import saved_sessions


async def test_real_mcp_stdio_is_structured_cached_and_readonly(store, monkeypatch):
    store.add("codex", "one", "/not-a-real-credential-store")
    store.start_session("native-session", "codex", None, "/workspace", "sticky")
    store.update_session("native-session", account="one")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "agent_rotate", "mcp"],
        env={
            **os.environ,
            "AGENT_ROTATE_HOME": str(store.root),
            "AGENT_ROTATE_SESSION_ID": "native-session",
        },
    )
    async with stdio_client(params) as (reader, writer), ClientSession(reader, writer) as client:
        await client.initialize()
        tools = (await client.list_tools()).tools
        assert len(tools) == 6
        assert all(t.annotations.readOnlyHint and t.outputSchema for t in tools)
        value = await client.call_tool("agent_rotate_current_session", {})
        assert value.structuredContent["session"]["account"] == "one"
        value = await client.call_tool("agent_rotate_accounts", {})
        assert value.structuredContent["accounts"][0]["health"]["state"] == "unknown"
        assert not (store.root / "jobs").exists()


async def test_mcp_delegation_is_explicit_and_monitor_cancels(store, tmp_path):
    with pytest.raises(ValueError, match="workspace"):
        server(store, allow_delegation=True)
    mcp = server(store, allow_delegation=True, workspace=tmp_path)
    tools = {t.name: t for t in await mcp.list_tools()}
    assert not tools["agent_rotate_delegate"].annotations.readOnlyHint
    assert tools["agent_rotate_cancel_job"].annotations.destructiveHint
    task = asyncio.create_task(mcp.call_tool("agent_rotate_monitor", {"seconds": 30}))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_mcp_jobs_cannot_read_or_cancel_another_workspace(store, tmp_path):
    with store.connect() as db:
        db.execute(
            "INSERT INTO jobs(id,provider,cwd,created,state) VALUES (?,?,?,?,?)",
            ("f" * 32, "codex", str(tmp_path / "elsewhere"), 1, "completed"),
        )
    mcp = server(store, allow_delegation=True, workspace=tmp_path)
    _, data = await mcp.call_tool("agent_rotate_jobs", {})
    assert data["jobs"] == []
    for name in ("agent_rotate_job_result", "agent_rotate_cancel_job"):
        with pytest.raises(Exception, match="workspace"):
            await mcp.call_tool(name, {"job_id": "f" * 32})


async def test_unavailable_desktop_notifier_does_not_interrupt_work(monkeypatch):
    from agent_rotate.notifications import send_desktop

    async def unavailable(*args, **kwargs):
        raise FileNotFoundError("no desktop notifier")

    monkeypatch.setattr("agent_rotate.notifications.sys.platform", "darwin")
    monkeypatch.setattr("agent_rotate.notifications.asyncio.create_subprocess_exec", unavailable)
    await send_desktop("account ready")


def test_saved_session_index_returns_metadata_not_prompt_content(tmp_path):
    ident = str(uuid.uuid4())
    (tmp_path / "rollout.jsonl").write_text(
        json.dumps(
            {
                "type": "session_meta",
                "payload": {"id": ident, "cwd": str(tmp_path), "prompt": "private prompt marker"},
            }
        )
        + "\n"
    )
    (tmp_path / "not-a-session.jsonl").write_text(
        '{"type":"message","text":"private prompt marker"}\n'
    )
    rows = saved_sessions("codex", root=tmp_path)
    assert len(rows) == 1 and rows[0]["id"] == ident
    assert "private prompt marker" not in json.dumps(rows)


def test_claude_session_header_is_recognized(tmp_path):
    ident = str(uuid.uuid4())
    (tmp_path / f"{ident}.jsonl").write_text(
        json.dumps(
            {
                "type": "user",
                "sessionId": ident,
                "cwd": str(tmp_path),
                "message": {"content": "private"},
            }
        )
        + "\n"
    )
    assert saved_sessions("claude", root=tmp_path)[0]["id"] == ident


@pytest.mark.parametrize("value", ["0", "100", "NaN", "infinity", "no"])
def test_config_threshold_rejects_invalid_values(store, value):
    args = parser().parse_args(["config", "set", "threshold", value])
    with pytest.raises(ValueError):
        settings(store, args)


def test_config_opt_in_and_completion_have_no_install_side_effect(store):
    assert settings(store, parser().parse_args(["config"])) == {
        "notifications": False,
        "strategy": "sticky",
        "threshold": None,
    }
    settings(store, parser().parse_args(["config", "set", "notifications", "true"]))
    assert store.setting("notifications") is True
    for shell in ("bash", "zsh", "fish"):
        text = script(shell)
        assert "--names" in text
        assert "rm " not in text and ".zshrc" not in text
