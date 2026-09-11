import asyncio
import json
import time

import pytest

from agent_rotate.collector import Collector
from agent_rotate.credentials import CredentialError, UsageError
from agent_rotate.dashboard import forecast, snapshot, write_feed
from agent_rotate.notifications import check_alerts
from agent_rotate.proxy import Router
from agent_rotate.rpc import revoked_error
from agent_rotate.store import Store, usage_fresh


def window(used, reset=None):
    return {
        "name": "seven_day",
        "used_percent": used,
        "resets_at": reset or time.time() + 86400,
        "period_seconds": 604800,
    }


def test_old_database_upgrade_preserves_accounts_and_cooldowns(store):
    a = store.add("codex", "one", "/fake")
    store.cooldown(a, "m", time.time() + 100)
    with store.connect() as db:
        db.execute("DROP TABLE polls")
    reopened = Store(store.root)
    assert reopened.accounts() == [a]
    assert reopened.blocked_until(a, "m") > time.time()
    assert reopened.claim_poll(a, time.time())


async def test_two_collectors_share_one_poll_and_keep_cache(store):
    a = store.add("codex", "one", "/fake")
    calls = []
    entered, release = asyncio.Event(), asyncio.Event()

    class Source:
        async def usage(self, account):
            calls.append(account.name)
            entered.set()
            await release.wait()
            return [window(25)]

    first = asyncio.create_task(Collector(store, Source()).poll(a))
    await entered.wait()
    assert not await Collector(Store(store.root), Source()).poll(a)
    release.set()
    assert await first
    assert not await Collector(store, Source()).poll(a)
    assert calls == ["one"]
    assert store.usage(a)[1][0]["used_percent"] == 25


async def test_usage_429_keeps_last_good_and_does_not_block_inference(store):
    a = store.add("claude", "one", "/fake")
    store.set_usage(a, [window(20)])
    retry = time.time() + 3600

    class Source:
        async def usage(self, account):
            raise UsageError("usage_429", retry)

    assert not await Collector(store, Source()).poll(a)
    assert store.poll_state(a)["next_poll"] >= retry
    assert store.usage(a)[1][0]["used_percent"] == 20
    assert store.blocked_until(a, "*") == 0
    assert store.health(a)["state"] == "unknown"
    assert snapshot(store)["accounts"][0]["stale"]


@pytest.mark.parametrize("permanent", [False, True])
async def test_only_permanent_credential_failure_quarantines(store, permanent):
    a = store.add("codex", "one", "/fake")

    class Source:
        async def usage(self, account):
            raise CredentialError("safe failure", permanent=permanent)

    await Collector(store, Source()).poll(a)
    assert (store.health(a)["state"] == "relogin_required") is permanent


async def test_successful_health_check_recovers_quarantine(store):
    a = store.add("codex", "one", "/fake")
    store.set_health(a, "relogin_required", "revoked_login")

    class Source:
        async def usage(self, account):
            return [window(10)]

    assert await Collector(store, Source()).poll(a)
    assert store.health(a)["state"] == "ready"


def test_lease_expiry_and_old_owner_cannot_release_new_lease(store):
    a = store.add("codex", "one", "/fake")
    now = time.time()
    old = store.claim_poll(a, now)
    new = store.claim_poll(a, now + 121)
    assert new and old != new
    store.finish_poll(a, old, next_poll=0, interval=10)
    assert store.poll_state(a)["owner"] == new


def test_groups_nearest_directory_and_removed_mapping_fail_closed(store, tmp_path):
    for p in ("claude", "codex"):
        store.add(p, "one", "/fake/one")
        store.add(p, "two", "/fake/two")
        store.set_pool(p, "work", ["one"])
    store.set_pool("codex", "special", ["two"])
    store.map_pool("codex", "work", tmp_path)
    store.map_pool("codex", "special", tmp_path / "sub")
    assert store.resolve_pool("codex", tmp_path / "sub" / "child") == "special"
    assert store.resolve_pool("claude", tmp_path) is None
    link = tmp_path / "linked"
    (tmp_path / "sub").mkdir()
    link.symlink_to(tmp_path / "sub", target_is_directory=True)
    assert store.resolve_pool("codex", link) == "special"
    store.remove_pool("codex", "special")
    assert store.resolve_pool("codex", link) == "special"
    with pytest.raises(ValueError, match="pool"):
        Router(store, "codex", None, pool="special")


