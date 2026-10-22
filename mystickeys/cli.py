"""Command-line interface for the MSI keyboard RGB controller (multi-backend)."""

from __future__ import annotations

import argparse
import sys
from typing import List

from . import effects as fx
from . import presets as presets_store
from .backends import (ALL_BACKENDS, KeyboardError, Unsupported, detect_info,
                       open_keyboard)
from .colors import parse_color, scale


def _colors(values: List[str]):
    return [parse_color(v) for v in values]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mystickeys",
        description="Control the RGB backlight on MSI laptop keyboards "
                    "(MysticLight and SteelSeries controllers).",
    )
    p.add_argument("-z", "--zone", default="all",
                   help="target zone: depends on model "
                        "(MysticLight: 1-4/all; SteelSeries: left/middle/right/all)")
    p.add_argument("-b", "--brightness", type=int, default=100, metavar="0-100",
                   help="brightness percent applied to colors (default: 100)")
    p.add_argument("--device", metavar="/dev/hidrawN",
                   help="use this device instead of auto-detecting")
    p.add_argument("--backend", choices=[c.key for c in ALL_BACKENDS],
                   help="force a protocol (use with --device for unlisted "
                        "controllers)")
    p.add_argument("--no-save", action="store_true",
                   help="do not persist to the keyboard's flash (MysticLight)")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("color", help="set a solid color")
    c.add_argument("color", help="name, #RRGGBB, or r,g,b")

    sub.add_parser("off", help="turn the backlight off")
    sub.add_parser("detect", help="show the detected controller and device node")
    sub.add_parser("info", help="list supported controllers / capabilities")
    sub.add_parser("list", help="list all HID devices and whether they match")

    z = sub.add_parser("zones", help="set each zone to its own color (left->right)")
    z.add_argument("colors", nargs="+", metavar="C", help="one color per zone")

    for name, dspeed in (("breath", 3.0), ("cycle", 5.0), ("wave", 3.0)):
        sp = sub.add_parser(name, help=f"{name} effect")
        sp.add_argument("colors", nargs="+", help="one or more colors")
        sp.add_argument("-s", "--speed", type=float, default=dspeed,
                        help="seconds per cycle")
        if name == "wave":
            sp.add_argument("-d", "--direction", choices=["ltr", "rtl"],
                            default="ltr", help="wave direction")

    ef = sub.add_parser("effect", help="run a built-in effect (see 'effects')")
    ef.add_argument("name", help="effect name, e.g. rainbow, ocean, aurora")
    ef.add_argument("-s", "--speed", type=float, default=None,
                    help="seconds per pass, 3-12 like MSI Center "
                         "(default: the effect's own)")
    ef.add_argument("-d", "--direction", choices=["ltr", "rtl"], default="ltr",
                    help="direction for wave-based effects")
    sub.add_parser("effects", help="list the built-in effects")

    lv = sub.add_parser("live", help="run a live effect until Ctrl+C "
                                     "(battery, cpu, temp, music, typing, fire, "
                                     "thunder, lava)")
    lv.add_argument("name", help="battery, cpu, temp, music, typing, fire, "
                                 "thunder or lava; "
                                 "or 'stop' / 'status' for the background one")
    lv.add_argument("-B", "--background", action="store_true",
                    help="keep running after this terminal closes and "
                         "start again at login (stop with: live stop)")
    lv.add_argument("-c", "--color", default="cyan",
                    help="color for 'typing' (default: cyan)")

    nt = sub.add_parser("notify", help="flash the keyboard on notifications "
                                       "(on/off/status/test)")
    nt.add_argument("action", choices=["on", "off", "status", "test", "run"],
                    help="on/off: start or stop the background service; "
                         "test: flash once; run: used by the service")
    nt.add_argument("-c", "--color", default=None,
                    help="flash color (saved; default: white)")

    sub.add_parser("gui", help="launch the graphical color picker")
    return p


def _cmd_detect(device=None, backend=None) -> int:
    found = detect_info(device, backend)
    if not found:
        print("No supported MSI keyboard controller found. Run 'mystickeys list' "
              "to see all HID devices.", file=sys.stderr)
        return 1
    cls, node, vid, pid, how = found
    print(f"Controller : {cls.name}"
          + (" (experimental)" if cls.experimental else ""))
    print(f"USB ID     : {vid:04x}:{pid:04x}  ({how})")
    print(f"Device node: {node}")
    if how != "known USB ID":
        print("Note       : this USB ID is not in the tested list. If it works, "
              "please report it so it can be added.")
    print(f"Zones      : {', '.join(cls.zones)}")
    print(f"Effects    : {'yes' if cls.supports_effects else 'no'}")
    return 0


def _cmd_list() -> int:
    from .backends import _candidates
    from .hidraw import device_name, enumerate_devices
    matches = {hit[1]: hit for hit in _candidates()}
    devices = enumerate_devices()
    if not devices:
        print("No hidraw devices found.", file=sys.stderr)
        return 1
    for node, vid, pid in sorted(devices):
        hit = matches.get(node)
        tag = f"-> {hit[0].key} ({hit[4]})" if hit else "-"
        print(f"{node:<14} {vid:04x}:{pid:04x}  {device_name(node)[:40]:<40} {tag}")
    return 0


