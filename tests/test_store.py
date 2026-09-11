import json
import sqlite3
import time

import pytest

from agent_rotate.credentials import Credential, claude_windows, codex_windows
from agent_rotate.store import Store, availability


@pytest.mark.parametrize("name", ["../other", "/absolute", "..", "bad\nname", "", "a" * 65])
def test_invalid_account_name(store, name):
    with pytest.raises(ValueError):
        store.add("codex", name, "/fake")


def test_disable_persists_and_add_does_not_reenable(store):
    store.add("codex", "work", "/fake")
    store.enable("codex", "work", False)
    store.add("codex", "work", "/fake")
    reopened = Store(store.root)
    assert not reopened.accounts()[0].enabled
    assert store.path.stat().st_mode & 0o777 == 0o600


def test_database_connection_closes_after_each_operation(store):
    with store.connect() as connection:
        connection.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")


def test_account_destination_cannot_silently_change(store):
    store.add("codex", "work", "/one")
    with pytest.raises(ValueError):
        store.add("codex", "work", "/two")


def test_same_codex_directory_is_not_two_accounts(store):
    store.add("codex", "first", "/same")
    with pytest.raises(ValueError):
        store.add("codex", "second", "/same")


def test_model_specific_quota_and_reset(store):
    account = store.add("claude", "work", "/fake")
    now = time.time()
    store.set_usage(
        account,
        [
            {"name": "five_hour", "used_percent": 20, "resets_at": now + 10},
            {"name": "seven_day_fable", "used_percent": 100, "resets_at": now + 20},
        ],
    )
    assert availability(store, account, "claude-fable-5", now)[0] == now + 20
    assert availability(store, account, "claude-sonnet", now)[0] == 0
    assert availability(store, account, "claude-fable-5", now + 21)[0] == 0


def test_credentials_repr_is_redacted():
    assert "secret" not in repr(Credential("secret", "secret-id"))


def test_only_usage_fields_survive_normalization():
    c = claude_windows(
        {
            "five_hour": {"utilization": 50, "resets_at": "2026-09-12T12:00:00Z"},
            "access_token": "do-not-return",
        }
    )
    o = codex_windows(
        {
            "rateLimits": {"primary": {"usedPercent": 10, "resetsAt": 2000000000}},
            "access_token": "do-not-return",
        }
    )
    assert c[0]["used_percent"] == 50
    assert o[0]["used_percent"] == 10
    assert "do-not-return" not in json.dumps([c, o])
