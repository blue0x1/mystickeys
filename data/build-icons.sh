#!/usr/bin/env bash
# Regenerate the PNG icons from the SVG (needs google-chrome + python3-pil).
# Usage: data/build-icons.sh data/mystickeys.svg data
set -euo pipefail
SVG="$1"; OUT="$2"; TMP="$(mktemp -d)"
printf '<html><body style="margin:0"><img src="file://%s" width="1024" height="1024"></body></html>' "$(realpath "$SVG")" > "$TMP/i.html"
timeout 60 google-chrome --headless=new --disable-gpu --no-sandbox --hide-scrollbars \
  --default-background-color=00000000 --window-size=1024,1024 \
  --screenshot="$TMP/m.png" "file://$TMP/i.html" 2>/dev/null
python3 -I -c '
import sys
from PIL import Image
m = Image.open(sys.argv[1]).convert("RGBA")
for s in (16, 24, 32, 48, 64, 128, 256, 512):
    m.resize((s, s), Image.LANCZOS).save(f"{sys.argv[2]}/mystickeys-{s}.png", optimize=True)
' "$TMP/m.png" "$OUT"
rm -rf "$TMP"
