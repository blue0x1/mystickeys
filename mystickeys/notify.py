"""Flash the keyboard when a desktop notification arrives.

A feature, not an effect: when it's on, a small background service
(systemd --user) watches the session bus for notifications and briefly
flashes the keyboard, then returns it to whatever it was showing.

Only the fact that a notification arrived (and which app sent it, for the
optional ignore list) is used; titles and message text are never read.
Nothing flashes while the desktop's Do Not Disturb mode is on.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from typing import Dict, Optional, Tuple

from . import presets, service
from .backends import KeyboardError, open_keyboard

RGB = Tuple[int, int, int]
SERVICE = "mystickeys-notify.service"
DEFAULTS = {"color": [255, 255, 255], "ignore": []}
DEBOUNCE = 1.5  # seconds: a burst of notifications gives one flash

_MONITOR = ["dbus-monitor", "--session",
            "type='method_call',interface='org.freedesktop.Notifications',"
            "member='Notify'"]


# -- settings ----------------------------------------------------------------
def _settings_path() -> str:
    return os.path.join(presets._dir(), "notify.json")


def load_settings() -> Dict:
    data = dict(DEFAULTS)
    try:
        with open(_settings_path()) as fh:
            data.update(json.load(fh))
    except (OSError, ValueError):
        pass
    return data


def save_settings(**changes) -> Dict:
    data = load_settings()
    data.update(changes)
    os.makedirs(presets._dir(), exist_ok=True)
    tmp = _settings_path() + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, _settings_path())
    return data


# -- the flash ---------------------------------------------------------------
def flash(color: Optional[RGB] = None) -> None:
    """Two quick blinks on the whole keyboard, then back to normal."""
    color = tuple(color or load_settings()["color"])
    kb = open_keyboard()
    with kb:
        kb.dev.settle = 0.0
        with kb.dev.locked():  # live effects pause while we flash
            for on in (True, False, True):
                kb.set_color(color if on else (0, 0, 0), save=False)
                time.sleep(0.15 if on else 0.1)
            kb.restore()  # the saved effect; a running live effect redraws


def _dnd_on() -> bool:
    """True if the desktop's Do Not Disturb mode is on."""
    try:
        out = subprocess.run(
            ["busctl", "--user", "get-property", "org.freedesktop.Notifications",
             "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
             "Inhibited"], capture_output=True, text=True, timeout=2).stdout
        return out.strip() == "b true"
    except (OSError, subprocess.SubprocessError):
        return False


def watch() -> None:
    """Run forever: flash on every notification (the service runs this)."""
    if not shutil.which("dbus-monitor"):
        raise KeyboardError("dbus-monitor not found (install dbus-bin)")
    last = 0.0
    while True:
        proc = subprocess.Popen(_MONITOR, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True)
        want_app = False
        for line in proc.stdout:
            if line.startswith("method call") and "member=Notify" in line:
                want_app = True  # the next line is the sending app's name
                continue
            if not want_app:
                continue
            want_app = False
            app = line.strip().removeprefix("string ").strip('"')
            settings = load_settings()  # re-read so changes apply at once
            if app in settings.get("ignore", []):
                continue
            now = time.monotonic()
            if now - last < DEBOUNCE or _dnd_on():
                continue
            last = now
            try:
                flash(settings["color"])
            except KeyboardError as e:
                print(f"flash failed: {e}", file=sys.stderr, flush=True)
        proc.wait()
        time.sleep(2)  # monitor exited (bus restart?): try again


# -- on / off (a systemd user service) ---------------------------------------
def enable(color: Optional[RGB] = None) -> None:
    if color:
        save_settings(color=list(color))
    service.install(SERVICE, "flash the keyboard on notifications", "notify run")


def disable() -> None:
    service.remove(SERVICE)


def is_enabled() -> bool:
    return service.is_active(SERVICE)
