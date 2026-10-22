"""Protocol backends for the different MSI laptop keyboard controllers.

Each backend declares the USB (vid, pid) pairs it drives and implements a
common interface. ``open_keyboard()`` auto-detects which controller is present
and returns the right backend.

Coverage
--------
* MysticLightBackend      1462:16xx   MS-156x/160x (Crosshair/Vector/Sword...)
* SteelSeries3ZoneBackend 1770:ff00   older 3-zone SteelSeries (GL/GE/GP...)
                                      -- implemented from documented protocol,
                                         UNTESTED here.
* SteelSeriesPerKeyBackend 1038:1122  per-key SteelSeries (GE/GS/GT/Stealth)
                                      -- recognised, delegates to the dedicated
                                         `msi-perkeyrgb` tool (not reimplemented).

Protocol credits:
  MysticLight  -- natanalt
  SteelSeries  -- MSIKLM / python-msikeys / msi-perkeyrgb projects
"""

from __future__ import annotations

import struct
from typing import Dict, List, Optional, Tuple

from .hidraw import (Descriptor, Hidraw, HidrawError, KeyboardError,  # noqa: F401
                     device_name, enumerate_devices, read_descriptor)

RGB = Tuple[int, int, int]


class Unsupported(KeyboardError):
    """Raised when a backend does not support a requested operation."""


def _clamp(v: int) -> int:
    return 0 if v < 0 else 255 if v > 255 else int(v)


# ===========================================================================
# Base
# ===========================================================================
class Backend:
    name = "generic"
    key = "generic"  # short name for --backend
    ids: Tuple[Tuple[int, int], ...] = ()
    experimental = False  # True for backends implemented from docs but unproven
    full_rgb = True
    supports_effects = False
    # ordered zone labels -> internal mask/id; "all" is required
    zones: Dict[str, int] = {"all": 0xFF}

    @classmethod
    def probe(cls, vid: int, pid: int, desc: Optional[Descriptor],
              name: str) -> bool:
        """True if an *unlisted* device looks like this controller.

        Called only for devices whose (vid, pid) is not in ``ids``. Must be
        conservative: a false match means sending this protocol to a device
        that speaks a different one.
        """
        return False

    def __init__(self, path: str, vid: int, pid: int):
        self.dev = Hidraw(path)
        self.vid = vid
        self.pid = pid
        self.path = path

    def zone_mask(self, name: str) -> int:
        if name not in self.zones:
            raise KeyboardError(
                f"{self.name}: zone '{name}' not valid. "
                f"Choose from: {', '.join(self.zones)}")
        return self.zones[name]

    def __enter__(self):
        self.dev.open()
        return self

    def __exit__(self, *exc):
        self.dev.close()

    # -- interface (override) ---------------------------------------------
    def set_color(self, color: RGB, zone: str = "all", save: bool = True) -> None:
        raise NotImplementedError

    def set_zone_colors(self, zone_colors: Dict[str, RGB], save: bool = True) -> None:
        for z, c in zone_colors.items():
            self.set_color(c, z, save=False)
        if save:
            self._save()

    def turn_off(self, zone: str = "all", save: bool = True) -> None:
        self.set_color((0, 0, 0), zone, save=save)

    def set_breath(self, colors, speed=3.0, zone="all", save=True):
        raise Unsupported(f"{self.name}: breathing effect not supported")

    def set_cycle(self, colors, speed=5.0, zone="all", save=True, hold=0.0):
        raise Unsupported(f"{self.name}: color-cycle effect not supported")

    def set_wave(self, colors, speed=3.0, direction=1, zone="all", save=True,
                 hold=0.0):
        raise Unsupported(f"{self.name}: wave effect not supported")

    def _save(self) -> None:
        pass

    def restore(self) -> None:
        """Go back to the effect saved on the keyboard (if supported)."""


