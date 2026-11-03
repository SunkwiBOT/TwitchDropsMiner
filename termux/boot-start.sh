#!/system/bin/sh
# Termux-side boot entry, run as the Termux app uid (10250) by the root service.d hook.
# tdm-start.sh already refuses to start a second instance (TCP probe on :8081),
# so calling this repeatedly is safe.
export HOME=/data/data/com.termux/files/home
APP="$HOME/twitchdrops"
[ -f "$APP/boot.disabled" ] && exit 0
exec sh "$APP/termux/tdm-start.sh"
