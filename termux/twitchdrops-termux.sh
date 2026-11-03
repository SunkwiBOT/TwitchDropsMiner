#!/system/bin/sh
# Root service.d hook: wait for boot + user unlock, then start the panel as Termux uid.
# Installed to /data/adb/service.d/twitchdrops-termux.sh by install-boot.sh.
APP=/data/data/com.termux/files/home/twitchdrops
LOG=/data/adb/service.d/twitchdrops-termux.log

{
    echo "=== boot hook $(date) ==="
    i=0
    while [ $i -lt 60 ]; do
        [ "$(getprop sys.boot_completed)" = "1" ] && [ -d "$APP" ] && break
        sleep 5
        i=$((i + 1))
    done
    # Termux 的 home 在用户解锁前可能不可读，再等一会儿
    sleep 10
    if [ -f "$APP/boot.disabled" ]; then
        echo "$(date) autostart disabled by panel"
        exit 0
    fi
    SU_BIN=su
    for c in /sbin/su /debug_ramdisk/su /system/bin/su; do
        [ -x "$c" ] && SU_BIN="$c" && break
    done
    "$SU_BIN" 10250 -c "sh $APP/termux/boot-start.sh"
} >> "$LOG" 2>&1 &
