"""Reusable look-and-feel for the MysticKeys GUI: palette, drawing helpers
and custom widgets (flat rounded buttons, a snapping slider)."""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
BG       = "#0f1115"   # window background
PANEL    = "#171a21"   # raised panel
CARD     = "#1e222c"   # card / input
CARD_HI  = "#262b38"   # hover
STROKE   = "#2d3340"   # borders
FG       = "#eef1f7"   # primary text
MUTED    = "#8b92a6"   # secondary text
ACCENT   = "#6ea8ff"   # primary accent
ACCENT_2 = "#9b7bff"   # secondary accent
DANGER   = "#ff6b7a"
OK       = "#49d6a0"


def _hex(r, g, b):
    return "#%02x%02x%02x" % (int(r), int(g), int(b))


def _rr(cv, x1, y1, x2, y2, r, **kw):
    """Draw a rounded rectangle on a canvas and return the item id."""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


class HoverButton(tk.Canvas):
    """A flat rounded button drawn on a canvas, with hover + press states."""

    def __init__(self, master, text, command, w=120, h=40,
                 fill=CARD, hover=CARD_HI, fg=FG, accent=False, **kw):
        super().__init__(master, width=w, height=h, bg=master["bg"],
                         highlightthickness=0, **kw)
        self._cmd = command
        self._fill = ACCENT if accent else fill
        self._hover = "#86b8ff" if accent else hover
        self._fg = "#0f1115" if accent else fg
        self._text = text
        self._bg_item = _rr(self, 1, 1, w - 1, h - 1, 11, fill=self._fill,
                            outline=STROKE if not accent else "")
        self._txt_item = self.create_text(w // 2, h // 2, text=text, fill=self._fg,
                                           font=("Segoe UI", 10, "bold"))
        self.bind("<Enter>", lambda e: self.itemconfigure(self._bg_item, fill=self._hover))
        self.bind("<Leave>", lambda e: self.itemconfigure(self._bg_item, fill=self._fill))
        self.bind("<Button-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)

    def _press(self, _e):
        self.itemconfigure(self._bg_item, fill=self._fill)
        self.move(self._txt_item, 0, 1)

    def _release(self, _e):
        self.move(self._txt_item, 0, -1)
        self.itemconfigure(self._bg_item, fill=self._hover)
        if self._cmd:
            self._cmd()


class StepSlider(tk.Canvas):
    """A compact slider that snaps to a list of values, with a value label."""

    def __init__(self, master, values, index, fmt, on_change, on_release,
                 w=180, h=30, **kw):
        super().__init__(master, width=w, height=h, bg=master["bg"],
                         highlightthickness=0, cursor="hand2", **kw)
        self.values, self.index, self.fmt = list(values), index, fmt
        self._on_change, self._on_release = on_change, on_release
        self._font = tkfont.Font(family="Segoe UI Semibold", size=10, weight="bold")
        self._sw, self._sh = w, h
        self.bind("<Button-1>", self._drag)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", lambda e: self._on_release())
        self.bind("<Button-4>", lambda e: self._step(1))
        self.bind("<Button-5>", lambda e: self._step(-1))
        self.bind("<MouseWheel>", lambda e: self._step(1 if e.delta > 0 else -1))
        self._draw()

    @property
    def value(self):
        return self.values[self.index]

    def _track(self):
        x0 = 10
        x1 = self._sw - self._font.measure(self.fmt(max(self.values, key=lambda v:
                                                      len(self.fmt(v))))) - 20
        return x0, x1

    def _set(self, i):
        i = max(0, min(len(self.values) - 1, i))
        if i != self.index:
            self.index = i
            self._draw()
            self._on_change()

    def _step(self, d):
        old = self.index
        self._set(self.index + d)
        if self.index != old:
            self._on_release()

    def _drag(self, e):
        x0, x1 = self._track()
        f = (e.x - x0) / (x1 - x0)
        self._set(round(f * (len(self.values) - 1)))

    def _draw(self):
        self.delete("all")
        x0, x1 = self._track()
        y = self._sh // 2
        hx = x0 + (x1 - x0) * self.index / (len(self.values) - 1)
        self.create_line(x0, y, x1, y, fill=STROKE, width=5, capstyle="round")
        if hx > x0:
            self.create_line(x0, y, hx, y, fill=ACCENT_2, width=5, capstyle="round")
        self.create_oval(hx - 7, y - 7, hx + 7, y + 7, fill="#ffffff",
                         outline=ACCENT_2, width=2)
        self.create_text(self._sw - 2, y, text=self.fmt(self.value), fill=FG,
                         font=self._font, anchor="e")
