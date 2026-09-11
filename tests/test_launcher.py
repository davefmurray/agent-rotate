import json

import pytest

from agent_rotate.launcher import invocation


def test_codex_routes_sse_without_weakening_permissions(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: "/fake/codex")
    args = ["exec", "--sandbox", "read-only", "--model", "user-chosen-model", "do task"]
    command, env = invocation("codex", args, "http://127.0.0.1:4321", "private-key", env={})
    assert command[-len(args) :] == args
    assert "model_providers.agent_rotate.supports_websockets=false" in command
    assert "model_providers.agent_rotate.requires_openai_auth=true" in command
    assert "features.enable_request_compression=false" in command
    assert "private-key" not in json.dumps(command)
    assert env["AGENT_ROTATE_PROXY_KEY"] == "private-key"
    assert not any("dangerously" in arg for arg in command)


def test_claude_routing_is_per_process(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: "/fake/claude")
    original = {"ANTHROPIC_CUSTOM_HEADERS": "X-Team: local", "CLAUDE_CONFIG_DIR": "/user/config"}
    command, env = invocation(
        "claude", ["--resume", "specific-session"], "http://127.0.0.1:1234", "key", env=original
    )
    assert command == ["/fake/claude", "--resume", "specific-session"]
    assert env["CLAUDE_CONFIG_DIR"] == "/user/config"
    assert env["ANTHROPIC_CUSTOM_HEADERS"] == "X-Team: local\nx-agent-rotate-key: key"
    assert "ANTHROPIC_BASE_URL" not in original


def test_claude_keeps_native_auth_instead_of_connector_disabling_override(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: "/fake/claude")
    _, env = invocation(
        "claude",
        [],
        "http://127.0.0.1:1234",
        "key",
        env={
            "ANTHROPIC_AUTH_TOKEN": "fake-token",
            "ANTHROPIC_API_KEY": "fake-key",
            "CLAUDE_CODE_OAUTH_TOKEN": "fake-oauth",
        },
    )
    assert not {"ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"} & env.keys()


@pytest.mark.parametrize(
    "args", [["--remote", "ws://host"], ["--oss"], ["-c", 'model_provider="other"']]
)
def test_conflicting_codex_routing_rejected(monkeypatch, args):
    monkeypatch.setattr("shutil.which", lambda _: "/fake/codex")
    with pytest.raises(ValueError):
        invocation("codex", args, "http://127.0.0.1:1234", "key", env={})
