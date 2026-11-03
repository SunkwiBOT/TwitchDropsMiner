#!/system/bin/sh
# Supervise loop: keep run.py alive until stop.flag shows up.
. "/data/data/com.termux/files/home/twitchdrops/termux/tdm-env.sh"

LOG="$APP/logs/server.log"
mkdir -p "$APP/logs"
# 日志超过 8 MB 时留最后 2 MB，避免长期挂机把 /data 写满（core 的 log.txt 同理）
for f in "$LOG" "$APP/log.txt"; do
    [ -f "$f" ] || continue
    size=$(wc -c < "$f" 2>/dev/null || echo 0)
    if [ "$size" -gt 8388608 ]; then
        tail -c 2000000 "$f" > "$f.tmp" && mv "$f.tmp" "$f"
    fi
done
echo "=== supervisor start $(date) (pid $$) ===" >> "$LOG"
echo $$ > "$APP/supervisor.pid"
while [ ! -f "$APP/stop.flag" ]; do
    echo "--- run.py start $(date) ---" >> "$LOG"
    "$ENVDIR/bin/python" "$APP/run.py" >> "$LOG" 2>&1
    rc=$?
    echo "--- run.py exited rc=$rc $(date) ---" >> "$LOG"
    [ -f "$APP/stop.flag" ] && break
    sleep 5
done
rm -f "$APP/supervisor.pid"
echo "=== supervisor exit $(date) ===" >> "$LOG"
