#!/system/bin/sh
# 启动面板服务（脱离 adb 会话存活）
. "/data/data/com.termux/files/home/twitchdrops/termux/tdm-env.sh"
. "/data/data/com.termux/files/home/twitchdrops/termux/tdm-pids.sh"

PORT="${TDM_WEB_PORT:-8081}"

port_up() {
    "$ENVDIR/bin/python" -c "import socket,sys; s=socket.socket(); s.settimeout(2); sys.exit(0 if s.connect_ex(('127.0.0.1',$PORT))==0 else 1)" 2>/dev/null
}

if port_up; then
    echo "already listening on :$PORT (pids: $(our_pids | tr '\n' ' '))"
    exit 0
fi
if [ -n "$(our_pids)" ]; then
    echo "supervisor is up but :$PORT is not answering - recent supervisor log:"
    tail -20 "$APP/logs/server.log" 2>/dev/null
    exit 1
fi

rm -f "$APP/stop.flag"
setsid nohup sh "$APP/termux/supervise.sh" >/dev/null 2>&1 &
echo "supervisor launched (pid $!)"

i=0
while [ $i -lt 30 ]; do
    sleep 2
    if port_up; then
        echo "OK: serving on :$PORT"
        curl -s -o /dev/null -w "  / -> HTTP %{http_code}（未设密码时应 302 到 /setup）\n" "http://127.0.0.1:$PORT/"
        curl -s -o /dev/null -w "  /setup -> HTTP %{http_code} (%{size_download} bytes)\n" "http://127.0.0.1:$PORT/setup"
        exit 0
    fi
    i=$((i + 1))
done
echo "FAILED: :$PORT never came up. Last log lines:"
tail -30 "$APP/logs/server.log" 2>/dev/null
tail -20 "$APP/log.txt" 2>/dev/null
exit 1
