"""Built-in color waves, in the style of MSI Center's Mystic Light.

MSI Center drives this keyboard with five hardware modes (off, steady,
breathing, color cycle, wave), evenly spaced colors and 3-12 second speeds.
The presets below are wave-mode color sets that follow the same rules, so
they run on the keyboard itself (no CPU, keep going with the app closed,
survive reboots).

Colors are chosen to be clearly different from each other: the keyboard's
4 zones blend into their neighbours, so similar shades turn to mush.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from .colors import scale

RGB = Tuple[int, int, int]

# MSI Center allows 3-12 s; we go down to 1 s for faster presets like Police
SPEED_MIN, SPEED_MAX = 1.0, 12.0

# Tuned by eye on real hardware: (255,128,0) reads orange and
# (255,255,0) yellow; pink/yellow/cyan and magenta/cyan sets looked wrong.
RED, ORANGE, YELLOW = (255, 0, 0), (255, 128, 0), (255, 255, 0)
GREEN, CYAN, BLUE = (0, 255, 0), (0, 255, 255), (0, 0, 255)
PURPLE = (128, 0, 255)
TEAL = (0, 255, 128)
WARM_WHITE, OFF = (255, 200, 120), (0, 0, 0)

RAINBOW = [RED, ORANGE, YELLOW, GREEN, CYAN, BLUE, PURPLE]


@dataclass
class Effect:
    key: str
    name: str
    description: str
    colors: List[RGB]
    speed: float = 6.0      # seconds per pass
    mode: str = "wave"      # hardware mode: "wave" or "cycle"
    hold: float = 0.0       # share of each color's turn it stays still


EFFECTS: List[Effect] = [
    Effect("rainbow", "Rainbow", "full rainbow moving across the keyboard",
           RAINBOW, 6.0),
    Effect("ocean", "Ocean", "blue, cyan and teal rolling across",
           [BLUE, CYAN, TEAL], 5.0),
    Effect("aurora", "Aurora", "green, cyan and purple drifting across",
           [GREEN, CYAN, PURPLE], 6.0),
    Effect("neon", "Neon", "yellow and purple stripes moving across",
           [YELLOW, PURPLE] * 2, 4.0),
    Effect("police", "Police", "red and blue chasing across", [RED, BLUE],
           2.0, hold=0.5),
    # one lit stretch among three dark ones, travelling zone by zone
    Effect("train", "Night Train", "a single headlight running across the "
           "dark keyboard", [WARM_WHITE, OFF, OFF, OFF], 3.0, hold=0.6),
]

BY_KEY: Dict[str, Effect] = {e.key: e for e in EFFECTS}


def get(key: str) -> Effect:
    try:
        return BY_KEY[key.lower()]
    except KeyError:
        raise ValueError(f"unknown effect {key!r}. Choose from: "
                         + ", ".join(BY_KEY)) from None


def apply(kb, effect: Effect, brightness: int = 100, speed: float = None,
          direction: int = 1, zone: str = "all", save: bool = True) -> None:
    """Send a preset to an open backend (speed in seconds per pass)."""
    cols = [scale(c, brightness) for c in effect.colors]
    secs = effect.speed if speed is None else speed
    if effect.mode == "cycle":
        kb.set_cycle(cols, speed=secs, zone=zone, save=save, hold=effect.hold)
    else:
        kb.set_wave(cols, speed=secs, direction=direction, zone=zone,
                    save=save, hold=effect.hold)
