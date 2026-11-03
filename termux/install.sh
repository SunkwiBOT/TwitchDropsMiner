#!/system/bin/sh
# Termux 安装脚本：Valentin-Metz/TwitchDropsMiner + 自带网页面板（run.py）。
# 由 Windows 侧 termux/push.sh 推送并后台执行；包体在 /data/local/tmp/tdm.tar.gz。
set -e

# --- Termux 环境：这里是 `su 10250 -c sh ...` 起来的，HOME 默认是 /data，必须先设好
export HOME=/data/data/com.termux/files/home
export PREFIX=/data/data/com.termux/files/usr
export PATH="$PREFIX/bin:$PREFIX/games:/product/bin:/apex/com.android.runtime/bin:/system/bin:/system/xbin"
export LD_LIBRARY_PATH="$PREFIX/lib"
export TMPDIR="$HOME/tmp"
export LANG=en_US.UTF-8
mkdir -p "$TMPDIR"

APP="$HOME/twitchdrops"
ENVDIR="$APP/env"
TARBALL=/data/local/tmp/tdm.tar.gz
PORT=8081

echo "== 1. 解包 =="
[ -f "$TARBALL" ] || { echo "缺少 $TARBALL"; exit 1; }
mkdir -p "$APP"
tar -xzf "$TARBALL" -C "$APP"
for f in "$APP"/termux/*.sh "$APP"/termux/*.py "$APP"/shims/*.py "$APP"/shims/PIL/*.py; do
    [ -f "$f" ] || continue
    tr -d '\r' < "$f" > "$f.u" && mv "$f.u" "$f"
done
for f in "$APP"/termux/*.sh; do chmod 755 "$f"; done
find "$APP" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
ls "$APP" | head -12

echo "== 2. 系统包 =="
for p in ca-certificates pkg-config libffi clang make; do
    if pkg install -y "$p" >/dev/null 2>&1; then echo "  ok    $p"; else echo "  SKIP  $p"; fi
done

echo "== 3. venv =="
[ -x "$ENVDIR/bin/python" ] || python3 -m venv "$ENVDIR"
"$ENVDIR/bin/python" -m pip install --upgrade pip setuptools wheel > "$TMPDIR/pip-base.log" 2>&1 \
    || { echo "基础 pip 安装失败"; tail -20 "$TMPDIR/pip-base.log"; exit 1; }

echo "== 4. Python 依赖（核心 + Flask；pystray/PyGObject/Pillow/zendriver 都不需要） =="
"$ENVDIR/bin/python" -m pip install "aiohttp>=3.9,<4.0" "Flask>=2.3.0" \
    > "$TMPDIR/pip.log" 2>&1
rc=$?
tail -4 "$TMPDIR/pip.log"
[ $rc -eq 0 ] || { echo "PIP 失败（完整日志：$TMPDIR/pip.log）"; tail -40 "$TMPDIR/pip.log"; exit 1; }

echo "== 5. 数据文件（不覆盖已有的 .env / settings.json / panel.json / cookies.jar） =="
cd "$APP"
if [ ! -f .env ]; then
    cat > .env <<EOS
TDM_WEB_PORT=$PORT
TDM_WEB_HOST=0.0.0.0
TDM_LOG_LEVEL=20
PANEL_SECRET=
EOS
fi
if grep -q '^TDM_WEB_PORT=' .env; then
    sed "s/^TDM_WEB_PORT=.*/TDM_WEB_PORT=$PORT/" .env > .env.new && mv .env.new .env
else
    printf 'TDM_WEB_PORT=%s\n' "$PORT" >> .env
fi
if [ ! -f settings.json ]; then
    # 只写两个字段；其余由 Settings 的默认值合并进来。默认 ENDING_SOONEST = 刷所有活动。
    cat > settings.json <<'EOS'
{
  "language": "简体中文",
  "dark_mode": true
}
EOS
fi
mkdir -p cache logs
echo "  .env:"; sed 's/^\(PANEL_SECRET=..\).*/\1... (隐藏)/' .env | grep -v '^$'

echo "== 6. 自检 =="
PYTHONPATH="$APP/shims" "$ENVDIR/bin/python" - <<'PY'
import ssl, sys
print("  python", sys.version.split()[0])
print("  CA 文件:", ssl.get_default_verify_paths().openssl_cafile)
import aiohttp, yarl, flask
print("  aiohttp", aiohttp.__version__, "| yarl", yarl.__version__, "| flask", flask.__version__)
import webgui
webgui.install()                      # 关键：必须在 import twitch 之前
import server.api                     # Flask 面板后端
from twitch import Twitch, _AuthState
from settings import Settings
from translate import _
print("  languages:", len(list(_.languages)))
assert _AuthState._browser_login is not None
print("  模块导入 OK；假 GUI 已接管 gui 模块")
g = webgui.GUIManager(None)
g.begin_campaign_load(121)
for i in range(61):
    g.note_campaign_added()
print("  载入进度自检:", g.load_snapshot()["done"], "/", g.load_snapshot()["total"])
PY

PYTHONPATH="$APP/shims" "$ENVDIR/bin/python" - <<'PY'
import socket, ssl
try:
    ctx = ssl.create_default_context()
    with ctx.wrap_socket(socket.create_connection(("twitch.tv", 443), timeout=15),
                         server_hostname="twitch.tv") as s:
        print(f"  出网 TLS OK ({s.version()})，根证书 {len(ctx.get_ca_certs())} 张")
except Exception as e:
    print("  出网 TLS 失败:", type(e).__name__, e)
PY

echo "== 7. 完成 -> $APP =="
