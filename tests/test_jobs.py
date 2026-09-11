import asyncio
import base64
import json
import os
import sys
import time

import pytest

from agent_rotate import jobs


@pytest.fixture
def fake_codex(tmp_path, store, monkeypatch):
    home = tmp_path / "native-auth"
    home.mkdir()
    payload = (
        base64.urlsafe_b64encode(json.dumps({"exp": time.time() + 3600}).encode())
        .decode()
        .rstrip("=")
    )
    (home / "auth.json").write_text(
        json.dumps(
            {"tokens": {"access_token": f"fake.{payload}.fake", "account_id": "synthetic-account"}}
        )
    )
    store.add("codex", "one", str(home))
    binary = tmp_path / "bin"
    binary.mkdir()
    codex = binary / "codex"
    codex.write_text(
        f"#!{sys.executable}\n"
        + """
import json, os, sys, time
from pathlib import Path
if 'app-server' in sys.argv:
    for line in sys.stdin:
        request = json.loads(line)
        if 'id' in request:
            result = {'rateLimits': {'primary': {'usedPercent': 0}}}
            print(json.dumps({'id': request['id'], 'result': result}), flush=True)
else:
    assert '--sandbox' in sys.argv
    assert sys.argv[sys.argv.index('--sandbox')+1] == 'read-only'
    assert '--ephemeral' in sys.argv
    assert not any('dangerously' in x for x in sys.argv)
    prompt = sys.stdin.read()
    Path('native-started').write_text(os.environ['AGENT_ROTATE_SESSION_ID'])
    if prompt == 'slow':
        while True:
            time.sleep(1)
    item = {'type': 'agent_message', 'text': 'JOB_OK'}
    print(json.dumps({'type': 'item.completed', 'item': item}), flush=True)
"""
    )
    codex.chmod(0o700)
    monkeypatch.setenv("PATH", str(binary) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("AGENT_ROTATE_HOME", str(store.root))
    return tmp_path


async def finish(store, ident):
    async with asyncio.timeout(15):
        while jobs.rows(store, ident)[0]["state"] in {"queued", "running"}:  # noqa: ASYNC110
            await asyncio.sleep(0.1)
    return jobs.result(store, ident)


async def test_background_job_uses_native_cli_and_keeps_prompt_out_of_metadata(store, fake_codex):
    submitted = await jobs.submit(
        store, "codex", "private prompt marker", fake_codex, account="one"
    )
    value = await finish(store, submitted["id"])
    assert value["state"] == "completed" and value["result"] == "JOB_OK"
    assert "private prompt marker" not in json.dumps(jobs.rows(store))
    path = jobs.job_dir(store, submitted["id"]) / "result.txt"
    assert path.stat().st_mode & 0o777 == 0o600
    assert (fake_codex / "native-started").read_text()
    jobs.forget(store, submitted["id"])
    assert not path.exists() and not jobs.rows(store, submitted["id"])


async def test_cancellation_stops_native_process_and_router(store, fake_codex):
    submitted = await jobs.submit(store, "codex", "slow", fake_codex, account="one")
    async with asyncio.timeout(15):
        while not (fake_codex / "native-started").exists():  # noqa: ASYNC110
            await asyncio.sleep(0.1)
    session = (fake_codex / "native-started").read_text()
    assert any(s["id"] == session for s in store.sessions())
    jobs.cancel(store, submitted["id"])
    value = await finish(store, submitted["id"])
    assert value["state"] == "cancelled" and value["result"] is None
    assert not any(s["id"] == session for s in store.sessions())


def test_claude_jobs_retain_permission_modes_and_never_bypass():
    args = jobs.native_args("claude", "read-only", "sonnet")
    assert args[args.index("--permission-mode") + 1] == "plan"
    assert args[args.index("--model") + 1] == "sonnet"
    assert "--no-session-persistence" in args
    assert not any("bypass" in x or "dangerously" in x for x in args)


async def test_timeout_stops_native_process_and_router(store, fake_codex):
    submitted = await jobs.submit(
        store, "codex", "slow", fake_codex, account="one", timeout_seconds=10
    )
    value = await finish(store, submitted["id"])
    session = (fake_codex / "native-started").read_text()
    assert value["state"] == "timed_out" and value["result"] is None
    assert not any(s["id"] == session for s in store.sessions())


async def test_bad_job_selection_fails_before_spawning(store, tmp_path):
    with pytest.raises(ValueError, match="No enabled"):
        await jobs.submit(store, "codex", "test", tmp_path, account="missing")
    assert not jobs.rows(store)
