#!/usr/bin/env bash
# Remove everything install.sh put on the system (your presets in
# ~/.config/mystickeys are kept).
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    # the background services are per-user: remove them before becoming root
    for unit in mystickeys-notify.service mystickeys-live.service; do
        systemctl --user disable --now "$unit" 2>/dev/null || true
        rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/$unit"
    done
    exec sudo bash "$0" "$@"
fi

rm -f /usr/local/bin/mystickeys \
      /etc/udev/rules.d/99-mystickeys.rules \
      /usr/local/share/applications/mystickeys.desktop \
      /usr/local/share/icons/hicolor/scalable/apps/mystickeys.svg
for size in 16 24 32 48 64 128 256 512; do
    rm -f "/usr/local/share/icons/hicolor/${size}x${size}/apps/mystickeys.png"
done
udevadm control --reload-rules || true
gtk-update-icon-cache -q -t /usr/local/share/icons/hicolor 2>/dev/null || true
update-desktop-database -q /usr/local/share/applications 2>/dev/null || true
echo "[+] mystickeys removed."
