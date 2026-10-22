"""`mystickeys report`: a hardware report for testing new laptop models.

Collects facts (laptop model, keyboard USB ID, how it was detected, its HID
descriptor), then runs short visual tests that ask the owner what they see.
The result is Markdown, ready to paste into a GitHub issue.

Privacy: only MSI / SteelSeries / KLM USB devices are listed, and no serial
numbers or other personal data are collected.
"""

from __future__ import annotations

import os
import platform
import time
from typing import Callable, List, Optional, Tuple

from . import __version__
from .backends import KeyboardError, Unsupported, detect_info
from .hidraw import device_name, enumerate_devices, read_descriptor

VENDORS = {0x1462: "MSI", 0x1770: "KLM", 0x1038: "SteelSeries"}

Ask = Callable[[str], str]


def _read(path: str) -> str:
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return "?"


def _distro() -> str:
    try:
        with open("/etc/os-release") as fh:
            for line in fh:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "?"


def facts() -> List[Tuple[str, str]]:
    dmi = "/sys/class/dmi/id/"
    rows = [
        ("Laptop", f"{_read(dmi + 'sys_vendor')} {_read(dmi + 'product_name')}"),
        ("Board", _read(dmi + "board_name")),
        ("BIOS", _read(dmi + "bios_version")),
        ("OS", f"{_distro()}, kernel {platform.release()}"),
        ("mystickeys", __version__),
    ]
    try:
        hit = detect_info()
    except KeyboardError as e:
        hit, rows = None, rows + [("Detection", f"error: {e}")]
    if hit:
        cls, node, vid, pid, how = hit
        rows.append(("Controller", f"{cls.name} at {node}"))
        rows.append(("USB ID", f"{vid:04x}:{pid:04x} ({how})"))
        rows.append(("Zones", ", ".join(z for z in cls.zones if z != "all")))
    elif not any(r[0] == "Detection" for r in rows):
        rows.append(("Controller", "none detected"))
    return rows


def devices() -> List[str]:
    """Every MSI-related hidraw device with its descriptor (for unknown models)."""
    out = []
    for node, vid, pid in sorted(enumerate_devices()):
        if vid not in VENDORS:
            continue
        desc = read_descriptor(node)
        sizes = ""
        if desc:
            feats = {rid: n for (kind, rid), n in desc.reports.items()
                     if kind == "feature"}
            sizes = ", ".join(f"feature {rid}: {n} B" for rid, n in sorted(feats.items()))
        raw = ""
        try:
            with open(f"/sys/class/hidraw/{os.path.basename(node)}/device/"
                      "report_descriptor", "rb") as fh:
                raw = fh.read().hex()
        except OSError:
            pass
        out.append(f"{node} {vid:04x}:{pid:04x} \"{device_name(node)}\"\n"
                   f"  {sizes or 'no feature reports'}\n  descriptor: {raw or '?'}")
    return out


# -- visual tests -------------------------------------------------------------
def _choice(ask: Ask, question: str, options: str) -> str:
    """Ask until one of the single-letter `options` (or s = skip) is given."""
    valid = set(options) | {"s"}
    while True:
        a = ask(f"{question} ").strip().lower()[:1]
        if a in valid:
            return a
        print(f"  please answer one of: {'/'.join(options)} (s = skip)")


def run_tests(kb, ask: Ask) -> List[Tuple[str, str]]:
    """Show patterns (never saved to the keyboard) and record the answers."""
    zones = [z for z in kb.zones if z != "all"]
    seen, physical = set(), []
    for z in zones:  # distinct zones only (some backends have aliases)
        if kb.zones[z] not in seen:
            seen.add(kb.zones[z])
            physical.append(z)
    results = []
    color_names = {"r": "red", "g": "green", "b": "blue", "o": "other", "n": "nothing"}

    print("\nVisual tests: look at the keyboard and answer each question.")
    print("Nothing is saved; your keyboard goes back to normal at the end.\n")

    for want, rgb in (("red", (255, 0, 0)), ("green", (0, 255, 0)), ("blue", (0, 0, 255))):
        kb.set_color(rgb, zone="all", save=False)
        a = _choice(ask, f"What color is the keyboard now? [r]ed [g]reen [b]lue "
                         f"[o]ther [n]othing:", "rgbon")
        got = color_names.get(a, "skipped")
        results.append((f"Whole keyboard {want}", "ok" if got == want else f"saw {got}"))

    kb.set_color((255, 128, 0), zone="all", save=False)
    a = _choice(ask, "Does it look ORANGE? [y]es, [r] looks red, "
                     "[g] looks yellow/green:", "yrg")
    results.append(("Orange (255,128,0)", {"y": "ok", "r": "looks red",
                                           "g": "looks yellow/green"}.get(a, "skipped")))

    for i, z in enumerate(physical):
        kb.set_color((0, 0, 0), zone="all", save=False)
        kb.set_color((255, 255, 255), zone=z, save=False)
        a = _choice(ask, f"Zone {z}: which part is lit? 1=left .. "
                         f"{len(physical)}=right, a=all, n=none:",
                    "".join(str(k + 1) for k in range(len(physical))) + "an")
        expected = str(i + 1)
        results.append((f"Zone {z} alone", "ok" if a == expected else
                        {"a": "whole keyboard lit", "n": "nothing lit",
                         "s": "skipped"}.get(a, f"lit position {a}")))

    try:
        kb.set_breath([(0, 255, 0)], speed=3.0, save=False)
        a = _choice(ask, "Green breathing: does it fade in and out? [y/n]:", "yn")
        results.append(("Breathing", {"y": "ok", "n": "no", "s": "skipped"}[a]))
    except Unsupported:
        results.append(("Breathing", "not supported by this backend"))

    try:
        kb.set_wave([(255, 0, 0), (0, 0, 255)], speed=3.0, direction=1, save=False)
        a = _choice(ask, "Red/blue wave: which way does it move? [l]eft-to-right, "
                         "[r]ight-to-left, [n]ot moving:", "lrn")
        results.append(("Wave", {"l": "ok", "r": "moves right-to-left (reversed)",
                                 "n": "not moving", "s": "skipped"}[a]))
    except Unsupported:
        results.append(("Wave", "not supported by this backend"))
    return results


# -- putting it together --------------------------------------------------------
def build(test: bool = True, ask: Ask = input,
          open_kb: Optional[Callable] = None) -> str:
    rows = facts()
    lines = ["## mystickeys hardware report", "", "| | |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rows]

    results: List[Tuple[str, str]] = []
    note = ""
    if test:
        from .backends import open_keyboard
        try:
            kb = (open_kb or open_keyboard)()
            with kb:
                try:
                    results = run_tests(kb, ask)
                finally:
                    try:
                        time.sleep(0.2)
                        kb.restore()
                    except Exception:
                        pass
        except Unsupported as e:
            note = f"Visual tests skipped: {e}"
        except KeyboardError as e:
            note = f"Visual tests skipped: {e}"
        except (EOFError, KeyboardInterrupt):
            note = "Visual tests stopped early."
    if results:
        lines += ["", "### Visual tests", "", "| Test | Result |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in results]
    if note:
        lines += ["", note]

    devs = devices()
    lines += ["", "<details><summary>MSI-related USB devices</summary>", "", "```"]
    lines += devs or ["none found"]
    lines += ["```", "</details>"]
    return "\n".join(lines) + "\n"
