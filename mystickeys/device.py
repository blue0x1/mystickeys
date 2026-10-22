"""Backward-compatible library API.

The driver internals now live in :mod:`mystickeys.backends` (multi-controller) and
:mod:`mystickeys.hidraw`. This module preserves the original ``MSIKeyboard`` class
and helpers so existing scripts keep working. It targets the MysticLight
controller specifically; for automatic multi-controller detection use
``mystickeys.backends.open_keyboard``.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .backends import KeyboardError, MysticLightBackend, detect_info
from .colors import scale  # noqa: F401  (re-export)

RGB = Tuple[int, int, int]

VENDOR_ID = 0x1462
PRODUCT_IDS = tuple(pid for vid, pid in MysticLightBackend.ids)

ZONE_ALL = 0xFF
ZONE_1 = 0b0001
ZONE_2 = 0b0010
ZONE_3 = 0b0100
ZONE_4 = 0b1000
WAVE_RIGHT_TO_LEFT = 0
WAVE_LEFT_TO_RIGHT = 1

_MASK_TO_NAME = {ZONE_ALL: "all", ZONE_1: "1", ZONE_2: "2", ZONE_3: "3", ZONE_4: "4"}


def find_hidraw() -> Optional[str]:
    """Return the /dev/hidraw node for a MysticLight keyboard, or None."""
    hit = detect_info(backend=MysticLightBackend.key)
    return hit[1] if hit else None


class MSIKeyboard:
    """Thin compatibility wrapper around the MysticLight backend.

    Accepts integer zone masks (ZONE_*) like the original API.
    """

    def __init__(self, path: Optional[str] = None):
        hit = None
        if path is None:
            hit = detect_info(backend=MysticLightBackend.key)
            if not hit:
                raise KeyboardError("MSI MysticLight keyboard not found.")
            path, vid, pid = hit[1:4]
        else:
            vid, pid = VENDOR_ID, PRODUCT_IDS[0]
        self._be = MysticLightBackend(path, vid, pid)

    def __enter__(self):
        self._be.dev.open()
        return self

    def __exit__(self, *exc):
        self._be.dev.close()

    open = property(lambda self: self._be.dev.open)
    close = property(lambda self: self._be.dev.close)

    @staticmethod
    def _zn(mask: int) -> str:
        return _MASK_TO_NAME.get(mask, "all")

    def set_color(self, color: RGB, zones: int = ZONE_ALL, save: bool = True):
        self._be.set_color(color, self._zn(zones), save)

    def set_zone_colors(self, zone_colors: Dict[int, RGB], save: bool = True):
        self._be.set_zone_colors({self._zn(m): c for m, c in zone_colors.items()}, save)

    def turn_off(self, zones: int = ZONE_ALL, save: bool = True):
        self._be.turn_off(self._zn(zones), save)

    def set_breath(self, colors: List[RGB], speed=3.0, zones=ZONE_ALL, save=True):
        self._be.set_breath(colors, speed, self._zn(zones), save)

    def set_color_cycle(self, colors: List[RGB], speed=5.0, zones=ZONE_ALL, save=True):
        self._be.set_cycle(colors, speed, self._zn(zones), save)

    def set_wave(self, colors: List[RGB], speed=3.0, direction=WAVE_LEFT_TO_RIGHT,
                 zones=ZONE_ALL, save=True):
        self._be.set_wave(colors, speed, direction, self._zn(zones), save)
