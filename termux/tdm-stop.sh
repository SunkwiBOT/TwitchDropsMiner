#!/system/bin/sh
# Stop the Termux TwitchDropsMiner service (supervisor + miner).
. "/data/data/com.termux/files/home/twitchdrops/termux/tdm-env.sh"
. "/data/data/com.termux/files/home/twitchdrops/termux/tdm-pids.sh"

PORT="${TDM_WEB_PORT:-8081}"
touch "$APP/stop.flag"

PIDS=$(our_pids)
if [ -z "$PIDS" ]; then
    echo "no supervisor/miner process found"
else
    for pid in $PIDS; do
        kill "$pid" 2>/dev/null && echo "sent TERM to $pid"
    done
fi

i=0
while [ $i -lt 20 ]; do
    if "$ENVDIR/bin/python" -c "import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(0 if s.connect_ex(('127.0.0.1',$PORT))==0 else 1)" 2>/dev/null; then
        sleep 1
        i=$((i + 1))
    else
        echo ":$PORT no longer accepting connections"
        # stop.flag 故意保留：supervisor 看到它才会真正退出，下一次 tdm-start 会删掉
        j=0
        while [ -n "$(our_pids)" ] && [ $j -lt 8 ]; do sleep 1; j=$((j + 1)); done
        rm -f "$APP/supervisor.pid"
        exit 0
    fi
done

echo "WARNING: :$PORT still answering after 20s - sending KILL"
for pid in $(our_pids); do kill -9 "$pid" 2>/dev/null; done
sleep 1
rm -f "$APP/supervisor.pid"
exit 0
