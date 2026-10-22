"""Persistent user presets for the keyboard RGB tool.

Stored as JSON at ``~/.config/mystickeys/presets.json``. When the GUI runs via
sudo we still target the invoking user's home (``$SUDO_USER``) and fix file
ownership, so presets saved as root remain usable as the normal user.

Each preset is: {"name": str, "rgb": [r, g, b], "brightness": int}
"""

from __future__ import annotations

import json
import os
from typing import Dict, List

RGB = List[int]


def _home() -> str:
    sudo_user = os.environ.get("SUDO_USER")
    if os.geteuid() == 0 and sudo_user and sudo_user != "root":
        try:
            import pwd
            return pwd.getpwnam(sudo_user).pw_dir
        except Exception:
            pass
    return os.path.expanduser("~")


def _dir() -> str:
    new = os.path.join(_home(), ".config", "mystickeys")
    old = os.path.join(_home(), ".config", "msi-rgb")  # name before 1.2.0
    if not os.path.exists(new) and os.path.isdir(old):
        try:
            os.rename(old, new)
        except OSError:
            return old
    return new


def path() -> str:
    return os.path.join(_dir(), "presets.json")


def _fix_owner(target: str) -> None:
    """If running as root for a sudo user, chown the path to that user."""
    sudo_user = os.environ.get("SUDO_USER")
    if os.geteuid() != 0 or not sudo_user or sudo_user == "root":
        return
    try:
        import pwd
        pw = pwd.getpwnam(sudo_user)
        os.chown(target, pw.pw_uid, pw.pw_gid)
    except Exception:
        pass


def _state_path() -> str:
    return os.path.join(_dir(), "state.json")


def load_state() -> Dict:
    """Return the last-applied {rgb, brightness, zones} or {}."""
    try:
        with open(_state_path()) as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def save_state(rgb, brightness: int, zones: Dict = None) -> None:
    data = {
        "rgb": [int(rgb[0]), int(rgb[1]), int(rgb[2])],
        "brightness": int(brightness),
        "zones": {k: [int(v[0]), int(v[1]), int(v[2])]
                  for k, v in (zones or {}).items()},
    }
    d = _dir()
    os.makedirs(d, exist_ok=True)
    _fix_owner(d)
    tmp = _state_path() + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, _state_path())
    _fix_owner(_state_path())


def load() -> List[Dict]:
    try:
        with open(path()) as fh:
            data = json.load(fh)
        if isinstance(data, list):
            out = []
            for p in data:
                if (isinstance(p, dict) and "name" in p and "rgb" in p
                        and len(p["rgb"]) == 3):
                    p.setdefault("brightness", 100)
                    out.append(p)
            return out
    except (OSError, ValueError):
        pass
    return []


def _write(presets: List[Dict]) -> None:
    d = _dir()
    os.makedirs(d, exist_ok=True)
    _fix_owner(d)
    tmp = path() + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(presets, fh, indent=2)
    os.replace(tmp, path())
    _fix_owner(path())


def add(name: str, rgb, brightness: int = 100) -> List[Dict]:
    name = (name or "").strip()[:24] or "preset"
    presets = [p for p in load() if p["name"].lower() != name.lower()]
    presets.append({"name": name,
                    "rgb": [int(rgb[0]), int(rgb[1]), int(rgb[2])],
                    "brightness": int(brightness)})
    _write(presets)
    return presets


def delete(name: str) -> List[Dict]:
    presets = [p for p in load() if p["name"] != name]
    _write(presets)
    return presets