# ===========================================================================
# MysticLight 1462:16xx
# ===========================================================================
class MysticLightBackend(Backend):
    name = "MysticLight (MS-156x/160x)"
    key = "mysticlight"
    ids = ((0x1462, 0x1601), (0x1462, 0x1603), (0x1462, 0x1605),
           (0x1462, 0x1562), (0x1462, 0x1563), (0x1462, 0x1564),
           (0x1462, 0x1570), (0x1462, 0x1572))
    full_rgb = True
    supports_effects = True
    zones = {"all": 0xFF, "1": 0b0001, "2": 0b0010, "3": 0b0100, "4": 0b1000}

    REPORT_WRITE = 2
    REPORT_READ = 1
    PACKET_SIZE = 64
    P_SELECT = 1
    P_EFFECT = 2
    P_SAVE = 0xA0
    P_LOAD = 0xB0  # reload the effects saved in flash
    EFF = {"disable": 0, "steady": 1, "breath": 2, "cycle": 3, "wave": 4}

    @classmethod
    def probe(cls, vid, pid, desc, name):
        # MSI motherboard / desktop Mystic Light controllers share vendor 1462
        # but use PIDs 0x7Bxx-0x7Fxx (board model MS-7Bxx...) and a different
        # protocol, so never touch them.
        if vid != 0x1462 or 0x7B00 <= pid <= 0x7FFF or desc is None:
            return False
        # Laptop signature: vendor-defined page with 64-byte feature
        # reports 1 (read) and 2 (write).
        return (desc.vendor_defined
                and desc.feature_size(cls.REPORT_READ) == cls.PACKET_SIZE
                and desc.feature_size(cls.REPORT_WRITE) == cls.PACKET_SIZE)

    def _packet(self, pid: int, payload: bytes = b"") -> None:
        buf = bytearray([self.REPORT_WRITE, pid]) + payload
        buf = buf.ljust(self.PACKET_SIZE, b"\x00")
        self.dev.send_feature(bytes(buf))
        self.dev.get_feature(self.REPORT_READ, self.PACKET_SIZE)

    def _select(self, mask: int) -> None:
        self._packet(self.P_SELECT, bytes([mask & 0xFF]))

    MAX_KEYFRAMES = 10  # the MCU ignores packets with more

    @classmethod
    def _keyframes(cls, colors: List[RGB],
                   hold: float = 0.0) -> List[Tuple[int, RGB]]:
        """Turn colors into (time 0-100, rgb) keyframes the MCU accepts.

        The animation only runs if a keyframe has time 100, and it does not
        wrap around by itself, so the first color is repeated at time 100.
        One color becomes [c@0, c@100], which is what MSI's own software sends.

        ``hold`` (0-1) keeps each color still for that share of its turn
        before fading to the next, which gives crisp, flash-like changes.
        """
        colors = list(colors) or [(0, 0, 0)]
        per_color = 2 if hold > 0 else 1
        limit = (cls.MAX_KEYFRAMES - 1) // per_color
        if len(colors) > limit:
            raise KeyboardError(
                f"too many colors ({len(colors)}); this keyboard accepts at "
                f"most {limit} per effect" + (" with hold" if hold else ""))
        slot = 100 / len(colors)
        frames = []
        for i, c in enumerate(colors):
            frames.append((round(i * slot), c))
            if hold > 0:
                frames.append((round(i * slot + slot * min(hold, 0.95)), c))
        frames.append((100, colors[0]))
        return frames

    def _effect(self, eff: int, colors: List[RGB], speed=3.0, direction=1,
                hold: float = 0.0) -> None:
        ticks = round(speed * 100)  # u16: cycle length in 1/100 s
        if not 1 <= ticks <= 0xFFFF:
            raise KeyboardError(f"speed must be between 0.01 and 655 seconds, "
                                f"got {speed}")
        payload = bytearray([eff & 0xFF])
        payload.extend(struct.pack("<H", ticks))
        payload.extend([0, 0, 15, 1])
        payload.append(direction & 0xFF)
        for t, (r, g, b) in self._keyframes(colors, hold):
            payload.extend([t, _clamp(r), _clamp(g), _clamp(b)])
        self._packet(self.P_EFFECT, bytes(payload))

    def _save(self) -> None:
        self._packet(self.P_SAVE)

    def restore(self) -> None:
        self._packet(self.P_LOAD)

    def set_color(self, color, zone="all", save=True):
        self._select(self.zone_mask(zone))
        self._effect(self.EFF["steady"], [color])
        if save:
            self._save()

    def turn_off(self, zone="all", save=True):
        self._select(self.zone_mask(zone))
        self._effect(self.EFF["disable"], [(0, 0, 0)])
        if save:
            self._save()

    def set_breath(self, colors, speed=3.0, zone="all", save=True):
        self._select(self.zone_mask(zone))
        self._effect(self.EFF["breath"], colors, speed)
        if save:
            self._save()

    def set_cycle(self, colors, speed=5.0, zone="all", save=True, hold=0.0):
        self._select(self.zone_mask(zone))
        self._effect(self.EFF["cycle"], colors, speed, hold=hold)
        if save:
            self._save()

    def set_wave(self, colors, speed=3.0, direction=1, zone="all", save=True,
                 hold=0.0):
        self._select(self.zone_mask(zone))
        self._effect(self.EFF["wave"], colors, speed, direction, hold=hold)
        if save:
            self._save()


