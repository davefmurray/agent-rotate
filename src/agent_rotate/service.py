"""Explicit, reversible installation of our own user service only."""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path


def manage(store, action: str, kind: str):
    binary = shutil.which("agent-rotate")
    if not binary:
        raise ValueError("Install agent-rotate before installing a service")
    name = f"dev.agent-rotate.{kind}"
    if sys.platform == "darwin":
        path = Path.home() / "Library" / "LaunchAgents" / f"{name}.plist"
        target = f"gui/{os.getuid()}"
        if action == "status":
            return {"installed": path.is_file(), "path": str(path), "kind": kind}
        if action == "remove":
            subprocess.run(["launchctl", "bootout", target, str(path)], capture_output=True)
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "Label": name,
                "ProgramArguments": [binary, kind],
                "RunAtLoad": True,
                "KeepAlive": True,
                "EnvironmentVariables": {
                    "AGENT_ROTATE_HOME": str(store.root),
                    "PATH": os.environ.get("PATH", ""),
                },
                "StandardOutPath": "/dev/null",
                "StandardErrorPath": "/dev/null",
            }
            path.write_bytes(plistlib.dumps(payload))
            path.chmod(0o600)
            subprocess.run(["launchctl", "bootout", target, str(path)], capture_output=True)
            result = subprocess.run(
                ["launchctl", "bootstrap", target, str(path)], capture_output=True
            )
            if result.returncode:
                raise ValueError(
                    "Service file created but launchctl failed; check your login session"
                )
    else:
        if kind == "menubar":
            raise ValueError("Menu bar service requires macOS")
        if not shutil.which("systemctl"):
            raise ValueError(
                "User systemd is required; agent-rotate daemon can run in the foreground"
            )
        path = Path.home() / ".config" / "systemd" / "user" / f"{name}.service"
        if action == "status":
            return {"installed": path.is_file(), "path": str(path), "kind": kind}
        if action == "remove":
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", path.name], capture_output=True
            )
            path.unlink(missing_ok=True)
        else:
            # Unit syntax has its own quoting and percent specifiers.
            def quote(value):
                return (
                    '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'
                )

            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "[Unit]\nDescription=Agent Rotate quota monitor\n[Service]\n"
                f"ExecStart={quote(binary)} daemon\n"
                f"Environment={quote('AGENT_ROTATE_HOME=' + str(store.root))}\n"
                f"Environment={quote('PATH=' + os.environ.get('PATH', ''))}\n"
                "Restart=on-failure\nUMask=0077\nStandardOutput=null\nStandardError=null\n"
                "[Install]\nWantedBy=default.target\n"
            )
            path.chmod(0o600)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, capture_output=True)
        if action == "install":
            subprocess.run(
                ["systemctl", "--user", "enable", "--now", path.name],
                check=True,
                capture_output=True,
            )
    return {"installed": action == "install", "path": str(path), "kind": kind}
