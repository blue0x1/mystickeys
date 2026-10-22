"""Small helpers for MysticKeys' background services (systemd --user).

Used by the notification flash and by live effects, so both keep running
after the app is closed and start again at login.
"""

from __future__ import annotations

import os
import subprocess
import sys

from .backends import KeyboardError


def unit_path(name: str) -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "systemd", "user", name)


def command() -> str:
    """How a service starts MysticKeys: the project's launcher when running
    from a source checkout, otherwise the installed package."""
    root = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    script = os.path.join(root, "bin", "mystickeys")
    if os.path.isfile(script):
        return f"{sys.executable} {script}"
    return f"{sys.executable} -m mystickeys"


def systemctl(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args],
                          capture_output=True, text=True, timeout=15)


def install(name: str, description: str, args: str) -> None:
    """Write the unit, enable it at login and (re)start it now."""
    if os.geteuid() == 0:
        raise KeyboardError("run this as your normal user, not with sudo")
    os.makedirs(os.path.dirname(unit_path(name)), exist_ok=True)
    with open(unit_path(name), "w") as fh:
        fh.write(f"""[Unit]
Description=MysticKeys: {description}
After=graphical-session.target

[Service]
ExecStart={command()} {args}
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
""")
    for step in (("daemon-reload",), ("enable", name), ("restart", name)):
        r = systemctl(*step)
        if r.returncode != 0:
            raise KeyboardError(f"systemctl --user {' '.join(step)} failed: "
                                f"{r.stderr.strip()}")


def remove(name: str) -> None:
    """Stop the service and don't start it at login any more."""
    systemctl("disable", "--now", name)


def is_active(name: str) -> bool:
    try:
        return systemctl("is-active", name).stdout.strip() == "active"
    except (OSError, subprocess.SubprocessError):
        return False
