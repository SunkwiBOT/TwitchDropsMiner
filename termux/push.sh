#!/bin/bash
# Control the Termux TwitchDropsMiner deployment on the phone.
#   ./push.sh              bundle + push + run installer (detached, long)
#   ./push.sh follow       tail the installer log
#   ./push.sh scripts      bundle + push + unpack only (no pip) - refresh code/shims
#   ./push.sh start        start the service (port 8081)
#   ./push.sh stop         stop it
#   ./push.sh restart      stop + start
#   ./push.sh status       port / processes / http / logs
#   ./push.sh boot         install /data/adb/service.d autostart hook
#   ./push.sh verifyboot   cold-stop -> run the hook -> assert 8081 comes back (no reboot)
set -e
SERIAL="${TDM_SERIAL:-}"
if [ -z "$SERIAL" ]; then
    SERIAL=$(adb devices | awk 'NR > 1 && $2 == "device" {print $1; exit}')
fi
if [ -z "$SERIAL" ]; then
    echo "ERROR: no adb device found; set TDM_SERIAL=<serial> or connect the phone" >&2
    exit 1
fi
UID_TERMUX="${TDM_UID:-10250}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT=/tmp/tdm.tar.gz
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'
ADB="adb -s $SERIAL"
w() { cygpath -w "$1" 2>/dev/null || echo "$1"; }
# push a windows script to /data/local/tmp (default name body.sh), strip CR, make readable
run_as_termux_file() {
    local dst="/data/local/tmp/${2:-body.sh}"
    $ADB push "$(w "$1")" "$dst" >/dev/null
    $ADB shell "su -c \"tr -d '\\r' < $dst > $dst.c && mv $dst.c $dst; chmod 644 $dst; chown $UID_TERMUX:$UID_TERMUX $dst\"" >/dev/null
}
run_termux_body() { $ADB shell "su -c 'su $UID_TERMUX -c \"sh /data/local/tmp/body.sh\"' 2>&1"; }
run_root_body() { $ADB shell "su -c 'sh /data/local/tmp/body.sh' 2>&1"; }

case "$1" in
follow)
    $ADB shell "su -c 'su $UID_TERMUX -c \"tail -n 60 /data/data/com.termux/files/home/tmp/tdm-install.log 2>/dev/null\"'"
    exit 0 ;;
status)
    run_as_termux_file "$REPO/termux/tdm-status.sh"; run_termux_body; exit 0 ;;
stop)
    run_as_termux_file "$REPO/termux/tdm-stop.sh"; run_termux_body; exit 0 ;;
start|restart)
    [ "$1" = restart ] && bash "$0" stop >/dev/null 2>&1
    run_as_termux_file "$REPO/termux/tdm-start.sh"; run_termux_body; exit 0 ;;
boot)
    bash "$0" scripts >/dev/null
    run_as_termux_file "$REPO/termux/twitchdrops-termux.sh" "twitchdrops-termux.sh"
    run_as_termux_file "$REPO/termux/install-boot.sh"
    run_root_body; exit 0 ;;
verifyboot)
    run_as_termux_file "$REPO/termux/boot-verify.sh"; run_root_body; exit 0 ;;
esac

echo "== build bundle =="
STAGE=$(mktemp -d)/app
mkdir -p "$STAGE"
tar -C "$REPO" \
    --exclude .git --exclude __pycache__ --exclude '*.pyc' --exclude tdm.tar.gz \
    --exclude .venv-preview --exclude env --exclude 'env/*' \
    --exclude panel.json --exclude .env --exclude settings.json --exclude cookies.jar \
    --exclude log.txt --exclude lock.file --exclude dump.dat --exclude boot.disabled \
    --exclude catalog.cache.json --exclude history.json --exclude history.json.new \
    --exclude history_game_map.json --exclude claimed_drops.json --exclude catalog.config.json \
    --exclude 'termux/boot.installed' --exclude 'logs/*' --exclude 'cache/*' \
    -cf - . | tar -C "$STAGE" -xf -
mkdir -p "$STAGE/shims"
cp -r "$REPO/termux/shims/." "$STAGE/shims/"
# 运行时状态绝不能进包：预览/本机调试写下的密码与密钥会覆盖手机上的真值
for forbidden in panel.json .env settings.json cookies.jar boot.disabled termux/boot.installed; do
    if [ -e "$STAGE/$forbidden" ]; then
        echo "FATAL: $forbidden 混进了部署包（会覆盖手机上的运行时状态）"; rm -rf "$(dirname "$STAGE")"; exit 1
    fi
done
tar -C "$STAGE" -czf "$OUT" .
rm -rf "$(dirname "$STAGE")"
echo "  bundle $OUT ($(du -h "$OUT" | cut -f1))"

echo "== push =="
$ADB push "$(w "$OUT")" /data/local/tmp/tdm.tar.gz >/dev/null
$ADB shell "su -c 'chmod 644 /data/local/tmp/tdm.tar.gz; chown $UID_TERMUX:$UID_TERMUX /data/local/tmp/tdm.tar.gz'" >/dev/null

if [ "$1" = "scripts" ]; then
    cat > /tmp/tdm-unpack.sh <<'EOS'
#!/system/bin/sh
set -e
export HOME=/data/data/com.termux/files/home
APP="$HOME/twitchdrops"
mkdir -p "$APP"
tar -xzf /data/local/tmp/tdm.tar.gz -C "$APP"
for f in "$APP"/termux/*.sh "$APP"/termux/*.py "$APP"/shims/*.py "$APP"/shims/PIL/*.py; do
    [ -f "$f" ] || continue
    tr -d '\r' < "$f" > "$f.u" && mv "$f.u" "$f"
done
for f in "$APP"/termux/*.sh; do chmod 755 "$f"; done
find "$APP" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
echo "unpacked -> $APP"
ls -l "$APP/termux" | tail -14
EOS
    run_as_termux_file /tmp/tdm-unpack.sh
    $ADB shell "su -c 'su $UID_TERMUX -c \"sh /data/local/tmp/body.sh\"' 2>&1"
    exit 0
fi

echo "== install (detached on device, follow with ./push.sh follow) =="
$ADB push "$(w "$REPO/termux/install.sh")" /data/local/tmp/tdm-install.sh >/dev/null
$ADB shell "su -c 'tr -d \"\\r\" < /data/local/tmp/tdm-install.sh > /data/local/tmp/tdm-install.sh.c && mv /data/local/tmp/tdm-install.sh.c /data/local/tmp/tdm-install.sh; chmod 644 /data/local/tmp/tdm-install.sh; chown $UID_TERMUX:$UID_TERMUX /data/local/tmp/tdm-install.sh'" >/dev/null
$ADB shell "su -c 'su $UID_TERMUX -c \"mkdir -p /data/data/com.termux/files/home/tmp; setsid nohup sh /data/local/tmp/tdm-install.sh > /data/data/com.termux/files/home/tmp/tdm-install.log 2>&1 &\"'" >/dev/null
echo "  launched; watch: bash push.sh follow"
