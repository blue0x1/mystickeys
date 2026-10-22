"""mystickeys -- control the RGB backlight of MSI laptop keyboards.

Multi-backend: MysticLight (1462:16xx) and SteelSeries
(1770:ff00 3-zone, 1038:1122 per-key).
"""

from .backends import (  # noqa: F401
    Backend,
    KeyboardError,
    Unsupported,
    detect,
    open_keyboard,
)
from .device import MSIKeyboard, find_hidraw  # noqa: F401

__version__ = "1.2.0"