# ===========================================================================
# SteelSeries 3-zone 1770:ff00  (untested)
# ===========================================================================
class SteelSeries3ZoneBackend(Backend):
    name = "SteelSeries 3-zone"
    key = "steelseries-3zone"
    ids = ((0x1770, 0xFF00),)
    experimental = True
    full_rgb = True
    supports_effects = True
    # left/middle/right regions; map numeric aliases for a uniform CLI
    zones = {"all": 0, "left": 1, "middle": 2, "right": 3,
             "1": 1, "2": 2, "3": 3}

    REPORT = 0x01
    CMD_COLOR = 0x42
    CMD_MODE = 0x41
    TAIL = 0xEC
    MODE = {"normal": 1, "gaming": 2, "breathe": 3, "wave": 4}

    def _color(self, region: int, r: int, g: int, b: int) -> None:
        self.dev.send_feature(bytes([self.REPORT, 0x02, self.CMD_COLOR, region,
                                     _clamp(r), _clamp(g), _clamp(b), self.TAIL]))

    def _mode(self, mode: int) -> None:
        self.dev.send_feature(bytes([self.REPORT, 0x02, self.CMD_MODE, mode,
                                     0, 0, 0, self.TAIL]))

    def set_color(self, color, zone="all", save=True):
        r, g, b = color
        regions = (1, 2, 3) if self.zone_mask(zone) == 0 else (self.zone_mask(zone),)
        for region in regions:
            self._color(region, r, g, b)
        self._mode(self.MODE["normal"])

    def turn_off(self, zone="all", save=True):
        self.set_color((0, 0, 0), zone, save=save)

    def set_breath(self, colors, speed=3.0, zone="all", save=True):
        self.set_color(colors[0], zone, save=False)
        self._mode(self.MODE["breathe"])

    def set_wave(self, colors, speed=3.0, direction=1, zone="all", save=True,
                 hold=0.0):
        if colors:
            self.set_color(colors[0], zone, save=False)
        self._mode(self.MODE["wave"])


# ===========================================================================
# SteelSeries per-key 1038:1122  (recognised, delegated)
# ===========================================================================
class SteelSeriesPerKeyBackend(Backend):
    name = "SteelSeries per-key"
    key = "steelseries-perkey"

    @classmethod
    def probe(cls, vid, pid, desc, name):
        # Other SteelSeries keyboards built into MSI laptops report as "KLC"
        return vid == 0x1038 and "klc" in name.lower()
    ids = ((0x1038, 0x1122),)
    experimental = True

    def __enter__(self):
        raise Unsupported(
            "Per-key SteelSeries keyboard (1038:1122) detected. This controller "
            "has a complex per-key protocol best handled by the dedicated tool "
            "`msi-perkeyrgb` (pipx install msi-perkeyrgb). Example:\n"
            "    sudo msi-perkeyrgb -m GE63 -s steady -c ff0000")


# ===========================================================================
# Registry / dispatch
# ===========================================================================
ALL_BACKENDS = (
    MysticLightBackend,
    SteelSeries3ZoneBackend,
    SteelSeriesPerKeyBackend,
)


def _candidates():
    """Yield (BackendClass, node, vid, pid, how) for every matching device.

    Exact USB-ID matches come first, then devices that only pass a
    backend's descriptor check.
    """
    devices = enumerate_devices()
    for cls in ALL_BACKENDS:
        for node, vid, pid in devices:
            if (vid, pid) in cls.ids:
                yield (cls, node, vid, pid, "known USB ID")
    for cls in ALL_BACKENDS:
        for node, vid, pid in devices:
            if (vid, pid) in cls.ids:
                continue
            if cls.probe(vid, pid, read_descriptor(node), device_name(node)):
                yield (cls, node, vid, pid, "matched by HID descriptor")


def backend_by_key(key: str) -> type:
    for cls in ALL_BACKENDS:
        if cls.key == key:
            return cls
    raise KeyboardError(f"unknown backend {key!r}. Choose from: "
                        + ", ".join(c.key for c in ALL_BACKENDS))


def detect_info(device: Optional[str] = None,
                backend: Optional[str] = None
                ) -> Optional[Tuple[type, str, int, int, str]]:
    """Like detect(), plus how the match was made.

    ``device`` (/dev/hidrawN) and ``backend`` (a Backend.key) force the
    choice instead of auto-detecting.
    """
    if device:
        device = device if device.startswith("/dev/") else "/dev/" + device
        ids = {n: (v, p) for n, v, p in enumerate_devices()}
        if device not in ids:
            raise KeyboardError(f"{device} is not a hidraw device")
        vid, pid = ids[device]
        if backend:
            return (backend_by_key(backend), device, vid, pid, "forced")
        for hit in _candidates():
            if hit[1] == device:
                return hit
        raise KeyboardError(
            f"{device} ({vid:04x}:{pid:04x}) is not a recognised controller. "
            f"Pass --backend to force one.")
    for hit in _candidates():
        if backend is None or hit[0].key == backend:
            return hit
    return None


def detect() -> Optional[Tuple[type, str, int, int]]:
    """Return (BackendClass, node, vid, pid) for the first MSI controller found."""
    hit = detect_info()
    return hit[:4] if hit else None


def open_keyboard(device: Optional[str] = None,
                  backend: Optional[str] = None) -> Backend:
    """Detect and return an (unopened) backend; raise if nothing supported."""
    found = detect_info(device, backend)
    if not found:
        raise KeyboardError(
            "No supported MSI keyboard controller found. Run 'mystickeys list' "
            "to see all HID devices, then try --device /dev/hidrawN "
            "--backend NAME.")
    cls, node, vid, pid, _how = found
    return cls(node, vid, pid)
