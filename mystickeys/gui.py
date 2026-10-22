"""A polished dark-themed Tkinter GUI for the MSI keyboard backlight.

Pure standard library (tkinter + colorsys). Features a live HSV color picker,
a keyboard-zone visualizer, brightness control, presets and effects.
"""

from __future__ import annotations

import colorsys
import sys
import threading
import webbrowser

try:
    import tkinter as tk
    from tkinter import font as tkfont
except Exception:  # pragma: no cover
    tk = None

from . import __version__
from . import effects as fx
from . import live
from . import notify
from . import presets as presets_store
from .backends import KeyboardError, Unsupported, detect, open_keyboard
from .colors import scale

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

SV_SIZE = 240          # displayed size of the saturation/value square
HUE_W   = 22
HUE_H   = 240
_ZOOM   = 2            # gradients rendered at half-res then zoomed


def _hex(r, g, b):
    return "#%02x%02x%02x" % (int(r), int(g), int(b))


def _rr(cv, x1, y1, x2, y2, r, **kw):
    """Draw a rounded rectangle on a canvas and return the item id."""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


def _physical_zones():
    found = detect()
    if not found:
        return ["1", "2", "3", "4"]
    cls = found[0]
    seen, out = set(), []
    for z in sorted((z for z in cls.zones if z != "all"), key=lambda z: cls.zones[z]):
        if cls.zones[z] in seen:
            continue
        seen.add(cls.zones[z])
        out.append(z)
    return out


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


# seconds per pass
SPEEDS = tuple(range(int(fx.SPEED_MIN), int(fx.SPEED_MAX) + 1))


