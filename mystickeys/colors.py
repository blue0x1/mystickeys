"""Color name parsing helpers."""

from __future__ import annotations

from typing import Tuple

RGB = Tuple[int, int, int]

NAMED = {
    "off": (0, 0, 0),
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "lime": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "aqua": (0, 255, 255),
    "magenta": (255, 0, 255),
    "pink": (255, 64, 160),
    "purple": (160, 0, 255),
    "violet": (160, 0, 255),
    "orange": (255, 90, 0),
    "gold": (255, 160, 0),
    "teal": (0, 160, 160),
    "warmwhite": (255, 200, 120),
}


def _clamp(v: int) -> int:
    return 0 if v < 0 else 255 if v > 255 else int(v)


def scale(color: RGB, brightness: int) -> RGB:
    """Scale an (r,g,b) by a 0-100 brightness percentage."""
    b = max(0, min(100, brightness))
    r, g, bl = color
    return (_clamp(r * b // 100), _clamp(g * b // 100), _clamp(bl * b // 100))


def parse_color(text: str) -> RGB:
    """Parse '#RRGGBB', 'RRGGBB', 'r,g,b' or a named color into (r,g,b)."""
    s = text.strip().lower()
    if s in NAMED:
        return NAMED[s]
    if "," in s:
        parts = [p for p in s.replace(" ", "").split(",") if p != ""]
        if len(parts) != 3:
            raise ValueError(f"expected 'r,g,b', got {text!r}")
        r, g, b = (int(p) for p in parts)
        for v in (r, g, b):
            if not 0 <= v <= 255:
                raise ValueError(f"channel out of range (0-255) in {text!r}")
        return (r, g, b)
    hexs = s[1:] if s.startswith("#") else s
    if len(hexs) == 3:  # shorthand #abc
        hexs = "".join(c * 2 for c in hexs)
    if len(hexs) == 6:
        try:
            return (int(hexs[0:2], 16), int(hexs[2:4], 16), int(hexs[4:6], 16))
        except ValueError:
            pass
    raise ValueError(
        f"unrecognized color {text!r}. Use a name (red), hex (#ff8800) "
        f"or r,g,b (255,136,0)."
    )
