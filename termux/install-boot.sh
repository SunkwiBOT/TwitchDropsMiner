#!/system/bin/sh
# Install the boot hook into /data/adb/service.d (run as root) + leave a marker
# for the panel's autostart checkbox. Source comes from /data/local/tmp.
set -e
SRC=/data/local/tmp/twitchdrops-termux.sh
DST=/data/adb/service.d/twitchdrops-termux.sh
APP=/data/data/com.termux/files/home/twitchdrops

[ -f "$SRC" ] || { echo "missing $SRC (push.sh boot pushes it)"; exit 1; }
mkdir -p /data/adb/service.d

tr -d '\r' < "$SRC" > "$DST"
chown 0:0 "$DST"
chmod 700 "$DST"
chcon u:object_r:adb_data_file:s0 "$DST" 2>/dev/null || true

# marker for the web panel (readable by uid 10250)
mkdir -p "$APP/termux"
echo "installed $(date)" > "$APP/termux/boot.installed"
chown 10250:10250 "$APP/termux/boot.installed"
chmod 644 "$APP/termux/boot.installed"

echo "installed:"
ls -Zl "$DST"
echo "--- head ---"
head -3 "$DST"
echo "--- service.d now holds ---"
ls -l /data/adb/service.d/
