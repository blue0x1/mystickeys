"""Live effects: the app computes zone colors many times per second.

Unlike the presets in :mod:`effects` these need MysticKeys running. They
only ever send "steady" colors and never write the keyboard's flash (which
wears out), and when they stop the keyboard reloads its saved effect.

Effects
-------
battery  zones fill with the charge level; the next zone pulses while charging
cpu      zones fill with CPU load, green -> yellow -> red
temp     zones fill with CPU temperature (40-95 C), blue -> green -> red
fire     every zone flickers on its own like a flame
thunder  dim blue sky with sudden white strikes
lava     slow purple, pink and orange blobs drifting between zones
music    4-band equalizer of whatever is playing (needs `parec`)
typing   the zone you type in lights up and fades (reads /dev/input; only
         the zone is used, keys are never stored)
"""

from __future__ import annotations

import array
import glob
import math
import os
import select
import struct
import subprocess
import threading
import time
from typing import Callable, List, Optional, Tuple

from .backends import KeyboardError
from .colors import scale

RGB = Tuple[int, int, int]


def _read(path: str) -> str:
    """Read a small text file (sysfs/procfs) and close it right away."""
    with open(path) as fh:
        return fh.read()


def _mix(a: RGB, b: RGB, t: float) -> RGB:
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _dim(c: RGB, f: float) -> RGB:
    f = max(0.0, min(1.0, f))
    return tuple(int(v * f) for v in c)


def _ramp(stops: List[RGB], t: float) -> RGB:
    """Color at position t (0-1) along evenly spaced color stops."""
    t = max(0.0, min(1.0, t)) * (len(stops) - 1)
    i = min(int(t), len(stops) - 2)
    return _mix(stops[i], stops[i + 1], t - i)


def _bar(level: float, n: int, color_at: Callable[[float], RGB]) -> List[RGB]:
    """Fill n zones left to right to `level` (0-1); the last zone fades in."""
    out = []
    for i in range(n):
        part = level * n - i  # how full this zone is
        out.append(_dim(color_at((i + 1) / n), part) if part > 0 else (0, 0, 0))
    return out


GREEN, YELLOW, RED = (0, 255, 0), (255, 200, 0), (255, 0, 0)
BLUE = (0, 80, 255)


# ---------------------------------------------------------------------------
# Effects: frame(now) -> one RGB per zone, left to right
# ---------------------------------------------------------------------------
class LiveEffect:
    fps = 30

    def __init__(self, zones: int):
        self.n = zones

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def frame(self, now: float) -> List[RGB]:
        raise NotImplementedError


class Battery(LiveEffect):
    fps = 20

    def __init__(self, zones):
        super().__init__(zones)
        bats = sorted(glob.glob("/sys/class/power_supply/BAT*"))
        if not bats:
            raise KeyboardError("no battery found in /sys/class/power_supply")
        self.path = bats[0]
        self._read_at = 0.0
        self.level, self.charging = 1.0, False

    def _read(self, now):
        if now - self._read_at < 5:
            return
        self._read_at = now
        try:
            self.level = int(_read(self.path + "/capacity")) / 100
            status = _read(self.path + "/status").strip()
            self.charging = status == "Charging"
        except (OSError, ValueError):
            pass

    def frame(self, now):
        self._read(now)
        color = _ramp([RED, YELLOW, GREEN], (self.level - 0.1) / 0.6)
        lit = self.level * self.n
        out = []
        pulse = 0.5 + 0.5 * math.sin(now * 3)
        for i in range(self.n):
            part = lit - i
            if part >= 1:
                out.append(color)
            elif part > 0:
                # the partly-full zone: dim, or pulsing while charging
                out.append(_dim(color, 0.15 + 0.85 * (pulse if self.charging
                                                     else part)))
            else:
                out.append((0, 0, 0))
        if self.level <= 0.15 and not self.charging:  # low: whole bar breathes
            out = [_dim(RED, 0.2 + 0.8 * pulse) if c != (0, 0, 0) else c
                   for c in out]
        return out


class Cpu(LiveEffect):
    def __init__(self, zones):
        super().__init__(zones)
        self._prev = self._times()
        self._sample_at = 0.0
        self.target = self.shown = 0.0

    @staticmethod
    def _times():
        with open("/proc/stat") as fh:
            vals = [int(v) for v in fh.readline().split()[1:]]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        return idle, sum(vals)

    def frame(self, now):
        if now - self._sample_at >= 0.5:
            self._sample_at = now
            idle, total = self._times()
            d_idle, d_total = idle - self._prev[0], total - self._prev[1]
            self._prev = (idle, total)
            if d_total > 0:
                self.target = 1 - d_idle / d_total
        self.shown += (self.target - self.shown) * 0.15  # smooth movement
        return _bar(self.shown, self.n, lambda t: _ramp([GREEN, YELLOW, RED], t))


