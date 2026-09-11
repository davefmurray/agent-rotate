"""Optional macOS UI consuming the same cached view as the terminal."""

from __future__ import annotations

import subprocess
import sys

from agent_rotate.dashboard import countdown, snapshot
from agent_rotate.store import Store


def run(store: Store):
    if sys.platform != "darwin":
        raise ValueError("The menu bar is available on macOS; use agent-rotate watch here")
    try:
        import rumps
    except ImportError:
        raise ValueError(
            "Install the menubar extra: uv tool install --force "
            "'agent-rotate[menubar] @ git+https://github.com/davefmurray/agent-rotate'"
        ) from None

    class MenuBar(rumps.App):
        def __init__(self):
            super().__init__("Agent Rotate", title="AR", quit_button=None)
            self.timer = rumps.Timer(self.refresh, 5)
            self.timer.start()
            self.refresh(None)

        def toggle(self, provider, account, enabled):
            store.enable(provider, account, not enabled)
            self.refresh(None)

        def refresh(self, _):
            data = snapshot(store)
            self.menu.clear()
            self.title = f"AR · {len(data['sessions'])}"
            for row in data["accounts"]:
                name = f"{row['provider']} / {row['account']}"
                account = rumps.MenuItem(name)
                account.add(
                    rumps.MenuItem(
                        "Disable" if row["enabled"] else "Enable",
                        callback=lambda _, r=row: self.toggle(
                            r["provider"], r["account"], r["enabled"]
                        ),
                    )
                )
                for w in row["windows"]:
                    account.add(
                        f"{w['name']}: {w['used_percent']:.0f}% · "
                        f"resets {countdown(w.get('resets_at'))}"
                    )
                account.add("Stale reading" if row["stale"] else "Usage current")
                if row["health"]["state"] == "relogin_required":
                    account.add("Re-login required · use agent-rotate health")
                self.menu.add(account)
            self.menu.add(None)
            for s in data["sessions"]:
                self.menu.add(f"{s['id'][:8]} · {s['provider']} / {s['account'] or 'starting'}")
            self.menu.add(rumps.MenuItem("Desktop alerts", callback=self.notifications))
            self.menu["Desktop alerts"].state = store.setting("notifications", False)
            self.menu.add(
                rumps.MenuItem(
                    "Quit Agent Rotate menu bar", callback=lambda _: rumps.quit_application()
                )
            )

        def notifications(self, _):
            store.set_setting("notifications", not store.setting("notifications", False))
            self.refresh(None)

    worker = subprocess.Popen(
        [sys.executable, "-m", "agent_rotate", "daemon"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    def stop_worker():
        if worker.poll() is not None:
            return
        worker.terminate()
        try:
            worker.wait(timeout=4)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait()

    # Cocoa termination may exit without unwinding Python's finally block.
    rumps.events.before_quit.register(stop_worker)
    try:
        MenuBar().run()
    finally:
        stop_worker()
        rumps.events.before_quit.unregister(stop_worker)
