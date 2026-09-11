"""Export the real dashboard with isolated sample data; no accounts or network required."""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from rich.console import CONSOLE_SVG_FORMAT, Console
from rich.terminal_theme import MONOKAI, TerminalTheme

from agent_rotate.dashboard import render, snapshot
from agent_rotate.store import Store

NOW = 1_800_000_000.0
OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "assets"


def sample(store: Store, *, diagnostics: bool):
    accounts = {}
    for provider, name, short, weekly in (
        ("claude", "personal", 42, 58),
        ("claude", "secondary", 16, 24),
        ("codex", "personal", 67, 48),
        ("codex", "secondary", 21, 32),
    ):
        account = store.add(provider, name, f"/sample/{provider}/{name}")
        accounts[provider, name] = account
        windows = [
            {
                "name": "five_hour" if provider == "claude" else "primary",
                "used_percent": short,
                "period_seconds": 18_000,
                "resets_at": NOW + 7200,
            },
            {
                "name": "seven_day" if provider == "claude" else "secondary",
                "used_percent": weekly,
                "period_seconds": 604_800,
                "resets_at": NOW + 3 * 86400,
            },
        ]
        if provider == "codex":
            for window in windows:
                window["bucket"] = "codex"
        store.set_usage(account, windows)
        store.set_health(account, "ready")
    for provider, ident, account, directory in (
        ("claude", "a1b2c3d4", "personal", "/work/api"),
        ("codex", "e5f6a7b8", "secondary", "/work/web"),
    ):
        store.set_pool(provider, "work", ["personal", "secondary"])
        store.start_session(ident, provider, "work", directory, "sticky")
        store.update_session(ident, account=account, reason="initial")
    if diagnostics:
        account = accounts["claude", "personal"]
        _, windows = store.usage(account)
        windows[0].update(used_percent=100, resets_at=NOW + 900)
        store.set_usage(account, windows)
        store.cooldown(account, "*", NOW + 900)
        store.set_health(accounts["claude", "secondary"], "relogin_required", "revoked_login")
        with store.connect() as db:
            db.execute(
                "UPDATE usage SET checked=? WHERE provider='codex' AND name='personal'",
                (NOW - 1200,),
            )
        store.update_session("a1b2c3d4", reason="exhausted")
        store.update_session("e5f6a7b8", reason="quota")
    return snapshot(store)


def main():
    converter = shutil.which("rsvg-convert")
    if not converter:
        raise SystemExit("Install librsvg (rsvg-convert) to render documentation PNGs")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    # Use a local font: documentation images need no remote font or asset requests.
    template = re.sub(r"@font-face \{\{.*?\}\}", "", CONSOLE_SVG_FORMAT, flags=re.S)
    template = template.replace("Fira Code, monospace", "Menlo, monospace")
    theme = TerminalTheme((15, 23, 42), (226, 232, 240), [MONOKAI.ansi_colors[i] for i in range(8)])
    for name, diagnostics in (("dashboard", False), ("routing-health", True)):
        with tempfile.TemporaryDirectory(prefix="agent-rotate-preview-") as directory:
            with patch("time.time", return_value=NOW):
                data = sample(Store(Path(directory) / "state"), diagnostics=diagnostics)
                console = Console(
                    record=True, file=io.StringIO(), width=120, height=40, force_terminal=True
                )
                console.print("$ agent-rotate status --cached", style="bold cyan")
                console.print()
                console.print(render(data))
                svg = console.export_svg(
                    title="Agent Rotate 0.2.0 · SAMPLE DATA",
                    theme=theme,
                    code_format=template,
                    unique_id=name,
                    font_aspect_ratio=0.60205078125,  # Menlo's monospace advance / font size.
                )
            source = Path(directory) / "preview.svg"
            source.write_text(svg)
            target = OUTPUT / f"{name}.png"
            subprocess.run([converter, str(source), "-o", str(target)], check=True)
            print(target.relative_to(OUTPUT.parent.parent))


if __name__ == "__main__":
    main()