class Temp(LiveEffect):
    LOW, HIGH = 40.0, 95.0  # degrees C mapped to empty / full

    def __init__(self, zones):
        super().__init__(zones)
        self.path = self._sensor()
        self._read_at = 0.0
        self.target = self.shown = 0.0

    @staticmethod
    def _sensor() -> str:
        for want in ("coretemp", "k10temp", "zenpower", "acpitz"):
            for hw in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
                try:
                    name = _read(hw + "/name").strip()
                except OSError:
                    continue
                if name == want and os.path.exists(hw + "/temp1_input"):
                    return hw + "/temp1_input"
        raise KeyboardError("no CPU temperature sensor found")

    def frame(self, now):
        if now - self._read_at >= 1:
            self._read_at = now
            try:
                c = int(_read(self.path)) / 1000
                self.target = (c - self.LOW) / (self.HIGH - self.LOW)
            except (OSError, ValueError):
                pass
        self.shown += (self.target - self.shown) * 0.1
        level = max(0.03, min(1.0, self.shown))
        return _bar(level, self.n, lambda t: _ramp([BLUE, GREEN, YELLOW, RED], t))


class Fire(LiveEffect):
    """Each zone flickers on its own like a flame: smooth, never jumpy."""
    fps = 30
    # ember -> red -> orange -> yellow-orange (orange/yellow checked by eye
    # on real hardware; similar reds looked identical, so the range is wide)
    STOPS = [(90, 0, 0), (255, 0, 0), (255, 60, 0), (255, 128, 0), (255, 175, 0)]
    JITTER = 0.035   # random movement per frame
    SMOOTH = 0.08    # how quickly a zone follows its target (lower = calmer)
    FLARE, DIP = 0.006, 0.003  # chance per frame

    def __init__(self, zones, seed=None):
        super().__init__(zones)
        import random
        self.rng = random.Random(seed)
        self.heat = [0.6] * zones
        self.target = [0.6] * zones

    def frame(self, now):
        rng = self.rng
        for i in range(self.n):
            # wander around a warm middle, with the occasional flare or dip
            t = (self.target[i] + rng.gauss(0, self.JITTER)
                 + (0.6 - self.target[i]) * 0.03)
            r = rng.random()
            if r < self.FLARE:
                t = rng.uniform(0.85, 1.0)
            elif r < self.FLARE + self.DIP:
                t = rng.uniform(0.2, 0.35)
            self.target[i] = max(0.0, min(1.0, t))
            self.heat[i] += (self.target[i] - self.heat[i]) * self.SMOOTH
        # neighbours pull on each other a little so the flames look connected
        h = self.heat
        mixed = [(h[max(i - 1, 0)] + 2 * h[i] + h[min(i + 1, self.n - 1)]) / 4
                 for i in range(self.n)]
        return [_dim(_ramp(self.STOPS, x), 0.5 + 0.5 * x) for x in mixed]


class Thunder(LiveEffect):
    """Dim, slowly shifting blue sky with sudden white strikes."""
    fps = 40
    SKY = (0, 25, 110)
    BOLT = (225, 235, 255)
    GAP = (1.5, 5.0)    # seconds between strikes
    DECAY = 0.12        # seconds for a flicker to fade to ~37%

    def __init__(self, zones, seed=None):
        super().__init__(zones)
        import random
        self.rng = random.Random(seed)
        self.flickers = []  # (start time, zones hit, strength)
        self.next_strike = None

    def _strike(self, now):
        rng = self.rng
        if rng.random() < 0.25:
            hit = list(range(self.n))  # the whole sky lights up
        else:
            first = rng.randrange(self.n)
            hit = [first] + ([first + 1] if first + 1 < self.n
                             and rng.random() < 0.5 else [])
        t = now
        for _ in range(rng.choice((1, 2, 2, 3))):  # a strike = 1-3 flickers
            self.flickers.append((t, hit, rng.uniform(0.7, 1.0)))
            t += rng.uniform(0.07, 0.18)

    def frame(self, now):
        if self.next_strike is None:
            self.next_strike = now + self.rng.uniform(0.3, 1.0)
        if now >= self.next_strike:
            self._strike(now)
            self.next_strike = now + self.rng.uniform(*self.GAP)
        self.flickers = [f for f in self.flickers if now - f[0] < 1.0]
        out = []
        for i in range(self.n):
            # the sky breathes a little, each zone at its own pace
            sky = _dim(self.SKY, 0.6 + 0.4 * math.sin(now * 0.4 + i * 1.7) ** 2)
            glow = 0.0
            for start, hit, strength in self.flickers:
                if i in hit and now >= start:
                    glow = max(glow, strength * math.exp(-(now - start) / self.DECAY))
            out.append(_mix(sky, self.BOLT, glow))
        return out


