#!/usr/bin/env bash
# Build the standalone mystickeys binary (no Python needed to run it).
#
# Builds inside Debian 11 (glibc 2.31) so the binary also runs on older
# distributions (Ubuntu 20.04+, Debian 11+, Fedora, Arch, ...).
# Needs Docker. Output: dist/mystickeys-<version>-linux-x86_64
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(python3 -c "import re;print(re.search(r'__version__ = \"(.+?)\"', open('$ROOT/mystickeys/__init__.py').read())[1])")"
NAME="mystickeys-$VERSION-linux-x86_64"

docker run --rm -v "$ROOT":/src:ro -v "$ROOT/dist":/out \
    -e NAME="$NAME" -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
    python:3.11-slim-bullseye bash -euc '
        # Debian 11 is end-of-life: its packages live on archive.debian.org
        sed -i -e "s|deb.debian.org/debian-security|archive.debian.org/debian-security|" \
               -e "s|deb.debian.org/debian|archive.debian.org/debian|" /etc/apt/sources.list
        apt-get update -qq && apt-get install -y -qq --no-install-recommends \
            binutils libtk8.6 libtcl8.6 >/dev/null
        python3 -c "import tkinter" || { echo "tkinter missing in build image"; exit 1; }
        pip install -q pyinstaller==6.11.1
        cp -r /src /build && cd /build
        pyinstaller --onefile --name "$NAME" --clean --noconfirm \
            --paths /build --collect-submodules mystickeys \
            --add-data "data/mystickeys-64.png:data" \
            packaging/entry.py >/dev/null
        cp "dist/$NAME" /out/
        cd /out && sha256sum "$NAME" > "$NAME.sha256"
        chown "$HOST_UID:$HOST_GID" "$NAME" "$NAME.sha256"
    '
echo "Built: $ROOT/dist/$NAME"