class App:
    def __init__(self, root):
        self.root = root
        self.h, self.s, self.v = 0.42, 0.85, 0.80   # fallback start color
        self.bright = 100
        self.zones = _physical_zones()
        self.zone_colors = {z: (20, 20, 26) for z in self.zones}
        self.target = "all"
        self.direction = 1          # 1 = left to right, 0 = right to left
        self._replay = None         # re-applies the running effect on change

        # restore the last-applied color / brightness / zones, if any
        st = presets_store.load_state()
        if st.get("rgb"):
            r, g, b = st["rgb"]
            self.h, self.s, self.v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if "brightness" in st:
            self.bright = int(st["brightness"])
        for z, col in (st.get("zones") or {}).items():
            if z in self.zone_colors:
                self.zone_colors[z] = tuple(col)

        root.title("MysticKeys")
        root.configure(bg=BG)
        root.resizable(False, False)

        self._build()
        self._render_sv()
        self._render_hue()
        self._sync_color()

    # -- layout ------------------------------------------------------------
    def _build(self):
        head = tk.Canvas(self.root, width=760, height=70, bg=BG,
                         highlightthickness=0)
        head.grid(row=0, column=0, columnspan=2, sticky="we")
        for i in range(760):  # subtle gradient bar
            t = i / 760
            r = int(0x6e + (0x9b - 0x6e) * t)
            g = int(0xa8 + (0x7b - 0xa8) * t)
            b = int(0xff + (0xff - 0xff) * t)
            head.create_line(i, 64, i, 68, fill=_hex(r, g, b))
        head.create_text(28, 24, anchor="w", text="MysticKeys",
                         fill=FG, font=("Segoe UI Semibold", 20, "bold"))
        found = detect()
        sub = found[0].name if found else "no controller detected"
        head.create_text(30, 50, anchor="w", text=sub, fill=MUTED,
                         font=("Segoe UI", 9))
        self.head = head

        # About button (top-right of the header)
        about = HoverButton(self.root, "About", self._about, w=78, h=30)
        about.place(x=664, y=20)

        body = tk.Frame(self.root, bg=BG)
        body.grid(row=1, column=0, columnspan=2, padx=18, pady=(4, 16))

        # ---- left: color picker --------------------------------------
        left = tk.Frame(body, bg=PANEL, highlightthickness=1,
                        highlightbackground=STROKE)
        left.grid(row=0, column=0, sticky="nwe", padx=(0, 14), ipadx=14, ipady=14)
        tk.Label(left, text="COLOR", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).grid(row=0, column=0, columnspan=2,
                                                    sticky="w", padx=4, pady=(0, 8))

        self.sv = tk.Canvas(left, width=SV_SIZE, height=SV_SIZE, bg=PANEL,
                            highlightthickness=0, cursor="tcross")
        self.sv.grid(row=1, column=0, padx=(4, 10))
        self.sv.bind("<Button-1>", self._on_sv)
        self.sv.bind("<B1-Motion>", self._on_sv)

        self.hue = tk.Canvas(left, width=HUE_W, height=HUE_H, bg=PANEL,
                             highlightthickness=0, cursor="sb_v_double_arrow")
        self.hue.grid(row=1, column=1, sticky="n")
        self.hue.bind("<Button-1>", self._on_hue)
        self.hue.bind("<B1-Motion>", self._on_hue)

        # big preview + hex
        prev = tk.Frame(left, bg=PANEL)
        prev.grid(row=2, column=0, columnspan=2, sticky="we", pady=(12, 0), padx=4)
        self.prev_cv = tk.Canvas(prev, width=58, height=58, bg=PANEL,
                                 highlightthickness=0)
        self.prev_cv.pack(side="left")
        self._prev_item = _rr(self.prev_cv, 2, 2, 56, 56, 12, fill="#000",
                              outline=STROKE)
        hx = tk.Frame(prev, bg=PANEL)
        hx.pack(side="left", padx=12)
        tk.Label(hx, text="HEX", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w")
        self.hexvar = tk.StringVar(value="#000000")
        e = tk.Entry(hx, textvariable=self.hexvar, width=10, bg=CARD, fg=FG,
                     insertbackground=FG, relief="flat", justify="center",
                     font=("Consolas", 13, "bold"))
        e.pack(anchor="w", ipady=4)
        e.bind("<Return>", self._on_hex)
        self.rgbvar = tk.StringVar(value="")
        tk.Label(hx, textvariable=self.rgbvar, bg=PANEL, fg=MUTED,
                 font=("Consolas", 9)).pack(anchor="w", pady=(2, 0))

        # ---- left, below the picker: effects --------------------------
        ep = tk.Frame(body, bg=PANEL, highlightthickness=1,
                      highlightbackground=STROKE)
        ep.grid(row=1, column=0, sticky="nwe", padx=(0, 14), pady=(14, 0),
                ipadx=14, ipady=10)
        tk.Label(ep, text="COLOR WAVES", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=4, pady=(0, 8))
        grid = tk.Frame(ep, bg=PANEL)
        grid.pack(anchor="w", padx=4)
        for i, eff in enumerate(fx.EFFECTS):
            last_odd = i == len(fx.EFFECTS) - 1 and i % 2 == 0
            bw = 272 if last_odd else 134  # a lone last button spans the row
            b = HoverButton(grid, eff.name, lambda e=eff: self.run_effect(e),
                            w=bw, h=34)
            b.grid(row=i // 2, column=i % 2, columnspan=2 if last_odd else 1,
                   padx=2, pady=2)
            self._swatch(b, eff, bw, 34)
            self._bind_tip(b, eff.description)

        ctl = tk.Frame(ep, bg=PANEL)
        ctl.pack(fill="x", padx=4, pady=(10, 0))
        tk.Label(ctl, text="SPEED", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        self.speed = StepSlider(ctl, SPEEDS, SPEEDS.index(6),
                                lambda v: f"{v} s", self._on_speed,
                                self._replay_effect, w=150)
        self.speed.pack(side="left", padx=(6, 8))
        self.dir_btn = HoverButton(ctl, "→", self._toggle_direction, w=40, h=28)
        self.dir_btn.pack(side="right")
        self._bind_tip(self.dir_btn, "wave direction")

        # ---- right: controls -----------------------------------------
        right = tk.Frame(body, bg=BG)
        right.grid(row=0, column=1, rowspan=2, sticky="n")
        body.grid_rowconfigure(1, weight=1)  # spare height goes below the left cards

        # zones
        zp = self._card(right, "ZONES")
        self.zone_cv = tk.Canvas(zp, width=300, height=66, bg=CARD,
                                 highlightthickness=0)
        self.zone_cv.pack(padx=12, pady=(0, 8))
        self.zone_cv.bind("<Button-1>", self._on_zone_click)
        chips = tk.Frame(zp, bg=CARD)
        chips.pack(padx=12, pady=(0, 12), anchor="w")
        self.chip_btns = {}
        for name in (["all"] + self.zones):
            b = tk.Label(chips, text=name, bg=PANEL, fg=FG, padx=10, pady=4,
                         font=("Segoe UI", 9, "bold"), cursor="hand2")
            b.pack(side="left", padx=3)
            b.bind("<Button-1>", lambda e, n=name: self._set_target(n))
            self.chip_btns[name] = b

        # brightness (custom slider: filled track + knob + live % label)
        bp = self._card(right, "BRIGHTNESS")
        self.bcanvas = tk.Canvas(bp, width=300, height=46, bg=CARD,
                                 highlightthickness=0, cursor="hand2")
        self.bcanvas.pack(fill="x", padx=12, pady=(0, 12))
        self._bfont = tkfont.Font(family="Segoe UI Semibold", size=12, weight="bold")
        self._BTX0, self._BTX1, self._BY = 16, 236, 23   # track geometry
        self._bwidth = 300                                # set on <Configure>
        self.bcanvas.bind("<Configure>", self._layout_bright)
        self.bcanvas.bind("<Button-1>", self._on_bright_drag)
        self.bcanvas.bind("<B1-Motion>", self._on_bright_drag)
        # mouse wheel: X11 sends Button-4/5, other platforms <MouseWheel>
        self.bcanvas.bind("<Button-4>", lambda e: self._bright_set(self.bright + 5))
        self.bcanvas.bind("<Button-5>", lambda e: self._bright_set(self.bright - 5))
        self.bcanvas.bind("<MouseWheel>", lambda e: self._bright_set(
            self.bright + (5 if e.delta > 0 else -5)))
        self._draw_bright()

        # presets
        pp = self._card(right, "PRESETS")
        pf = tk.Frame(pp, bg=CARD)
        pf.pack(padx=12, pady=(0, 6), anchor="w")
        presets = [(255, 0, 0), (255, 90, 0), (255, 200, 0), (0, 255, 90),
                   (16, 124, 65), (0, 220, 255), (40, 120, 255), (150, 60, 255),
                   (255, 60, 160), (255, 255, 255)]
        for i, rgb in enumerate(presets):
            c = tk.Canvas(pf, width=30, height=30, bg=CARD, highlightthickness=0,
                          cursor="hand2")
            c.grid(row=i // 5, column=i % 5, padx=4, pady=4)
            _rr(c, 2, 2, 28, 28, 8, fill=_hex(*rgb), outline=STROKE)
            c.bind("<Button-1>", lambda e, v=rgb: self._set_rgb(v))

        # my presets (saved)
        myhdr = tk.Frame(pp, bg=CARD)
        myhdr.pack(fill="x", padx=12, pady=(6, 0))
        tk.Label(myhdr, text="MY PRESETS", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        HoverButton(myhdr, "＋ Save", self._save_preset, w=78, h=26)\
            .pack(side="right")
        self.user_pf = tk.Frame(pp, bg=CARD)
        self.user_pf.pack(padx=12, pady=(6, 12), anchor="w", fill="x")
        self._build_user_presets()

        # actions
        bar = tk.Frame(right, bg=BG)
        bar.pack(fill="x", pady=(4, 0))
        HoverButton(bar, "Apply", self.apply, w=104, h=42, accent=True)\
            .pack(side="left", padx=(0, 6))
        HoverButton(bar, "Breath", self.breath, w=76, h=42).pack(side="left", padx=3)
        HoverButton(bar, "Cycle", self.cycle, w=70, h=42).pack(side="left", padx=3)
        HoverButton(bar, "Wave", self.wave, w=70, h=42).pack(side="left", padx=3)
        HoverButton(bar, "Off", self.off, w=58, h=42).pack(side="left", padx=3)

        # live effects (run while the app is open)
        lp = self._card(right, "LIVE")
        lp.pack_configure(pady=(12, 0))
        lgrid = tk.Frame(lp, bg=CARD)
        lgrid.pack(padx=12, pady=(0, 10), anchor="w")
        self.live_btns = {}
        for i, (key, label) in enumerate((
                ("battery", "Battery"), ("cpu", "CPU"), ("temp", "Temp"),
                ("music", "Music"), ("typing", "Typing"), ("fire", "Fire"),
                ("thunder", "Thunder"), ("lava", "Lava lamp"))):
            b = HoverButton(lgrid, label, lambda k=key: self.toggle_live(k),
                            w=94, h=32)
            b.grid(row=i // 4, column=i % 4, padx=(0, 4), pady=(0, 4))
            self._bind_tip(b, live.LIVE[key][1] + " (click again to stop)")
            self.live_btns[key] = b

        # notification flash: a feature with an on/off switch
        nrow = tk.Frame(lp, bg=CARD)
        nrow.pack(fill="x", padx=12, pady=(0, 12))
        tk.Label(nrow, text="Flash on notifications", bg=CARD, fg=FG,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        self.notify_test = HoverButton(nrow, "Test", self._notify_test, w=58, h=30)
        self.notify_test.pack(side="right")
        self.notify_btn = HoverButton(nrow, "Off", self.toggle_notify, w=70, h=30)
        self.notify_btn.pack(side="right", padx=(0, 6))
        self._bind_tip(self.notify_btn, "flash the keyboard when a notification "
                       "arrives (uses the picked color; keeps running after "
                       "you close the app)")
        self._show_notify(notify.is_enabled())
        # show a live effect that is already running in the background
        running = live.background_effect()
        if running in self.live_btns:
            self._live_key = running
            self._mark_live(running, True)

        self.status = tk.Label(self.root, text="Ready", bg=PANEL, fg=MUTED,
                               anchor="w", font=("Segoe UI", 9), padx=16, pady=6)
        self.status.grid(row=2, column=0, columnspan=2, sticky="we")

        self.root.grid_columnconfigure(0, weight=1)
        self._draw_zone_bar()
        self._set_target("all")

    # -- user presets ------------------------------------------------------
    def _build_user_presets(self):
        for w in self.user_pf.winfo_children():
            w.destroy()
        items = presets_store.load()
        if not items:
            tk.Label(self.user_pf, text="No saved presets yet — set a color and "
                     "click Save.", bg=CARD, fg=MUTED,
                     font=("Segoe UI", 8), wraplength=300,
                     justify="left").pack(anchor="w")
            return
        for i, p in enumerate(items):
            rgb = tuple(p["rgb"])
            cell = tk.Frame(self.user_pf, bg=CARD)
            cell.grid(row=i // 5, column=i % 5, padx=4, pady=3)
            c = tk.Canvas(cell, width=34, height=28, bg=CARD,
                          highlightthickness=0, cursor="hand2")
            c.pack()
            _rr(c, 2, 2, 32, 26, 8, fill=_hex(*rgb), outline=STROKE)
            name = p["name"]
            short = name if len(name) <= 7 else name[:6] + "…"
            lbl = tk.Label(cell, text=short, bg=CARD, fg=MUTED,
                           font=("Segoe UI", 7))
            lbl.pack()
            tip = f"{name}  ·  click: apply   ·   right-click: delete"
            for widget in (c, lbl):
                widget.bind("<Button-1>",
                            lambda e, pp=p: self._apply_user_preset(pp))
                widget.bind("<Button-3>",
                            lambda e, nm=name: self._delete_user_preset(nm))
                self._bind_tip(widget, tip)

    def _bind_tip(self, widget, text):
        widget.bind("<Enter>", lambda e: self.status.configure(text=text, fg=MUTED),
                    add="+")

    def _save_preset(self):
        name = self._prompt_name()
        if not name:
            return
        presets_store.add(name, self._rgb(), self.bright)
        self._build_user_presets()
        self.status.configure(text=f"Saved preset '{name}'", fg=OK)

    def _apply_user_preset(self, p):
        rgb = tuple(p["rgb"])
        self._bright_set(int(p.get("brightness", 100)))
        self._set_rgb(rgb)                 # loads color into the picker
        self.apply()                       # and pushes it to the keyboard

    def _delete_user_preset(self, name):
        if self._confirm("Delete preset", f"Delete preset '{name}'?"):
            presets_store.delete(name)
            self._build_user_presets()
            self.status.configure(text=f"Deleted '{name}'", fg=MUTED)

    def _prompt_name(self):
        win = tk.Toplevel(self.root)
        win.title("Save preset")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self.root)
        try:
            win.grab_set()
        except Exception:
            pass
        result = {"name": None}

        tk.Label(win, text="Preset name", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=20, pady=(18, 6))
        var = tk.StringVar()
        ent = tk.Entry(win, textvariable=var, width=24, bg=CARD, fg=FG,
                       insertbackground=FG, relief="flat", justify="left",
                       font=("Segoe UI", 12))
        ent.pack(padx=20, ipady=6)
        ent.focus_set()

        # color chip preview
        chip = tk.Canvas(win, width=240, height=26, bg=BG, highlightthickness=0)
        chip.pack(padx=20, pady=(10, 0))
        _rr(chip, 0, 0, 240, 24, 8, fill=_hex(*self._rgb()), outline=STROKE)

        def ok(_e=None):
            result["name"] = var.get().strip()
            win.destroy()

        def cancel(_e=None):
            win.destroy()

        bar = tk.Frame(win, bg=BG)
        bar.pack(fill="x", padx=20, pady=16)
        HoverButton(bar, "Save", ok, w=100, h=36, accent=True).pack(side="right")
        HoverButton(bar, "Cancel", cancel, w=90, h=36).pack(side="right", padx=(0, 8))
        ent.bind("<Return>", ok)
        ent.bind("<Escape>", cancel)

        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + 120
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.root.wait_window(win)
        return result["name"]

    # -- dark modal dialogs (replace native light messageboxes) -----------
    def _dialog(self, title, message, buttons):
        """buttons: list of (label, value, accent). Returns the chosen value."""
        win = tk.Toplevel(self.root)
        win.title(title)
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self.root)
        try:
            win.grab_set()
        except Exception:
            pass
        result = {"v": None}

        strip = tk.Canvas(win, width=360, height=6, bg=ACCENT, highlightthickness=0)
        strip.pack(fill="x")
        tk.Label(win, text=title, bg=BG, fg=FG,
                 font=("Segoe UI Semibold", 13, "bold")).pack(
                     anchor="w", padx=22, pady=(16, 4))
        tk.Label(win, text=message, bg=BG, fg=MUTED, justify="left",
                 wraplength=320, font=("Segoe UI", 10)).pack(
                     anchor="w", padx=22, pady=(0, 6))

        bar = tk.Frame(win, bg=BG)
        bar.pack(fill="x", padx=22, pady=16)

        def choose(v):
            result["v"] = v
            win.destroy()

        for label, value, accent in reversed(buttons):
            HoverButton(bar, label, lambda v=value: choose(v),
                        w=96, h=36, accent=accent).pack(side="right", padx=(8, 0))

        win.bind("<Escape>", lambda e: choose(None))
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + 140
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.root.wait_window(win)
        return result["v"]

    def _confirm(self, title, message):
        return bool(self._dialog(title, message,
                                 [("Cancel", False, False), ("Delete", True, True)]))

    def _info(self, title, message):
        self._dialog(title, message, [("OK", True, True)])

    # -- about dialog ------------------------------------------------------
    def _about(self):
        gh_url = "https://github.com/blue0x1"
        win = tk.Toplevel(self.root)
        win.title("About")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self.root)
        try:
            win.grab_set()
        except Exception:
            pass

        # gradient header strip
        hd = tk.Canvas(win, width=380, height=96, bg=BG, highlightthickness=0)
        hd.pack(fill="x")
        for i in range(380):
            t = i / 380
            r = int(0x6e + (0x9b - 0x6e) * t)
            g = int(0xa8 + (0x7b - 0xa8) * t)
            b = 0xff
            hd.create_line(i, 0, i, 96, fill=_hex(r, g, b))
        hd.create_text(190, 38, text="MysticKeys", fill="#0f1115",
                       font=("Segoe UI Semibold", 18, "bold"))
        hd.create_text(190, 66, text=f"version {__version__}", fill="#0f1115",
                       font=("Segoe UI", 10, "bold"))

        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=26, pady=20)

        tk.Label(body, text="Author", bg=BG, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w")
        tk.Label(body, text="Chokri Hammedi", bg=BG, fg=FG,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(body, text="blue0x1", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 14))

        tk.Label(body, text="GitHub", bg=BG, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w")
        link = tk.Label(body, text=gh_url, bg=BG, fg=ACCENT, cursor="hand2",
                        font=("Segoe UI", 10, "underline"))
        link.pack(anchor="w", pady=(0, 18))
        link.bind("<Button-1>", lambda e: webbrowser.open(gh_url))

        HoverButton(body, "Close", win.destroy, w=100, h=38, accent=True)\
            .pack(anchor="e")

        # center over the main window
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + 80
        win.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _card(self, parent, title):
        wrap = tk.Frame(parent, bg=CARD, highlightthickness=1,
                        highlightbackground=STROKE)
        wrap.pack(fill="x", pady=(0, 12))
        tk.Label(wrap, text=title, bg=CARD, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=12, pady=(10, 6))
        return wrap

    # -- gradient rendering ------------------------------------------------
    def _render_sv(self):
        base = SV_SIZE // _ZOOM
        img = tk.PhotoImage(width=base, height=base)
        rows = []
        for y in range(base):
            val = 1 - y / (base - 1)
            row = []
            for x in range(base):
                sat = x / (base - 1)
                r, g, b = colorsys.hsv_to_rgb(self.h, sat, val)
                row.append("#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255)))
            rows.append("{" + " ".join(row) + "}")
        img.put(" ".join(rows))
        self._sv_img = img.zoom(_ZOOM)
        self.sv.delete("grad")
        self.sv.create_image(0, 0, anchor="nw", image=self._sv_img, tags="grad")
        self.sv.tag_lower("grad")
        self._draw_sv_marker()

    def _render_hue(self):
        base_h = HUE_H // _ZOOM
        img = tk.PhotoImage(width=HUE_W // _ZOOM, height=base_h)
        rows = []
        for y in range(base_h):
            r, g, b = colorsys.hsv_to_rgb(y / (base_h - 1), 1, 1)
            col = "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))
            rows.append("{" + " ".join([col] * (HUE_W // _ZOOM)) + "}")
        img.put(" ".join(rows))
        self._hue_img = img.zoom(_ZOOM)
        self.hue.delete("grad")
        self.hue.create_image(0, 0, anchor="nw", image=self._hue_img, tags="grad")
        self.hue.tag_lower("grad")
        self._draw_hue_marker()

    def _draw_sv_marker(self):
        self.sv.delete("mk")
        x = self.s * SV_SIZE
        y = (1 - self.v) * SV_SIZE
        x = max(6, min(SV_SIZE - 6, x))
        y = max(6, min(SV_SIZE - 6, y))
        self.sv.create_oval(x - 7, y - 7, x + 7, y + 7, outline="#ffffff",
                            width=2, tags="mk")
        self.sv.create_oval(x - 8, y - 8, x + 8, y + 8, outline="#000000",
                            width=1, tags="mk")

    def _draw_hue_marker(self):
        self.hue.delete("mk")
        y = self.h * HUE_H
        y = max(3, min(HUE_H - 3, y))
        self.hue.create_rectangle(0, y - 3, HUE_W, y + 3, outline="#fff",
                                  width=2, tags="mk")

    # -- zone bar ----------------------------------------------------------
    def _draw_zone_bar(self):
        cv = self.zone_cv
        cv.delete("all")
        n = len(self.zones)
        gap = 8
        w = (300 - gap * (n - 1)) / n
        self._zone_rects = {}
        for i, z in enumerate(self.zones):
            x1 = i * (w + gap)
            col = _hex(*self.zone_colors[z])
            sel = (self.target == z) or (self.target == "all")
            rid = _rr(cv, x1, 4, x1 + w, 62, 10, fill=col,
                      outline=ACCENT if sel else STROKE,
                      width=2 if sel else 1)
            cv.create_text(x1 + w / 2, 33, text=z, fill="#ffffff",
                           font=("Segoe UI", 9, "bold"))
            self._zone_rects[z] = (x1, x1 + w)

    def _on_zone_click(self, e):
        for z, (x1, x2) in self._zone_rects.items():
            if x1 <= e.x <= x2:
                self._set_target(z)
                return

    def _set_target(self, name):
        self.target = name
        for n, b in self.chip_btns.items():
            if n == name:
                b.configure(bg=ACCENT, fg="#0f1115")
            else:
                b.configure(bg=PANEL, fg=FG)
        self._draw_zone_bar()

    # -- interaction -------------------------------------------------------
    def _on_sv(self, e):
        self.s = max(0.0, min(1.0, e.x / SV_SIZE))
        self.v = max(0.0, min(1.0, 1 - e.y / SV_SIZE))
        self._draw_sv_marker()
        self._sync_color()

    def _on_hue(self, e):
        self.h = max(0.0, min(0.9999, e.y / HUE_H))
        self._render_sv()
        self._draw_hue_marker()
        self._sync_color()

    def _on_hex(self, _e=None):
        from .colors import parse_color
        try:
            r, g, b = parse_color(self.hexvar.get())
            self._set_rgb((r, g, b))
        except Exception:
            self.status.configure(text="invalid hex", fg=DANGER)

    def _layout_bright(self, e=None):
        """Fit the track to the canvas width, leaving room for "100%"."""
        width = self._bwidth = e.width if e else self.bcanvas.winfo_width()
        label_w = self._bfont.measure("100%")
        self._BTX0 = 16
        self._BTX1 = max(self._BTX0 + 40, width - label_w - 34)
        self._draw_bright()

    def _draw_bright(self):
        cv = self.bcanvas
        cv.delete("all")
        x0, x1, y = self._BTX0, self._BTX1, self._BY
        hx = x0 + (x1 - x0) * self.bright / 100
        # unfilled track
        cv.create_line(x0, y, x1, y, fill=STROKE, width=6, capstyle="round")
        # filled portion
        if hx > x0:
            cv.create_line(x0, y, hx, y, fill=ACCENT, width=6, capstyle="round")
        # knob
        cv.create_oval(hx - 9, y - 9, hx + 9, y + 9, fill="#ffffff",
                       outline=ACCENT, width=3)
        # live value label
        # live value label, right-aligned so "100%" always fits
        cv.create_text(self._bwidth - 4, y,
                       text=f"{self.bright}%", fill=FG, font=self._bfont,
                       anchor="e")

    def _on_bright_drag(self, e):
        x0, x1 = self._BTX0, self._BTX1
        v = (e.x - x0) / (x1 - x0) * 100
        self.bright = max(0, min(100, int(round(v))))
        self._draw_bright()
        self._bright_to_live()

    def _bright_set(self, value):
        self.bright = max(0, min(100, int(value)))
        self._draw_bright()
        self._bright_to_live()

    def _bright_to_live(self):
        if self._live_key:  # the service re-reads this about once a second
            live.save_state(brightness=self.bright)

    def _set_rgb(self, rgb):
        r, g, b = rgb
        self.h, self.s, self.v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        self._render_sv()
        self._draw_hue_marker()
        self._sync_color()

    def _rgb(self):
        r, g, b = colorsys.hsv_to_rgb(self.h, self.s, self.v)
        return (int(r * 255), int(g * 255), int(b * 255))

    def _sync_color(self):
        rgb = self._rgb()
        self.hexvar.set(_hex(*rgb))
        self.rgbvar.set("rgb(%d, %d, %d)" % rgb)
        self.prev_cv.itemconfigure(self._prev_item, fill=_hex(*rgb))

    # -- device actions ----------------------------------------------------
    def _targets(self):
        return self.zones if self.target == "all" else [self.target]

    def _save_state(self):
        presets_store.save_state(self._rgb(), self.bright, self.zone_colors)

    def _do(self, fn, msg):
        self.stop_live()  # a normal action replaces any live effect
        try:
            kb = open_keyboard()
            with kb:
                fn(kb)
            self.status.configure(text=msg, fg=OK)
        except Unsupported as e:
            self.status.configure(text="not supported on this model", fg=DANGER)
            self._popup(str(e))
        except KeyboardError as e:
            self.status.configure(text=str(e), fg=DANGER)
            self._popup(str(e))

    # -- live effects ----------------------------------------------------------
    # Live effects run as a background service (see live.start_background),
    # so they keep going after the window is closed and after login.
    _live_key = None  # name of the running live effect, if any

    def _mark_live(self, key, on):
        b = self.live_btns[key]
        b._fill = ACCENT_2 if on else CARD
        b.itemconfigure(b._bg_item, fill=b._fill)

    def toggle_live(self, key):
        running = self._live_key
        if running == key:  # clicking the active one turns it off
            self.stop_live()
            self.status.configure(text="Live effect stopped", fg=MUTED)
            return
        if running:
            self._mark_live(running, False)
        try:
            live.start_background(key, color=self._rgb(), brightness=self.bright)
        except (KeyboardError, OSError) as e:
            self._live_key = None
            self.status.configure(text=str(e), fg=DANGER)
            self._popup(str(e))
            return
        self._live_key = key
        self._mark_live(key, True)
        self.status.configure(text=f"Live: {key} · keeps running after you "
                                   "close the app (click it again to stop)",
                              fg=OK)

    def stop_live(self):
        if not self._live_key:
            return
        key, self._live_key = self._live_key, None
        live.stop_background()  # returns once the keyboard is restored
        self._mark_live(key, False)

    # -- notification flash -------------------------------------------------
    def _show_notify(self, on):
        self._notify_on = on
        b = self.notify_btn
        b._fill = OK if on else CARD
        b.itemconfigure(b._bg_item, fill=b._fill)
        b.itemconfigure(b._txt_item, text="On" if on else "Off",
                        fill="#0f1115" if on else FG)

    def toggle_notify(self):
        try:
            if self._notify_on:
                notify.disable()
                self._show_notify(False)
                self.status.configure(text="Notification flash off", fg=MUTED)
            else:
                notify.enable(self._rgb())
                self._show_notify(True)
                self.status.configure(
                    text=f"Notification flash on ({self.hexvar.get()}); "
                         "it keeps working after you close the app", fg=OK)
        except (KeyboardError, OSError) as e:
            self.status.configure(text=str(e), fg=DANGER)
            self._popup(str(e))

    def _notify_test(self):
        color = self._rgb() if not self._notify_on else None
        threading.Thread(target=self._flash_quietly, args=(color,),
                         daemon=True).start()
        self.status.configure(text="Test flash", fg=MUTED)

    def _flash_quietly(self, color):
        try:
            notify.flash(color)
        except KeyboardError as e:
            msg = str(e)
            self.root.after(0, lambda: self.status.configure(text=msg, fg=DANGER))

    def close(self):
        self.root.destroy()  # a live effect keeps running in the background

    def _popup(self, msg):
        self._info("MysticKeys", msg)

    def apply(self):
        rgb = scale(self._rgb(), self.bright)
        for z in self._targets():
            self.zone_colors[z] = rgb
        self._draw_zone_bar()
        self._replay = None
        self._do(lambda kb: kb.set_color(rgb, zone=self.target),
                 f"Applied {self.hexvar.get()} → {self.target}")
        self._save_state()

    # -- effects -----------------------------------------------------------
    def _secs(self):
        return float(self.speed.value)

    def _start(self, send, msg, preview):
        """Apply an effect now and remember it for speed/direction changes."""
        for i, z in enumerate(self._targets()):
            self.zone_colors[z] = preview[i % len(preview)]
        self._draw_zone_bar()
        self._replay = (send, msg)
        self._do(send, msg())
        self._save_state()

    def _replay_effect(self):
        if self._replay:
            send, msg = self._replay
            self._do(send, msg())

    def _on_speed(self):
        if self._replay:
            self.status.configure(text=f"speed {self.speed.value} s "
                                       "(release to apply)", fg=MUTED)

    def _toggle_direction(self):
        self.direction ^= 1
        self.dir_btn.itemconfigure(self.dir_btn._txt_item,
                                   text="→" if self.direction else "←")
        self._replay_effect()

    def _swatch(self, btn, eff, w, h):
        """Thin color strip along the bottom of an effect button."""
        cols = eff.colors
        seg = (w - 28) / len(cols)
        for i, c in enumerate(cols):
            btn.create_line(14 + i * seg, h - 6, 14 + (i + 1) * seg, h - 6,
                            fill=_hex(*c), width=2)

    def set_speed(self, secs):
        """Move the speed slider (without re-applying anything)."""
        self.speed.index = min(range(len(SPEEDS)),
                               key=lambda i: abs(SPEEDS[i] - secs))
        self.speed._draw()

    def run_effect(self, eff):
        self.set_speed(eff.speed)  # start from the preset's tuned speed
        cols = [scale(c, self.bright) for c in eff.colors]
        self._start(lambda kb: fx.apply(kb, eff, brightness=self.bright,
                                        speed=self._secs(),
                                        direction=self.direction,
                                        zone=self.target),
                    lambda: f"{eff.name} · {self._secs():g} s per pass", cols)

    def breath(self):
        rgb = scale(self._rgb(), self.bright)
        self._start(lambda kb: kb.set_breath([rgb], speed=self._secs(),
                                             zone=self.target),
                    lambda: f"Breathing · {self._secs():g} s", [rgb])

    def cycle(self):
        cols = [scale(c, self.bright) for c in fx.RAINBOW]
        self._start(lambda kb: kb.set_cycle(cols, speed=self._secs(),
                                            zone=self.target),
                    lambda: f"Color cycle · {self._secs():g} s", cols)

    def wave(self):
        # a band of the picked color travelling across the keyboard
        rgb = scale(self._rgb(), self.bright)
        self._start(lambda kb: kb.set_wave([rgb, (0, 0, 0)], speed=self._secs(),
                                           direction=self.direction,
                                           zone=self.target),
                    lambda: f"Wave · {self._secs():g} s", [rgb])

    def off(self):
        for z in self._targets():
            self.zone_colors[z] = (20, 20, 26)
        self._draw_zone_bar()
        self._replay = None
        self._do(lambda kb: kb.turn_off(zone=self.target), "Off")
        self._save_state()


def _set_window_icon(root) -> None:
    """Use the app icon for the window/taskbar (project or installed copy)."""
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [os.path.join(here, "data", "mystickeys-64.png"),
                  "/usr/local/share/icons/hicolor/64x64/apps/mystickeys.png",
                  "/usr/share/icons/hicolor/64x64/apps/mystickeys.png"]
    for path in candidates:
        if os.path.exists(path):
            try:
                root._icon = tk.PhotoImage(file=path)  # keep a reference
                root.iconphoto(True, root._icon)
            except tk.TclError:
                pass
            return


def main() -> int:
    if tk is None:
        print("Tkinter is not available. Install python3-tk.", file=sys.stderr)
        return 1
    root = tk.Tk(className="mystickeys")  # WM class matches the .desktop file
    _set_window_icon(root)
    try:
        # crisper fonts / dpi where available
        root.tk.call("tk", "scaling", 1.25)
    except Exception:
        pass
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", app.close)  # stop live effects first
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
