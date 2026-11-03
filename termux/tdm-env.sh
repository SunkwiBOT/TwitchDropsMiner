#!/system/bin/sh
# Shared environment for the Termux TwitchDropsMiner service.
# Self-contained: works both from an adb-driven `su 10250 -c` shell and from a
# Termux login shell, because everything is exported explicitly.
export HOME=/data/data/com.termux/files/home
export PREFIX=/data/data/com.termux/files/usr
export PATH="$PREFIX/bin:$PREFIX/games:/product/bin:/apex/com.android.runtime/bin:/system/bin:/system/xbin"
export LD_LIBRARY_PATH="$PREFIX/lib"
export TMPDIR="$HOME/tmp"
export LANG=en_US.UTF-8

APP="$HOME/twitchdrops"
ENVDIR="$APP/env"
export PYTHONPATH="$APP/shims"
export TDM_WEB_PORT=8081
export TDM_WEB_HOST=0.0.0.0
export TDM_LOG_LEVEL=20
# Python on Termux has no system trust store of its own unless ca-certificates is in.
[ -f "$PREFIX/etc/tls/cert.pem" ] && export SSL_CERT_FILE="$PREFIX/etc/tls/cert.pem"
export TZ=Asia/Shanghai
mkdir -p "$TMPDIR" "$APP/logs"
cd "$APP" || exit 1