class LavaLamp(LiveEffect):
    """Slow blobs of purple, pink and orange drifting between zones."""
    fps = 20
    # (color, seconds per sway, phase) - different speeds so it never repeats
    BLOBS = [((128, 0, 255), 23.0, 0.0),
             ((255, 0, 128), 31.0, 2.1),
             ((255, 110, 0), 41.0, 4.2)]
    WIDTH = 0.9  # blob size, in zones

    def frame(self, now):
        span = self.n - 1
        pos = [span / 2 + span / 2 * math.sin(2 * math.pi * now / period + phase)
               for _c, period, phase in self.BLOBS]
        out = []
        for i in range(self.n):
            weights = [math.exp(-((i - p) ** 2) / (2 * self.WIDTH ** 2)) for p in pos]
            total = sum(weights) or 1.0
            color = tuple(int(sum(w * b[0][k] for w, b in zip(weights, self.BLOBS))
                              / total) for k in range(3))
            # zones between blobs glow softer, like wax in the dark
            out.append(_dim(color, 0.45 + 0.55 * min(1.0, max(weights))))
        return out


class Music(LiveEffect):
    """4-band equalizer from the default output's monitor, via parec."""
    RATE = 8000
    # one-pole low-pass cutoffs (Hz) that split the signal into bands
    CUTS = (180.0, 700.0, 2200.0)
    COLORS = [(255, 0, 60), (255, 120, 0), (0, 255, 80), (0, 120, 255)]

    def __init__(self, zones):
        super().__init__(zones)
        self.proc: Optional[subprocess.Popen] = None
        self.levels = [0.0] * 4
        self.shown = [0.0] * 4
        self.peak = [1e-3] * 4
        self._k = [1 - math.exp(-2 * math.pi * f / self.RATE) for f in self.CUTS]
        self._lp = [0.0, 0.0, 0.0]
        self._thread = None
        self._lock = threading.Lock()

    def start(self):
        cmd = ["parec", "--format=s16le", f"--rate={self.RATE}", "--channels=1",
               "--latency-msec=20"]
        try:
            sink = subprocess.run(["pactl", "get-default-sink"],
                                  capture_output=True, text=True,
                                  timeout=3).stdout.strip()
            if sink:
                cmd.append(f"--device={sink}.monitor")
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL)
        except OSError as e:
            raise KeyboardError(f"cannot capture audio (parec): {e}") from e
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def stop(self):
        if self.proc:
            self.proc.terminate()
            self.proc = None

    def _reader(self):
        chunk = self.RATE // 50 * 2  # 20 ms of 16-bit samples
        k1, k2, k3 = self._k
        while self.proc and self.proc.stdout:
            data = self.proc.stdout.read(chunk)
            if not data:
                break
            samples = array.array("h", data[: len(data) // 2 * 2])
            l1, l2, l3 = self._lp
            e = [0.0, 0.0, 0.0, 0.0]
            for s in samples:
                x = s / 32768.0
                l1 += k1 * (x - l1)
                l2 += k2 * (x - l2)
                l3 += k3 * (x - l3)
                b = (l1, l2 - l1, l3 - l2, x - l3)
                e[0] += b[0] * b[0]
                e[1] += b[1] * b[1]
                e[2] += b[2] * b[2]
                e[3] += b[3] * b[3]
            self._lp = [l1, l2, l3]
            n = max(1, len(samples))
            with self._lock:
                self.levels = [math.sqrt(v / n) for v in e]

    def frame(self, now):
        with self._lock:
            levels = list(self.levels)
        out = []
        for i in range(4):
            # auto-gain: compare each band with its own slowly-decaying peak
            self.peak[i] = max(levels[i], self.peak[i] * 0.995, 1e-3)
            target = levels[i] / self.peak[i] if levels[i] > 2e-4 else 0.0
            # fast attack, slower fall, like a real meter
            rate = 0.6 if target > self.shown[i] else 0.15
            self.shown[i] += (target - self.shown[i]) * rate
            out.append(_dim(self.COLORS[i], self.shown[i] ** 1.5))
        # fewer than 4 zones (3-zone keyboards): merge the top two bands
        return out[: self.n - 1] + [out[-1]] if self.n < 4 else out


# Typing: x position (in key widths, 0-15) of each Linux key code on a
# laptop ANSI layout. Only used to decide which zone a key belongs to.
def _row(codes, start=0.0, widths=None):
    pos, x = {}, start
    for i, code in enumerate(codes):
        w = widths.get(i, 1.0) if widths else 1.0
        if code:
            pos[code] = x + w / 2
        x += w
    return pos


_KEY_X = {}
_KEY_X.update(_row([1, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 87, 88, 110, 111],
                   widths={}))                                     # Esc, F1-F12
_KEY_X.update(_row([41, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14],
                   widths={13: 2.0}))                             # ` 1 ... Bksp
_KEY_X.update(_row([15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 43],
                   widths={0: 1.5, 13: 1.5}))                     # Tab Q ... \
_KEY_X.update(_row([58, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 28],
                   widths={0: 1.75, 12: 2.25}))                   # Caps A ... Enter
_KEY_X.update(_row([42, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54],
                   widths={0: 2.25, 11: 2.75}))                   # Shift Z ... Shift
_KEY_X.update(_row([29, 0, 125, 56, 57, 100, 97, 105, 108, 106],
                   widths={4: 5.0}))                              # Ctrl ... arrows
_KEY_X[103] = 12.5                                                 # up arrow
for _code in (102, 104, 107, 109, 99, 119):  # Home PgUp End PgDn PrtSc Pause
    _KEY_X[_code] = 14.5
_LAYOUT_W = 15.0

EV_KEY = 1
_EVENT = struct.Struct("llHHi")  # struct input_event on 64-bit Linux


def find_keyboard() -> str:
    """Return the /dev/input/eventN of the built-in keyboard."""
    try:
        text = _read("/proc/bus/input/devices")
    except OSError as e:
        raise KeyboardError(f"cannot list input devices: {e}") from e
    best = None
    for block in text.split("\n\n"):
        name = next((l.split("=", 1)[1].strip('"') for l in block.splitlines()
                     if l.startswith("N: Name=")), "")
        handlers = next((l for l in block.splitlines()
                         if l.startswith("H: Handlers=")), "")
        ev = next((h for h in handlers.split() if h.startswith("event")), None)
        if not ev or "kbd" not in handlers:
            continue
        if "AT Translated" in name or "keyboard" in name.lower():
            best = best or "/dev/input/" + ev
            if "AT Translated" in name:  # the laptop's own keyboard
                return "/dev/input/" + ev
    if not best:
        raise KeyboardError("no keyboard input device found")
    return best


class Typing(LiveEffect):
    fps = 40
    FADE = 0.35  # seconds for a flash to fade to half

    def __init__(self, zones, color: RGB = (0, 200, 255), idle: float = 0.08):
        super().__init__(zones)
        self.color, self.idle = color, idle
        self.heat = [0.0] * zones
        self.fd: Optional[int] = None
        self._last = time.monotonic()

    def start(self):
        node = find_keyboard()
        try:
            self.fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
        except PermissionError as e:
            raise KeyboardError(
                f"no permission to read {node}. Add yourself to the 'input' "
                f"group (sudo usermod -aG input $USER, then log in again) or "
                f"run with sudo.") from e

    def stop(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _zone_of(self, code: int) -> Optional[int]:
        if code >= 71 and code <= 83 or code in (55, 74, 78, 96, 98, 117):
            return self.n - 1  # numpad keys -> rightmost zone
        x = _KEY_X.get(code)
        if x is None:
            return None
        return min(self.n - 1, int(x / _LAYOUT_W * self.n))

    def _poll(self):
        while self.fd is not None:
            r, _, _ = select.select([self.fd], [], [], 0)
            if not r:
                return
            try:
                data = os.read(self.fd, _EVENT.size * 64)
            except BlockingIOError:
                return
            for off in range(0, len(data) - _EVENT.size + 1, _EVENT.size):
                _s, _us, etype, code, value = _EVENT.unpack_from(data, off)
                if etype == EV_KEY and value in (1, 2):  # press / repeat
                    z = self._zone_of(code)
                    if z is not None:
                        self.heat[z] = 1.0

    def frame(self, now):
        self._poll()
        dt, self._last = now - self._last, now
        decay = 0.5 ** (dt / self.FADE)
        out = []
        for i in range(self.n):
            self.heat[i] *= decay
            out.append(_dim(self.color, self.idle + (1 - self.idle) * self.heat[i]))
        return out


LIVE = {
    "battery": (Battery, "zones fill with the battery level"),
    "cpu": (Cpu, "zones fill with CPU load"),
    "temp": (Temp, "zones fill with CPU temperature"),
    "music": (Music, "4-band equalizer of the sound playing"),
    "fire": (Fire, "every zone flickers like a flame"),
    "thunder": (Thunder, "dim blue sky with sudden white strikes"),
    "lava": (LavaLamp, "slow purple, pink and orange blobs drifting"),
    "typing": (Typing, "the zone you type in lights up"),
}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def physical_zones(kb) -> List[str]:
    seen, out = set(), []
    for z in sorted((z for z in kb.zones if z != "all"), key=lambda z: kb.zones[z]):
        if kb.zones[z] not in seen:
            seen.add(kb.zones[z])
            out.append(z)
    return out


def run(kb, effect: LiveEffect, stop: threading.Event,
        brightness=100) -> None:
    """Drive an open backend until `stop` is set, then restore the keyboard.

    ``brightness`` is 0-100, or a function returning it (read every frame,
    so a GUI slider takes effect immediately).
    """
    get_bright = brightness if callable(brightness) else (lambda: brightness)
    zones = physical_zones(kb)
    settle, kb.dev.settle = kb.dev.settle, 0.0  # no pause between packets
    sent: List[Optional[RGB]] = [None] * len(zones)
    redraw_until = 0.0
    effect.start()
    try:
        period = 1.0 / effect.fps
        while not stop.is_set():
            now = time.monotonic()
            bright = get_bright()
            colors = [scale(c, bright) for c in effect.frame(now)[: len(zones)]]
            with kb.dev.locked() as waited:
                if waited > 0.05:
                    # someone else (a notification flash) used the keyboard
                    # and asked it to reload its saved effect, which lands a
                    # moment later: redraw every zone for a little while
                    redraw_until = now + 0.6
                if now < redraw_until:
                    sent = [None] * len(zones)
                for i, c in enumerate(colors):
                    if c != sent[i]:  # only send zones that changed
                        kb.set_color(c, zone=zones[i], save=False)
                        sent[i] = c
            stop.wait(max(0.0, period - (time.monotonic() - now)))
    finally:
        effect.stop()
        kb.dev.settle = settle
        try:
            kb.restore()  # back to the effect saved on the keyboard
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Background service: keeps a live effect running after the app is closed
# ---------------------------------------------------------------------------
LIVE_SERVICE = "mystickeys-live.service"
ALIASES = {"lightning": "thunder"}  # old names still work


def _state_path() -> str:
    from . import presets
    return os.path.join(presets._dir(), "live.json")


def load_state() -> dict:
    import json
    try:
        with open(_state_path()) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(**changes) -> None:
    import json
    from . import presets
    data = load_state()
    data.update(changes)
    os.makedirs(presets._dir(), exist_ok=True)
    tmp = _state_path() + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh)
    os.replace(tmp, _state_path())


def start_background(name: str, color: RGB = (0, 200, 255),
                     brightness: int = 100) -> None:
    """Run a live effect as a service: survives closing the app and logins."""
    from . import service
    name = ALIASES.get(name, name)
    if name not in LIVE:
        raise KeyboardError(f"unknown live effect {name!r}")
    save_state(effect=name, color=list(color), brightness=int(brightness))
    service.install(LIVE_SERVICE, "live keyboard effect", "live service")


def stop_background() -> None:
    from . import service
    service.remove(LIVE_SERVICE)  # the service restores the keyboard on exit


def background_effect() -> Optional[str]:
    """Name of the live effect the service is running, or None."""
    from . import service
    if service.is_active(LIVE_SERVICE):
        return load_state().get("effect")
    return None


def run_saved(stop: threading.Event) -> None:
    """What the service runs: the saved effect, until stopped."""
    from .backends import open_keyboard
    state = load_state()
    name = ALIASES.get(state.get("effect"), state.get("effect"))
    if name not in LIVE:
        raise KeyboardError("no live effect saved; start one from the app")
    cache = {"at": 0.0, "bright": int(state.get("brightness", 100))}

    def brightness():  # follow the app's slider while running
        now = time.monotonic()
        if now - cache["at"] > 1.0:
            cache["at"] = now
            cache["bright"] = int(load_state().get("brightness", cache["bright"]))
        return cache["bright"]

    kb = open_keyboard()
    with kb:
        n = len(physical_zones(kb))
        cls = LIVE[name][0]
        effect = (cls(n, color=tuple(state.get("color", (0, 200, 255))))
                  if name == "typing" else cls(n))
        run(kb, effect, stop, brightness=brightness)
