#!/usr/bin/env bash
# Install mystickeys system-wide and set up passwordless (udev) access.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"

if [[ $EUID -ne 0 ]]; then
    echo "This installer needs root. Re-running with sudo..."
    exec sudo bash "$0" "$@"
fi

echo "[*] Installing udev rule for non-root access..."
install -m 0644 "$HERE/99-mystickeys.rules" /etc/udev/rules.d/99-mystickeys.rules
udevadm control --reload-rules
udevadm trigger --subsystem-match=hidraw || true

echo "[*] Linking launcher to /usr/local/bin/mystickeys ..."
ln -sf "$HERE/bin/mystickeys" /usr/local/bin/mystickeys
chmod +x "$HERE/bin/mystickeys"

echo "[*] Adding MysticKeys to the application menu..."
ICONS=/usr/local/share/icons/hicolor
for size in 16 24 32 48 64 128 256 512; do
    install -Dm 0644 "$HERE/data/mystickeys-$size.png" \
        "$ICONS/${size}x${size}/apps/mystickeys.png"
done
install -Dm 0644 "$HERE/data/mystickeys.svg" "$ICONS/scalable/apps/mystickeys.svg"
install -Dm 0644 "$HERE/data/mystickeys.desktop" \
    /usr/local/share/applications/mystickeys.desktop
# refresh menu/icon caches (whichever tools this desktop has)
gtk-update-icon-cache -q -t "$ICONS" 2>/dev/null || true
update-desktop-database -q /usr/local/share/applications 2>/dev/null || true

echo
echo "[+] Done."
echo "    Try:  mystickeys color red"
echo "          mystickeys gui    (or open MysticKeys from the app menu)"
echo
echo "    If you still get a permission error, replug is not possible on a laptop"
echo "    so reboot once (or run 'sudo udevadm trigger') to apply the udev rule."
