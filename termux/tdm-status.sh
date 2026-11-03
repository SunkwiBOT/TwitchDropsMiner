#!/system/bin/sh
# Status of the Termux TwitchDropsMiner service.
. "/data/data/com.termux/files/home/twitchdrops/termux/tdm-env.sh"
. "/data/data/com.termux/files/home/twitchdrops/termux/tdm-pids.sh"

PORT="${TDM_WEB_PORT:-8081}"

echo "== port =="
"$ENVDIR/bin/python" -c "import socket,sys; s=socket.socket(); s.settimeout(2); print('  127.0.0.1:$PORT', 'LISTENING' if s.connect_ex(('127.0.0.1',$PORT))==0 else 'down')"

echo "== processes =="
for pid in $(our_pids); do
    printf '  %s %s\n' "$pid" "$(tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null)"
done

echo "== http =="
curl -s -o /dev/null -w '  /login              -> %{http_code} (%{size_download} bytes)\n' "http://127.0.0.1:$PORT/login"
curl -s -o /dev/null -w '  /setup              -> %{http_code}\n' "http://127.0.0.1:$PORT/setup"
curl -s -o /dev/null -w '  /                   -> %{http_code}（未登录应 302）\n' "http://127.0.0.1:$PORT/"
curl -s -o /dev/null -w '  /api/state          -> %{http_code}（未登录应 401）\n' "http://127.0.0.1:$PORT/api/state"

echo "== autostart =="
if [ -f "$APP/termux/boot.installed" ]; then
    if [ -f "$APP/boot.disabled" ]; then echo "  boot hook installed, disabled by panel"; else echo "  boot hook installed, enabled"; fi
else
    echo "  boot hook NOT installed (push.sh boot)"
fi

echo "== miner log (log.txt) =="
tail -12 "$APP/log.txt" 2>/dev/null | sed 's/^/  /'
echo "== supervisor log (logs/server.log) =="
tail -10 "$APP/logs/server.log" 2>/dev/null | sed 's/^/  /'
