# mystickeys — MSI laptop keyboard RGB control (Linux)

Change the RGB keyboard backlight on MSI gaming laptops. No MSI Center, no
Windows, no vendor software. A single CLI/GUI that **auto-detects the
controller** and speaks the right protocol — effectively a mini-OpenRGB scoped
to MSI laptop keyboards.

- **Pure Python standard library** — talks to `/dev/hidraw` directly via
  `ioctl` HID feature reports. No `pip install` required.
- **Multi-backend**: MysticLight + SteelSeries controllers.
- CLI **and** a small Tkinter GUI.
- Zones, brightness, and effects (steady / breath / cycle / wave) where the
  controller supports them.

## Supported hardware
| Controller | USB ID(s) | Example models | Status |
|---|---|---|---|
| **MysticLight** MS-156x/160x | `1462:1601` `:1603` `:1605` `:1562-1564` `:1570` `:1572` — **plus any other `1462` laptop controller** with the same HID layout | Crosshair 16, Vector, Sword, newer Raider | ✅ supported |
| **SteelSeries 3-zone** | `1770:ff00` | older GL / GE / GP | ⚠️ implemented from docs, **experimental** |
| **SteelSeries per-key** | `1038:1122` | GE / GS / GT / Stealth | ↪️ detected, delegates to [`msi-perkeyrgb`](https://github.com/Askannz/msi-perkeyrgb) |

Check yours: `./bin/mystickeys list` shows every HID device and whether it matched,
and `./bin/mystickeys detect` shows the chosen controller.

### Models not in the table
You don't need to edit the code for an unlisted model. Detection reads each
device's HID report descriptor (no root needed). A MysticLight laptop
controller is recognized by its layout: a vendor-defined page with 64-byte
feature reports 1 and 2. `detect` then says `matched by HID descriptor`. MSI
motherboard/desktop RGB controllers (PIDs `7Bxx` and up) use a different
protocol and are never matched.

If auto-detection still misses your keyboard, force it:
```bash
./bin/mystickeys list                                         # find your /dev/hidrawN
sudo ./bin/mystickeys --device /dev/hidraw1 --backend mysticlight color red
```
Backends: `mysticlight`, `steelseries-3zone`, `steelseries-perkey`
(see `./bin/mystickeys info`). If an unlisted model works, please report its USB ID
so it can be added to the tested list.

> Protocol credits: MysticLight —
> [natanalt](https://gist.github.com/natanalt/06f1d5854230c788b9b9e7e33ab90b9f);
> SteelSeries — the MSIKLM / python-msikeys / msi-perkeyrgb projects.
>
> **Experimental backends** send their documented command bytes but have not
> been confirmed on real hardware. If you own such a laptop and test it, please
> report back so the status can be upgraded to "supported".

## Quick start (no install, needs root for raw HID)
```bash
cd mystickeys
sudo ./bin/mystickeys color red
sudo ./bin/mystickeys color '#00ff88'
sudo ./bin/mystickeys color 0,128,255 --brightness 60
sudo ./bin/mystickeys off
```

## Install (recommended — enables running without sudo)
```bash
sudo ./install.sh
# then, after the udev rule is active (reboot once on a laptop):
mystickeys color blue
mystickeys gui
```
The installer also adds **MysticKeys** (with its icon) to your application
menu under Settings. To change the icon, edit `data/mystickeys.svg` and run
`data/build-icons.sh data/mystickeys.svg data` to regenerate the PNGs.

## Usage
```
mystickeys [-z ZONE] [-b 0-100] [--device NODE] [--backend NAME] [--no-save] COMMAND

Zones:   -z 1|2|3|4|all     (default: all)
Bright:  -b 0..100          (default: 100)

Commands:
  color COLOR               solid color
  off                       backlight off
  zones C1 C2 C3 C4         a different color per zone (left -> right)
  breath COLOR [COLOR...]   breathing effect     (-s seconds)
  cycle  COLOR [COLOR...]   color-cycle effect   (-s seconds)
  wave   COLOR [COLOR...]   wave effect          (-s seconds, -d ltr|rtl)
  effect NAME [COLOR]       built-in effect      (-s seconds, -d ltr|rtl)
  effects                   list the built-in effects
  live NAME                 live effect until Ctrl+C (battery, cpu, temp,
                            music, typing, fire, thunder, lava;
                            -c COLOR for typing)
  detect                    show detected controller + /dev/hidraw node
  list                      list all HID devices and whether they match
  info                      list all supported controllers and capabilities
  notify on|off|status|test notification flash (-c COLOR with on/test)
  gui                       graphical color picker
```

Color formats: a name (`red`, `cyan`, `orange`, `warmwhite`, ...),
hex (`#ff8800` or `ff8800` or `#f80`), or `r,g,b` (`255,136,0`).

### Examples
```bash
mystickeys color purple
mystickeys -b 40 color white                 # dim white
mystickeys zones red green blue white        # rainbow across the 4 zones
mystickeys breath cyan -s 4                  # slow cyan breathing
mystickeys cycle red green blue -s 6
mystickeys wave magenta -d rtl
mystickeys off
```

## Color waves
Ready-made wave presets in the style of MSI Center, tuned by eye on a
Katana 15 (MS-1565):

| Preset | Colors | Speed |
|---|---|---|
| `rainbow` | red → orange → yellow → green → cyan → blue → purple | 6 s |
| `ocean` | blue, cyan, teal | 5 s |
| `aurora` | green, cyan, purple | 6 s |
| `neon` | yellow and purple stripes | 4 s |
| `police` | red and blue, each holding briefly | 2 s |
| `train` | **Night Train**: one warm-white light running across a dark keyboard, zone by zone | 3 s |

```bash
mystickeys effect ocean
mystickeys effect rainbow -s 10 -d rtl     # slower, right to left
```
They run on the keyboard's own controller (no CPU use, keep going with the
app closed, survive reboots). In the GUI they're in the **Color waves** card:
clicking one sets the speed slider (1–12 s) to its tuned speed, and the
speed and direction controls also apply to the Breath / Cycle / Wave buttons.

This keyboard has 4 lighting zones, not per-key lighting, so moving effects
travel zone by zone. Tip: the 4 zones blend into each other, so effects with clearly different
colors look best; similar shades side by side turn muddy.

## Live effects
These are computed by MysticKeys many times per second. Started from the
GUI's **Live** card they run as a small background service: they **keep
running after you close the app** and come back after login, until you click
the effect again or pick any other effect or color. They never write the
keyboard's memory; when they stop, the keyboard returns to its saved effect.

| Live effect | What it shows |
|---|---|
| `battery` | zones fill with the charge level (red → yellow → green); the next zone pulses while charging, and the bar breathes red below 15% |
| `cpu` | zones fill with CPU load, green → yellow → red |
| `temp` | zones fill with CPU temperature (40–95 °C), blue → green → yellow → red |
| `music` | 4-band equalizer of whatever is playing: bass (left, red) to treble (right, blue). Needs `parec` (PulseAudio/PipeWire) |
| `fire` | every zone flickers on its own like a flame: dark red, red and orange with the occasional flare |
| `thunder` | a dim, slowly shifting blue sky; every 1.5–5 s a strike of 1–3 white flickers hits one or two zones (sometimes all) |
| `lava` | slow purple, pink and orange blobs drifting between zones at different speeds |
| `typing` | the zone you type in lights up and fades (`-c` sets the color; the GUI uses the picked color) |

```bash
mystickeys live music                     # in this terminal, until Ctrl+C
mystickeys -b 60 live typing -c orange
mystickeys live fire -B                   # in the background, like the GUI
mystickeys live status                    # which one runs in the background
mystickeys live stop
```
`typing` reads the keyboard input device to know *where* you type; only the
zone is used and keys are never stored. It needs your user in the `input`
group (`sudo usermod -aG input $USER`, then log in again) or sudo.

## Notification flash
A feature you switch on or off: when a desktop notification arrives, the
keyboard blinks twice and then goes back to what it was showing (including a
running live effect). It runs as a small background service, so it keeps
working after you close the app and starts again when you log in.

- **GUI:** the **Flash on notifications** switch in the Live card (turning it
  on uses the picked color) and **Test** to try it.
- **Terminal:**
  ```bash
  mystickeys notify on -c cyan    # turn on, flash in cyan
  mystickeys notify test          # flash once now
  mystickeys notify status
  mystickeys notify off
  ```

Nothing flashes while Do Not Disturb is on, and a burst of notifications
gives a single flash. Only the arrival of a notification is used, never its
text. To ignore an app, add its name to `"ignore"` in
`~/.config/mystickeys/notify.json` (e.g. `"ignore": ["Spotify"]`).

By default settings are saved to the keyboard flash so they persist across
reboots. Pass `--no-save` to apply without writing flash.

## Use as a library
```python
from mystickeys import MSIKeyboard
with MSIKeyboard() as kb:
    kb.set_color((255, 0, 128))
```

## Troubleshooting
- **Permission denied** opening `/dev/hidrawN`: run with `sudo`, or
  `sudo ./install.sh` and reboot once so the udev rule takes effect.
- **Device not found**: run `./bin/mystickeys list`. If your keyboard is there but
  not matched, use `--device /dev/hidrawN --backend NAME` (see above). The
  udev rule covers every MSI laptop PID (`1462:1xxx`). For non-root access
  with another ID, add a line to `99-mystickeys.rules`.
- **GUI won't start**: install Tk — `sudo apt install python3-tk`.

## Uninstall
```bash
./uninstall.sh      # asks for sudo; your presets in ~/.config/mystickeys are kept
```