def _cmd_live(args) -> int:
    import signal
    import threading
    from . import live
    try:
        if args.name == "stop":
            live.stop_background()
            print("Background live effect stopped.")
            return 0
        if args.name == "status":
            print(live.background_effect() or "none")
            return 0
        if args.background:
            live.start_background(args.name, parse_color(args.color),
                                  args.brightness)
            print(f"Live '{args.name}' runs in the background (also after "
                  "login). Stop it with: mystickeys live stop")
            return 0
    except (KeyboardError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    args.name = live.ALIASES.get(args.name, args.name)
    if args.name not in live.LIVE and args.name != "service":
        print(f"error: unknown live effect {args.name!r}. Choose from: "
              + ", ".join(live.LIVE), file=sys.stderr)
        return 1
    stop = threading.Event()
    # Ctrl+C and `kill` both stop cleanly so the keyboard gets restored
    signal.signal(signal.SIGINT, lambda *a: stop.set())
    signal.signal(signal.SIGTERM, lambda *a: stop.set())
    if args.name == "service":  # what the background service runs
        try:
            live.run_saved(stop)
        except KeyboardError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        return 0
    try:
        kb = open_keyboard(args.device, args.backend)
        with kb:
            cls = live.LIVE[args.name][0]
            n = len(live.physical_zones(kb))
            effect = (cls(n, color=parse_color(args.color))
                      if args.name == "typing" else cls(n))
            print(f"Live '{args.name}' running. Press Ctrl+C to stop.")
            live.run(kb, effect, stop, brightness=args.brightness)
        print("Stopped; keyboard restored to its saved effect.")
    except (KeyboardError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def _cmd_notify(args) -> int:
    from . import notify
    try:
        color = parse_color(args.color) if args.color else None
        if args.action == "on":
            notify.enable(color)
            c = notify.load_settings()["color"]
            print(f"Notification flash is ON (color {c[0]},{c[1]},{c[2]}); "
                  "it starts with your login. Turn off: mystickeys notify off")
        elif args.action == "off":
            notify.disable()
            print("Notification flash is OFF.")
        elif args.action == "status":
            print("ON" if notify.is_enabled() else "OFF")
        elif args.action == "test":
            notify.flash(color)
        else:  # run (the service)
            notify.watch()
    except (KeyboardError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass
    return 0


def _cmd_info() -> int:
    print("Supported MSI keyboard controllers:\n")
    for cls in ALL_BACKENDS:
        ids = ", ".join(f"{v:04x}:{p:04x}" for v, p in cls.ids)
        tag = " [experimental]" if cls.experimental else ""
        print(f"  {cls.name}{tag}")
        print(f"      key     : {cls.key}")
        print(f"      USB IDs : {ids}")
        print(f"      zones   : {', '.join(cls.zones)}")
        print(f"      effects : {'yes' if cls.supports_effects else 'no'}\n")
    return 0


def run(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "detect":
        try:
            return _cmd_detect(args.device, args.backend)
        except KeyboardError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    if args.cmd == "list":
        return _cmd_list()
    if args.cmd == "notify":
        return _cmd_notify(args)
    if args.cmd == "live":
        return _cmd_live(args)
    if args.cmd == "effects":
        print("Built-in color waves (run on the keyboard itself, persist "
              "after reboot):\n")
        for e in fx.EFFECTS:
            print(f"  {e.key:<10} {e.description} ({e.speed:g}s)")
        print("\nExample: mystickeys effect ocean -s 10 -d rtl")
        return 0
    if args.cmd == "info":
        return _cmd_info()
    if args.cmd == "gui":
        from .gui import main as gui_main
        return gui_main()

    save = not args.no_save
    bright = args.brightness

    def sc(colors):
        return [scale(c, bright) for c in colors]

    state = None  # (rgb, brightness, {zone: rgb}) to persist for the GUI

    try:
        kb = open_keyboard(args.device, args.backend)
        with kb:
            phys = [z for z in kb.zones if z != "all"]
            if args.cmd == "color":
                rgb = parse_color(args.color)
                kb.set_color(scale(rgb, bright), zone=args.zone, save=save)
                targets = phys if args.zone == "all" else [args.zone]
                state = (rgb, bright, {z: rgb for z in targets})
            elif args.cmd == "off":
                kb.turn_off(zone=args.zone, save=save)
                targets = phys if args.zone == "all" else [args.zone]
                state = ((20, 20, 26), bright, {z: (20, 20, 26) for z in targets})
            elif args.cmd == "zones":
                cols = sc(_colors(args.colors))
                # distinct physical zones, left-to-right, excluding aliases
                seen = set()
                ordered = []
                for z in sorted((z for z in kb.zones if z != "all"),
                                key=lambda z: kb.zones[z]):
                    if kb.zones[z] in seen:
                        continue
                    seen.add(kb.zones[z])
                    ordered.append(z)
                mapping = {ordered[i]: c for i, c in enumerate(cols)
                           if i < len(ordered)}
                kb.set_zone_colors(mapping, save=save)
                raw = _colors(args.colors)
                smap = {ordered[i]: raw[i] for i in range(len(ordered))
                        if i < len(raw)}
                state = (raw[0], bright, smap)
            elif args.cmd == "breath":
                kb.set_breath(sc(_colors(args.colors)), speed=args.speed,
                              zone=args.zone, save=save)
            elif args.cmd == "cycle":
                kb.set_cycle(sc(_colors(args.colors)), speed=args.speed,
                             zone=args.zone, save=save)
            elif args.cmd == "effect":
                fx.apply(kb, fx.get(args.name), brightness=bright, speed=args.speed,
                         direction=1 if args.direction == "ltr" else 0,
                         zone=args.zone, save=save)
            elif args.cmd == "wave":
                direction = 1 if args.direction == "ltr" else 0
                kb.set_wave(sc(_colors(args.colors)), speed=args.speed,
                            direction=direction, zone=args.zone, save=save)
        if state:
            try:
                presets_store.save_state(*state)
            except Exception:
                pass
    except Unsupported as e:
        print(str(e), file=sys.stderr)
        return 2
    except (KeyboardError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