def test_ordered_fallback_stays_in_pool_and_disabled_account_stays_out(store):
    for name in ("one", "two", "outside"):
        store.add("codex", name, "/fake/" + name)
    store.set_pool("codex", "work", ["two", "one"])
    router = Router(store, "codex", None, pool="work", strategy="ordered")
    assert router.choose("m", set()).name == "two"
    assert router.choose("m", {"two"}).name == "one"
    assert router.choose("m", {"two", "one"}) is None
    store.enable("codex", "two", False)
    assert router.choose("m", set()).name == "one"


def test_proactive_requires_dwell_headroom_and_request_boundary(store):
    a = store.add("claude", "one", "/one")
    b = store.add("claude", "two", "/two")
    store.set_usage(a, [window(92)])
    store.set_usage(b, [window(50)])
    router = Router(store, "claude", None, threshold=90)
    router.active = "one"
    router.changed_at = time.time()
    assert router.choose("m", set(), proactive=True).name == "one"
    router.changed_at -= 301
    assert router.choose("m", set()).name == "one"
    assert router.choose("m", set(), proactive=True).name == "two"
    store.set_usage(b, [window(89)])
    assert router.choose("m", set(), proactive=True).name == "one"


def test_consume_first_uses_known_weekly_reset_and_stays_sticky(store):
    a = store.add("claude", "one", "/one")
    b = store.add("claude", "two", "/two")
    store.set_usage(a, [window(70, time.time() + 100)])
    store.set_usage(b, [window(10, time.time() + 10000)])
    router = Router(store, "claude", None, strategy="consume-first")
    assert router.choose("m", set()).name == "one"
    router.active = "two"
    assert router.choose("m", set()).name == "two"


def test_forecast_uses_sample_time_and_suppresses_sparse_reset_and_stale_data(store):
    a = store.add("claude", "one", "/one")
    now = time.time()
    w = window(90, now + 4 * 86400)
    store.set_usage(a, [w])
    assert forecast(store, a, w, now)["ahead_of_pace"] is True
    assert forecast(store, a, w, now)["exhaustion_at"] is None
    with store.connect() as db:
        for offset, used in [(600, 70), (300, 80)]:
            db.execute(
                "INSERT INTO usage_samples VALUES (?,?,?,?)",
                ("claude", "one", now - offset, json.dumps([dict(w, used_percent=used)])),
            )
    assert forecast(store, a, w, now + 0.01)["exhaustion_at"] > now
    with store.connect() as db:
        db.execute("UPDATE usage SET checked=?", (now + 60,))
    assert not usage_fresh(store, a, now)
    assert forecast(store, a, w, now)["exhaustion_at"] is None


def test_two_sessions_have_independent_accounts_expiry_and_private_feed(store):
    store.start_session("one", "codex", None, "/project1", "sticky")
    store.start_session("two", "codex", None, "/project2", "sticky")
    store.update_session("one", account="a")
    store.update_session("two", account="b")
    data = snapshot(store, session="one")
    assert data["current_session"]["account"] == "a"
    assert len(data["sessions"]) == 2
    write_feed(store, data)
    assert (store.root / "status.json").stat().st_mode & 0o777 == 0o600
    with store.connect() as db:
        db.execute("UPDATE sessions SET heartbeat=0 WHERE id='two'")
    assert len(snapshot(store)["sessions"]) == 1
    store.update_session("one", ended=True)
    assert snapshot(store, session="one")["current_session"] is None


async def test_local_alerts_opt_in_and_deduplicate_across_processes(store):
    messages = []

    async def send(message):
        messages.append(message)

    store.start_session("one", "claude", None, "/project", "sticky")
    store.update_session("one", account="a")
    await check_alerts(store, snapshot(store), send=send)
    assert messages == []
    store.set_setting("notifications", True)
    await check_alerts(store, snapshot(store), send=send)
    store.update_session("one", account="b", reason="quota")
    await check_alerts(store, snapshot(store), send=send)
    await check_alerts(Store(store.root), snapshot(store), send=send)
    assert len(messages) == 1 and "b" in messages[0]


def test_only_explicit_structured_revocation_is_permanent():
    assert revoked_error({"data": {"error": "invalid_grant"}})
    assert not revoked_error({"message": "invalid_grant maybe in a network timeout"})
