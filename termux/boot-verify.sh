#!/system/bin/sh
# Cold-stop -> run the boot hook -> assert the service comes back. Does NOT reboot the
# phone; it exercises the same code path Magisk's service.d runs at boot. (Run as root.)
D=/data/data/com.termux/files/home/twitchdrops
U=10250
HOOK=/data/adb/service.d/twitchdrops-termux.sh
LOG=/data/adb/service.d/twitchdrops-termux.log
FAILED=0

SU_BIN=/system/bin/sh
for c in /sbin/su /debug_ramdisk/su /system/bin/su; do [ -x "$c" ] && SU_BIN="$c" && break; done

probe() { "$SU_BIN" "$U" -c "$D/env/bin/python $D/termux/portprobe.py 8081" >/dev/null 2>&1; }

miner_pids() {
    for d in /proc/[0-9]*; do
        pid=${d#/proc/}
        [ -r "$d/cmdline" ] || continue
        cmd=$(tr '\0' ' ' < "$d/cmdline" 2>/dev/null) || continue
        case "$cmd" in *"$D/run.py"*) echo "$pid" ;; esac
    done
}

echo "== 0. current state =="
probe && echo "  :8081 up" || echo "  :8081 down"

echo "== 1. cold stop =="
"$SU_BIN" "$U" -c "sh $D/termux/tdm-stop.sh" 2>&1 | sed 's/^/  /'
if probe; then echo "  FAIL: port still answering after stop"; FAILED=1; else echo "  ok: port released"; fi

echo "== 2. run the boot hook (simulates Magisk service.d at boot) =="
sh "$HOOK"
i=0
while [ $i -lt 30 ]; do
    sleep 5
    if probe; then echo "  ok: :8081 back up after $(( (i + 1) * 5 ))s"; break; fi
    i=$((i + 1))
done
probe || { echo "  FAIL: :8081 never came back"; FAILED=1; }

echo "== 3. hook log tail =="
tail -n 6 "$LOG" 2>/dev/null | sed 's/^/  /'

echo "== 4. miner process environment =="
MPID=$(miner_pids | head -1)
if [ -n "$MPID" ]; then
    echo "  miner pid $MPID"
    tr '\0' '\n' < "/proc/$MPID/environ" 2>/dev/null | grep -E '^(TZ|SSL_CERT_FILE|PYTHONPATH|TDM_WEB_PORT|HOME)=' | sed 's/^/    /'
    for want in TZ= SSL_CERT_FILE= PYTHONPATH= TDM_WEB_PORT=8081; do
        if ! tr '\0' '\n' < "/proc/$MPID/environ" 2>/dev/null | grep -q "^$want"; then
            echo "  FAIL: env missing $want"
            FAILED=1
        fi
    done
else
    echo "  FAIL: no run.py process found"
    FAILED=1
fi

echo "== 5. run the hook again (must skip, not double-start) =="
sh "$HOOK"
sleep 12
tail -n 4 "$LOG" 2>/dev/null | sed 's/^/  /'
if tail -n 6 "$LOG" 2>/dev/null | grep -q "already listening"; then
    echo "  ok: second run skipped"
else
    echo "  WARN: last log lines do not say 'already listening'"
fi

echo "== 6. autostart switch =="
touch "$D/boot.disabled"
"$SU_BIN" "$U" -c "sh $D/termux/tdm-stop.sh" >/dev/null 2>&1
sh "$HOOK"
sleep 12
if probe; then echo "  FAIL: boot.disabled did not stop the hook"; FAILED=1; else echo "  ok: hook skipped while boot.disabled exists"; fi
rm -f "$D/boot.disabled"
sh "$HOOK"
i=0
while [ $i -lt 24 ]; do
    sleep 5
    probe && break
    i=$((i + 1))
done
probe && echo "  ok: hook started again after boot.disabled removed" || { echo "  FAIL: no restart after re-enable"; FAILED=1; }

echo "== 7. final state =="
probe && echo "  :8081 up" || { echo "  :8081 DOWN"; FAILED=1; }
N=$(miner_pids | wc -l)
echo "  run.py processes: $N (must be 1)"
[ "$N" = "1" ] || FAILED=1

echo
if [ $FAILED -eq 0 ]; then echo "BOOT-HOOK-VERIFY: PASS"; else echo "BOOT-HOOK-VERIFY: FAIL"; fi
