"""server/api.py - TwitchDropsMiner 的网页面板后端。

只做两件事：把 webgui 捕获到的核心状态用 JSON 暴露出去；把用户在网页上的操作
（切频道、领取、改优先/排除列表、重载、重新登录）安全地投递回 asyncio 核心线程。
上游核心代码不改动。
"""
from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import os
import secrets
import time
from datetime import timedelta
from pathlib import Path

from flask import (Flask, jsonify, redirect, render_template, request,
                   session, url_for)

from constants import State
import catalog
import history

ROOT = Path(__file__).resolve().parent.parent
# 面板口令与会话密钥是**运行时状态**，只存在于设备上。允许改路径是为了让 PC 上的
# 离线预览不把假密码/密钥写进仓库根目录（写进去会被 push.sh 打包回手机，
# 覆盖掉你真正设的面板密码 —— 2026-10-29 就是这么把登录搞坏的）。
PANEL_FILE = Path(os.environ.get("TDM_PANEL_FILE") or (ROOT / "panel.json"))
ENV_FILE = Path(os.environ.get("TDM_ENV_FILE") or (ROOT / ".env"))

core: dict = {"loop": None, "client": None, "gui": None}

app = Flask(__name__,
            static_folder=str(Path(__file__).parent / "static"),
            template_folder=str(Path(__file__).parent / "templates"))

# 静态资源版本 = 进程启动时间：改了前端只要重启，手机浏览器就不会继续吃旧缓存
ASSET_V = str(int(time.time()))
app.jinja_env.globals["ASSET_V"] = ASSET_V


# ------------------------------------------------------------ 界面文案
# 上游 lang/*.json 覆盖了 gui.* 的全部字段，面板固定文案一律走 `t()`；
# 面板自身新增的句子（空状态、提示、toast）只有中英两份，其它语言回落英文。

PANEL_UI = {
    "zh": {
        "title": "Twitch 挖宝鼠",
        "panel_logout": "退出面板",
        "conn_connecting": "正在连接",
        "conn_connected": "已连接",
        "conn_lost": "连接中断",
        "user_logged": "已登录",
        "user_unknown": "未登录",
        "status_meta": "核心 {state} · 活动 {campaigns} · 频道 {channels} · 可领取 {claims}",
        "load_title": "库存载入进度",
        "load_running": "正在将掉宝活动列表添加至库存...({done}/{total})",
        "load_done": "活动载入完成：共 {total} 个",
        "ws_empty": "尚未建立 WebSocket 连接。",
        "login_status": "状态:",
        "login_user_id": "用户ID：",
        "login_logged_hint": "会话已从 cookies 恢复，无需任何操作。",
        "login_relogin": "重新登录（设备码）",
        "login_code_hint": "请在浏览器里打开下面的网址并登录 Twitch，输入这个验证码：",
        "login_code_expiry": "验证码剩余有效期约 {minutes} 分钟",
        "login_confirm": "已授权，立即刷新",
        "login_poll_hint": "授权成功后无需任何操作：核心自己会轮询到令牌并开始载入库存（通常几秒到十几秒）。",
        "login_start": "登录",
        "login_session_restored": "会话已从 cookies 恢复。",
        "login_wait_password": "核心正在等待账号密码登录：",
        "login_username": "用户名",
        "login_password": "密码",
        "login_twofa": "双重验证码（没有就留空）",
        "login_submit": "登录",
        "progress_empty": "当前没有正在推进的掉宝。",
        "claimed_items": "本次已领取：",
        "history_tab": "历史",
        "history_title": "历史掉宝",
        "history_hint": "记录 Twitch「已领取」奖励，活动过期后仍保留。优先列表里的游戏排在最前（没有记录的也会列出）；旧活动无法识别游戏的记录放在最后。同名奖励默认堆叠，点开看每次领取详情。",
        "history_only_priority": "只看优先列表游戏",
        "history_summary": "共 {n} 件物品 · {m} 款游戏有记录",
        "history_priority": "优先 #{n}",
        "history_group_meta": "{n} 件 · 最近 {time}",
        "history_group_empty": "暂无领取记录",
        "history_toggle": "展开/收起",
        "history_unknown_game": "未归类（旧活动）",
        "catalog_interval": "掉宝活动刷新频率（分钟）",
        "catalog_interval_hint": "最低 5 分钟（公开目录免费档限制），最高 1440 分钟；改动会在下一轮探测时生效，最多再等 5 分钟。",
        "catalog_interval_invalid": "请输入 5–1440 之间的分钟数",
        "minutes": "{n} 分钟",
        "history_claimed_at": "领取于 {time}",
        "history_recorded_at": "记录于 {time}",
        "history_campaign_meta": "活动：{campaign}",
        "history_empty": "还没有历史记录。面板看到已领取的掉宝后会自动记下来。",
        "history_empty_priority": "优先列表里的游戏还没有领取记录。",
        "logs_empty": "暂无日志。",
        "channels_empty": "当前没有候选频道（通常是因为还没有可刷的活动）。",
        "channels_empty_hint": "载入库存并搜索直播频道后，这里才会出现频道。",
        "channels_summary": "共 {n} 个频道 · 在线 {online} · 正在观看 {watching}",
        "notif_empty": "暂无通知。",
        "inv_empty_title": "当前账号没有可刷的掉宝活动",
        "inv_empty_text": "这是 Twitch 按账号与出口地区返回的真实结果（currentUser.dropCampaigns 为空），不是面板的问题。可以点上面的「刷新」再拉一次，或检查账号资格与代理。",
        "inv_summary": "库存 {n} 个活动，按当前筛选显示 {m} 个",
        "inv_no_match": "当前筛选条件下没有可显示的活动。",
        "inv_filters_hint": "勾选=显示该类；与桌面版同一组开关，改动会自动记住（只影响本页显示）。",
        "inv_refresh_hint": "「刷新」= 向 Twitch 重新拉取库存（等价设置页的刷新），不是保存筛选。",
        "set_immediate_hint": "改动会立即生效并写入 settings.json；多数选项需要刷新库存或重启核心后生效。",
        "set_autostart_na": "尚未安装 service.d 自启钩子；用 push.sh boot 安装后才可切换。",
        "set_tray_na": "安卓上没有系统托盘，此项不生效。",
        "set_quality": "连接质量（1-6）",
        "set_quality_hint": "上游桌面版未暴露，只存在于 settings.json；核心会把值钳在 1-6。",
        "set_proxy_ph": "http://username:password@address:port",
        "set_proxy_hint": "必须同时带主机与端口；留空表示不使用代理。",
        "set_lang_hint": "(需要重启)",
        "prio_empty": "优先列表为空。",
        "excl_empty": "排除列表为空。",
        "cand_open": "候选",
        "cand_hint": "候选与桌面版下拉同源：只来自已加载的掉宝库存；库存为空时可直接手输游戏名。",
        "cand_none": "候选里没有匹配「{q}」的游戏；直接按「添加」也能入库。",
        "add": "添加",
        "add_ph": "游戏名称",
        "confirm_title": "请确认",
        "confirm_ok": "确定",
        "confirm_cancel": "取消",
        "toast_saved": "已保存",
        "toast_failed": "操作失败",
        "toast_added": "已添加 {name}",
        "toast_removed": "已移除 {name}",
        "toast_switch": "已请求切换到 {name}",
        "toast_claimed": "已领取 {name}",
        "toast_reload": "已请求刷新库存",
        "toast_filter_saved": "筛选已记住（只影响本页显示）",
        "toast_lang_restart": "语言已切换，刷新页面后面板文案生效",
        "toast_relogin": "已请求设备码，稍等片刻",
        "toast_submitted": "已提交，等待核心登录",
        "autostart_on": "开机自启已开启",
        "autostart_off": "开机自启已关闭",
        "relogin_title": "重新登录",
        "relogin_text": "会清掉本机保存的 Twitch 会话并重新走一次设备码授权，当前进度不受影响。确定？",
        "logout_title": "退出登录",
        "logout_text": "会向 Twitch 撤销 access token、清空 cookies 并重启核心，之后需要重新走设备码。确定？",
        "logout_ok": "已在 Twitch 侧撤销令牌",
        "logout_local": "本地会话已清除（Twitch 撤销未成功）",
        "auth_setup_lead": "首次使用：设置一个面板密码。它与 Twitch 密码无关。",
        "auth_login_lead": "请输入面板密码。",
        "auth_password": "面板密码",
        "auth_password2": "确认面板密码",
        "auth_submit_setup": "设置并进入",
        "auth_submit_login": "进入面板",
        "auth_err_short": "密码至少 8 位",
        "auth_err_mismatch": "两次输入的密码不一致",
        "auth_err_wrong": "密码不正确",
        "help_version": "版本",
        "help_fork": "本 fork",
        "help_panel": "面板",
        "filter_refresh": "刷新",
        "claim": "领取",
        "load_hidden": "载入中…",
        "state_line": "核心状态",
    },
    "en": {
        "title": "Twitch Drops Miner",
        "panel_logout": "Log out",
        "conn_connecting": "Connecting",
        "conn_connected": "Connected",
        "conn_lost": "Disconnected",
        "user_logged": "Logged in",
        "user_unknown": "Not logged in",
        "status_meta": "core {state} · {campaigns} campaigns · {channels} channels · {claims} claimable",
        "load_title": "Inventory load progress",
        "load_running": "Adding drops campaigns to the inventory... ({done}/{total})",
        "load_done": "Campaigns loaded: {total}",
        "ws_empty": "No websocket connection yet.",
        "login_status": "Status:",
        "login_user_id": "User ID:",
        "login_logged_hint": "Session restored from cookies, nothing to do.",
        "login_relogin": "Log in again (device code)",
        "login_code_hint": "Open the page below in a browser, log in to Twitch, and enter this code:",
        "login_code_expiry": "Code expires in about {minutes} min",
        "login_confirm": "Authorized, refresh now",
        "login_poll_hint": "Nothing else to do: the core polls for the token and starts loading the inventory (usually a few seconds).",
        "login_start": "Log in",
        "login_session_restored": "Session restored from cookies.",
        "login_wait_password": "The core is waiting for username/password login:",
        "login_username": "Username",
        "login_password": "Password",
        "login_twofa": "2FA code (leave empty if none)",
        "login_submit": "Sign in",
        "progress_empty": "No drop is currently in progress.",
        "claimed_items": "Claimed this campaign:",
        "history_tab": "History",
        "history_title": "Drop history",
        "history_hint": "Twitch-claimed rewards, kept after the campaigns expire. Priority-list games come first (even with no claims yet); old claims whose game cannot be identified go last. Same-name rewards are stacked; click to expand each claim.",
        "history_only_priority": "Only priority-list games",
        "history_summary": "{n} items · {m} games with records",
        "history_priority": "Priority #{n}",
        "history_group_meta": "{n} items · latest {time}",
        "history_group_empty": "No claims yet",
        "history_toggle": "Expand/collapse",
        "history_unknown_game": "Uncategorized (old campaigns)",
        "catalog_interval": "Campaign discovery interval (minutes)",
        "catalog_interval_hint": "5–1440 minutes. The free catalog allows at most one request per 5 minutes; changes apply on the next probe (up to 5 minutes later).",
        "catalog_interval_invalid": "Enter a value between 5 and 1440 minutes",
        "minutes": "{n} min",
        "history_claimed_at": "Claimed {time}",
        "history_recorded_at": "Recorded {time}",
        "history_campaign_meta": "Campaign: {campaign}",
        "history_empty": "No history yet. The panel records items as soon as it sees them claimed.",
        "history_empty_priority": "No claimed items for priority-list games yet.",
        "logs_empty": "No log lines yet.",
        "channels_empty": "No candidate channels yet (usually because there are no active campaigns).",
        "channels_empty_hint": "Channels show up after the inventory is loaded and live channels are searched.",
        "channels_summary": "{n} channels · {online} online · watching {watching}",
        "notif_empty": "No notifications.",
        "inv_empty_title": "This account has no farmable drops campaigns",
        "inv_empty_text": "This is what Twitch returns for the account and region (currentUser.dropCampaigns is empty), not a panel fault. Try Refresh again, or check account eligibility and proxy.",
        "inv_summary": "{n} campaigns in inventory, {m} shown by the current filters",
        "inv_no_match": "No campaign matches the current filters.",
        "inv_filters_hint": "Checked = show that kind; same switches as the desktop app, remembered per browser (display only).",
        "inv_refresh_hint": "Refresh = fetch the inventory from Twitch again (same as the settings button), not save filters.",
        "set_immediate_hint": "Changes apply immediately and are written to settings.json; most take effect after a reload or core restart.",
        "set_autostart_na": "The service.d hook is not installed; run push.sh boot first.",
        "set_tray_na": "No system tray on Android; this option has no effect.",
        "set_quality": "Connection quality (1-6)",
        "set_quality_hint": "Not exposed in the desktop GUI, only in settings.json; clamped to 1-6 by the core.",
        "set_proxy_ph": "http://username:password@address:port",
        "set_proxy_hint": "Host and port are required; empty means no proxy.",
        "set_lang_hint": "(requires restart)",
        "prio_empty": "Priority list is empty.",
        "excl_empty": "Exclude list is empty.",
        "cand_open": "Candidates",
        "cand_hint": "Candidates come from the loaded inventory only, same as the desktop dropdown; type a name directly if empty.",
        "cand_none": "No candidate matches \"{q}\"; you can still add it directly.",
        "add": "Add",
        "add_ph": "Game name",
        "confirm_title": "Please confirm",
        "confirm_ok": "OK",
        "confirm_cancel": "Cancel",
        "toast_saved": "Saved",
        "toast_failed": "Operation failed",
        "toast_added": "Added {name}",
        "toast_removed": "Removed {name}",
        "toast_switch": "Switching to {name}",
        "toast_claimed": "Claimed {name}",
        "toast_reload": "Inventory reload requested",
        "toast_filter_saved": "Filters remembered (display only)",
        "toast_lang_restart": "Language changed; reload the page to apply panel labels",
        "toast_relogin": "Device code requested, hang on",
        "toast_submitted": "Submitted, waiting for the core",
        "autostart_on": "Autostart enabled",
        "autostart_off": "Autostart disabled",
        "relogin_title": "Log in again",
        "relogin_text": "This clears the saved Twitch session and starts a new device-code login. Progress is not affected. Continue?",
        "logout_title": "Log out",
        "logout_text": "This revokes the access token at Twitch, clears cookies and restarts the core. Continue?",
        "logout_ok": "Token revoked at Twitch",
        "logout_local": "Local session cleared (Twitch revoke failed)",
        "auth_setup_lead": "First run: choose a panel password. It is unrelated to your Twitch password.",
        "auth_login_lead": "Enter the panel password.",
        "auth_password": "Panel password",
        "auth_password2": "Confirm panel password",
        "auth_submit_setup": "Set and continue",
        "auth_submit_login": "Enter panel",
        "auth_err_short": "At least 8 characters",
        "auth_err_mismatch": "The two passwords differ",
        "auth_err_wrong": "Wrong password",
        "help_version": "Version",
        "help_fork": "This fork",
        "help_panel": "Panel",
        "filter_refresh": "Refresh",
        "claim": "Claim",
        "load_hidden": "Loading…",
        "state_line": "Core state",
    },
}

# 面板前端会动态拼的文案，全部由服务端按当前语言下发（见 _js_i18n）
JS_KEYS = (
    "gui.tabs.main", "gui.tabs.inventory", "gui.tabs.settings", "gui.tabs.help",
    "gui.status.name", "gui.output",
    "gui.websocket.name", "gui.websocket.websocket", "gui.websocket.initializing",
    "gui.websocket.connected", "gui.websocket.disconnected", "gui.websocket.connecting",
    "gui.websocket.disconnecting", "gui.websocket.reconnecting",
    "gui.login.name", "gui.login.logged_in", "gui.login.logged_out", "gui.login.logging_in",
    "gui.login.required", "gui.login.request", "gui.login.username", "gui.login.password",
    "gui.login.twofa_code", "gui.login.button",
    "gui.progress.name", "gui.progress.drop", "gui.progress.game", "gui.progress.campaign",
    "gui.progress.remaining", "gui.progress.drop_progress", "gui.progress.campaign_progress",
    "gui.channels.name", "gui.channels.switch", "gui.channels.online", "gui.channels.pending",
    "gui.channels.offline", "gui.channels.headings.channel", "gui.channels.headings.status",
    "gui.channels.headings.game", "gui.channels.headings.viewers",
    "gui.inventory.filter.name", "gui.inventory.filter.show", "gui.inventory.filter.not_linked",
    "gui.inventory.filter.upcoming", "gui.inventory.filter.expired",
    "gui.inventory.filter.excluded", "gui.inventory.filter.finished",
    "gui.inventory.filter.refresh", "gui.inventory.status.linked",
    "gui.inventory.status.not_linked", "gui.inventory.status.active",
    "gui.inventory.status.upcoming", "gui.inventory.status.expired",
    "gui.inventory.status.claimed", "gui.inventory.status.ready_to_claim",
    "gui.inventory.starts", "gui.inventory.ends", "gui.inventory.allowed_channels",
    "gui.inventory.all_channels", "gui.inventory.and_more", "gui.inventory.percent_progress",
    "gui.inventory.minutes_progress",
    "gui.settings.general.name", "gui.settings.general.autostart", "gui.settings.general.tray",
    "gui.settings.general.tray_notifications", "gui.settings.general.dark_mode",
    "gui.settings.general.priority_mode", "gui.settings.general.proxy",
    "gui.settings.advanced.name", "gui.settings.advanced.warning",
    "gui.settings.advanced.warning_text", "gui.settings.advanced.enable_badges_emotes",
    "gui.settings.advanced.available_drops_check",
    "gui.settings.priority_modes.priority_only", "gui.settings.priority_modes.ending_soonest",
    "gui.settings.priority_modes.low_availability",
    "gui.settings.game_name", "gui.settings.priority", "gui.settings.exclude",
    "gui.settings.reload", "gui.settings.reload_text",
    "gui.help.links.name", "gui.help.links.inventory", "gui.help.links.campaigns",
    "gui.help.how_it_works", "gui.help.how_it_works_text", "gui.help.getting_started",
    "gui.help.getting_started_text", "gui.help.invalidate.text", "gui.help.invalidate.button",
    "gui.tray.notification_title",
)


def _lang() -> str:
    lang = ""
    client = core.get("client")
    if client is not None:
        try:
            lang = str(client.settings.language or "")
        except Exception:
            lang = ""
    if not lang:
        # 核心还没构造出来时（/setup 首次打开）直接读 settings.json
        try:
            from constants import SETTINGS_PATH
            from utils import json_load
            lang = str(json_load(SETTINGS_PATH, {}).get("language") or "")
        except Exception:
            lang = ""
    if not lang:
        try:
            from translate import _
            lang = str(_.current)
        except Exception:
            lang = ""
    return "zh" if lang.startswith("简体") else "en"


def ui(key: str) -> str:
    """面板自己的文案；缺翻译就回落英文，再缺就把 key 原样吐出来。"""
    table = PANEL_UI.get(_lang()) or PANEL_UI["en"]
    return table.get(key) or PANEL_UI["en"].get(key) or key


def t(*path: str) -> str:
    """取上游自己 lang/*.json 里的文案，保证与桌面版一字不差。"""
    try:
        from translate import _
        return str(_(*path))
    except Exception:
        return str(path[-1])


def _js_i18n() -> dict:
    data = {key: t(*key.split(".")) for key in JS_KEYS}
    data["ui"] = dict(PANEL_UI.get(_lang()) or PANEL_UI["en"])
    return data


def dark_mode() -> bool:
    client = core.get("client")
    try:
        return bool(client.settings.dark_mode)
    except Exception:
        # 核心还没起来时按面板自己的默认（夜间）渲染，避免白屏闪一下再变黑
        return True


app.jinja_env.globals["t"] = t
app.jinja_env.globals["ui"] = ui
app.jinja_env.globals["LANG"] = _lang
app.jinja_env.globals["_js_i18n"] = _js_i18n
app.jinja_env.globals["dark_mode"] = dark_mode


def _clean(value):
    """NaN/Infinity 一律换成 null。

    Flask 会把 `float('inf')` 原样输出成裸 `Infinity`，那不是合法 JSON，浏览器
    `JSON.parse` 直接抛错，面板就报"服务返回了非 JSON 内容"。上游
    `inventory.TimedDrop.availability` 在掉宝没有剩余分钟时返回 `math.inf`
    （inventory.py:280-286），实测领取完一个掉宝后 `/api/campaigns` 正好踩中。
    """
    from math import isfinite
    if isinstance(value, float):
        return value if isfinite(value) else None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


@app.after_request
def _sanitize_json(response):
    if response.mimetype == "application/json" and not response.direct_passthrough:
        payload = response.get_json(silent=True)
        if payload is not None:
            cleaned = _clean(payload)
            if cleaned != payload:
                response.set_data(json.dumps(cleaned, ensure_ascii=False))
    return response


# ------------------------------------------------------------- 初始化

def init(loop, client):
    core["loop"] = loop
    core["client"] = client
    core["gui"] = client.gui


def _secret_key() -> bytes:
    """会话签名密钥：放在 .env 的 PANEL_SECRET，重启后登录态不丢。"""
    secret = os.environ.get("PANEL_SECRET")
    if secret:
        return secret.encode()
    text = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    lines = text.splitlines()
    for line in lines:
        if line.startswith("PANEL_SECRET="):
            value = line.split("=", 1)[1].strip()
            # 之前版本每次重启都会换成新密钥，导致面板登录态全丢；有值就沿用
            if value:
                os.environ["PANEL_SECRET"] = value
                return value.encode()
    value = secrets.token_hex(32)
    if any(line.startswith("PANEL_SECRET=") for line in lines):
        lines = [f"PANEL_SECRET={value}" if line.startswith("PANEL_SECRET=") else line
                 for line in lines]
    else:
        lines = lines + [f"PANEL_SECRET={value}"]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ["PANEL_SECRET"] = value
    return value.encode()


app.secret_key = _secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)


# ------------------------------------------------------------- 口令存储

def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 240_000).hex()


def panel_state() -> dict:
    if PANEL_FILE.exists():
        try:
            return json.loads(PANEL_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def needs_setup() -> bool:
    return "salt" not in panel_state()


# ------------------------------------------------------------- 开机自启
# 上游把“开机自启”做成注册表 / .desktop / LaunchAgent；这里是 Termux，
# 等价物是 /data/adb/service.d 里的 root 钩子。面板只能改“开关”，
# 钩子本身要 root 才能装（push.sh boot），装完写一个 marker 供这里判断。

BOOT_MARKER = ROOT / "termux" / "boot.installed"
BOOT_DISABLED = ROOT / "boot.disabled"


def autostart_available() -> bool:
    return BOOT_MARKER.exists()


def autostart_enabled() -> bool:
    return autostart_available() and not BOOT_DISABLED.exists()


def set_autostart(enabled: bool) -> None:
    if not autostart_available():
        raise RuntimeError("autostart hook is not installed")
    if enabled:
        BOOT_DISABLED.unlink(missing_ok=True)
    else:
        BOOT_DISABLED.write_text("disabled by panel\n", encoding="utf-8")


# ------------------------------------------------------------- 鉴权

def authed() -> bool:
    return bool(session.get("authed"))


def require_auth(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not authed():
            if request.path.startswith("/api/"):
                return jsonify({"error": "未登录", "code": "unauthorized"}), 401
            return redirect(url_for("login_page"))
        return fn(*args, **kwargs)
    return wrapper


@app.before_request
def _touch():
    core["last_seen"] = time.time()


# ------------------------------------------------------------- 页面

@app.route("/setup", methods=["GET", "POST"])
def setup_page():
    if not needs_setup():
        return redirect(url_for("login_page"))
    error = None
    if request.method == "POST":
        pw = (request.form.get("password") or "").strip()
        pw2 = (request.form.get("password2") or "").strip()
        if len(pw) < 8:
            error = ui("auth_err_short")
        elif pw != pw2:
            error = ui("auth_err_mismatch")
        else:
            salt = secrets.token_hex(16)
            PANEL_FILE.write_text(json.dumps(
                {"salt": salt, "hash": _hash(pw, salt), "created": time.time()},
                ensure_ascii=False), encoding="utf-8")
            session["authed"] = True
            session.permanent = True
            return redirect(url_for("dashboard"))
    return render_template("setup.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login_page():
    if needs_setup():
        return redirect(url_for("setup_page"))
    error = None
    if request.method == "POST":
        st = panel_state()
        if _hash((request.form.get("password") or ""), st["salt"]) == st["hash"]:
            session["authed"] = True
            session.permanent = True
            return redirect(url_for("dashboard"))
        error = ui("auth_err_wrong")
    return render_template("login.html", error=error)


@app.route("/panel/logout", methods=["POST"])
def panel_logout():
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/")
@require_auth
def dashboard():
    return render_template("index.html")


# ------------------------------------------------------------- 工具

def _client():
    return core.get("client")


def run_coro(coro, timeout: float = 25):
    """把协程丢回核心事件循环执行并等结果（Flask 在另一个线程）。"""
    loop = core.get("loop")
    if loop is None:
        raise RuntimeError("核心尚未启动")
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout)


def _g(obj, *names, default=None):
    """逐个属性名尝试，避免上游属性改名导致整个接口 500。"""
    for n in names:
        try:
            value = getattr(obj, n)
        except Exception:
            continue
        if value is not None:
            return value
    return default


def _finite(value, default=None):
    """把 math.inf / nan 变成 default：这类值不是合法 JSON，也不能直接给前端。"""
    from math import isfinite
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if isfinite(number) else default


def _when(value) -> str:
    """时间显示对齐上游：`x.astimezone().replace(microsecond=0, tzinfo=None)`。"""
    try:
        if value is None:
            return ""
        return str(value.astimezone().replace(microsecond=0, tzinfo=None))
    except Exception:
        return str(value or "")


def _drop_json(drop) -> dict:
    campaign = _g(drop, "campaign", default=None)
    benefits = []
    try:
        for benefit in (drop.benefits or []):
            benefits.append({
                "id": _g(benefit, "id", default=""),
                "name": _g(benefit, "name", default=""),
                "type": str(_g(_g(benefit, "type", default=None), "name", default="UNKNOWN")),
                "is_badge_or_emote": bool(_safe(benefit, "is_badge_or_emote")),
                "image_url": str(_g(benefit, "image_url", default="") or ""),
            })
    except Exception:
        pass
    try:
        rewards = drop.rewards_text()
    except Exception:
        rewards = str(_g(drop, "name", default="未知掉宝"))
    required = int(_g(drop, "required_minutes", default=0) or 0)
    current = int(_g(drop, "current_minutes", default=0) or 0)
    progress = float(_g(drop, "progress", default=0.0) or 0.0)
    try:
        # 上游 can_earn 是方法不是属性，直接 getattr 会拿到永远为真的 bound method
        can_earn = bool(drop.can_earn())
    except Exception:
        can_earn = False
    ends_at = _g(drop, "ends_at", default=None)
    starts_at = _g(drop, "starts_at", default=None)
    campaign_ends = _g(campaign, "ends_at", default=None)
    campaign_starts = _g(campaign, "starts_at", default=None)
    return {
        "id": _g(drop, "id", default=""),
        "name": str(_g(drop, "name", default="")),
        "rewards": rewards,
        "benefits": benefits,
        "current": current,
        "required": required,
        "remaining": int(_g(drop, "remaining_minutes", default=0) or 0),
        "total_required": int(_safe(drop, "total_required_minutes") or required),
        "progress": progress,
        "percentage": f"{progress:3.1%}",
        "is_claimed": bool(_safe(drop, "is_claimed")),
        "can_claim": bool(_safe(drop, "can_claim")),
        "can_earn": can_earn,
        "preconditions_met": bool(_safe(drop, "preconditions_met")),
        "availability": _finite(_safe(drop, "availability")),
        "starts": _when(starts_at),
        "ends": _when(ends_at),
        # 上游 update_progress() 的两种额外行：drop 窗口比活动窄时单独显示开始/结束
        "show_starts": bool(starts_at and campaign_starts and starts_at > campaign_starts
                            and _when_now_lt(starts_at)),
        "show_ends": bool(ends_at and campaign_ends and ends_at < campaign_ends),
        "time_left": str(_g(drop, "time_left_string", default="") or ""),
    }


def _when_now_lt(value) -> bool:
    try:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc) < value
    except Exception:
        return False


def _safe(obj, name):
    """属性可能是 property 且会抛错（比如 can_earn 需要 campaign 状态），拿不到就当 False。"""
    try:
        return getattr(obj, name)
    except Exception:
        return None


def _campaign_json(campaign, settings=None) -> dict:
    game = _g(campaign, "game", default=None)
    drops = []
    try:
        drops = [_drop_json(d) for d in (campaign.drops or [])]
    except Exception:
        pass
    try:
        acl = list(_g(campaign, "allowed_channels", default=[]) or [])
    except Exception:
        acl = []
    name = str(_g(game, "name", default=""))
    excluded = False
    in_priority = False
    priority_only = False
    if settings is not None:
        try:
            excluded = name in (getattr(settings, "exclude", set()) or set())
            in_priority = name in (getattr(settings, "priority", []) or [])
            from constants import PriorityMode
            priority_only = getattr(settings, "priority_mode", None) is PriorityMode.PRIORITY_ONLY
        except Exception:
            pass
    return {
        "id": _g(campaign, "id", default=""),
        "name": _g(campaign, "name", default="未命名活动"),
        "game": name,
        "game_id": str(_g(game, "id", default="")),
        "image_url": str(_g(campaign, "image_url", default="") or ""),
        "linked": bool(_g(campaign, "linked", default=False)),
        "link_url": str(_g(campaign, "link_url", default="") or ""),
        "active": bool(_safe(campaign, "active")),
        "upcoming": bool(_safe(campaign, "upcoming")),
        "expired": bool(_safe(campaign, "expired")),
        "eligible": bool(_safe(campaign, "eligible")),
        "finished": bool(_safe(campaign, "finished")),
        "has_badge_or_emote": bool(_safe(campaign, "has_badge_or_emote")),
        "excluded": excluded,
        "in_priority": in_priority,
        "priority_only": priority_only,
        "required_minutes": int(_safe(campaign, "required_minutes") or 0),
        "remaining_minutes": int(_safe(campaign, "remaining_minutes") or 0),
        "progress": float(_safe(campaign, "progress") or 0.0),
        "percentage": f"{float(_safe(campaign, 'progress') or 0.0):6.1%}",
        "claimed": int(_safe(campaign, "claimed_drops") or 0),
        "total_drops": int(_safe(campaign, "total_drops") or len(drops)),
        "availability": _finite(_safe(campaign, "availability")),
        "starts": _when(_g(campaign, "starts_at", default=None)),
        "ends": _when(_g(campaign, "ends_at", default=None)),
        "allowed_channels": [str(_g(ch, "name", "login", default="")) for ch in acl],
        "allowed_more": max(len(acl) - 4, 0) if len(acl) > 5 else 0,
        "drops": drops,
    }


def _channel_json(channel, watching_iid=None) -> dict:
    game = _g(channel, "game", default=None)
    online = bool(_safe(channel, "online"))
    pending = bool(_safe(channel, "pending_online"))
    viewers = _g(channel, "viewers", default=None)
    return {
        "iid": _g(channel, "iid", default=None),
        "id": str(_g(channel, "id", default="")),
        "name": _g(channel, "name", "login", default=""),
        "game": str(game) if game is not None and str(game) else "",
        "viewers": int(viewers) if viewers is not None else None,
        # 上游三态：在线 ✔ / 离线 ⏳(pending_online) / 离线 ❌
        "status": "online" if online else ("pending" if pending else "offline"),
        "online": online,
        "pending_online": pending,
        "drops_enabled": bool(_safe(channel, "drops_enabled")),
        "acl_based": bool(_safe(channel, "acl_based")),
        "watching": bool(watching_iid is not None and _g(channel, "iid") == watching_iid),
    }


# ------------------------------------------------------------- 只读 API

@app.route("/api/state")
@require_auth
def api_state():
    client = _client()
    if client is None:
        return jsonify({"error": "核心尚未启动"}), 503
    gui = core["gui"]
    auth = getattr(client, "_auth_state", None)
    user_id = getattr(auth, "user_id", 0) if auth else 0
    watching = gui.channels.watching
    drop = gui.progress.current_drop
    try:
        state_name = str(client._state.name)
    except Exception:
        state_name = "UNKNOWN"
    pending = 0
    for campaign in getattr(client, "inventory", []) or []:
        try:
            pending += sum(1 for d in campaign.drops if d.can_claim)
        except Exception:
            pass
    settings = getattr(client, "settings", None)
    try:
        history.record(client)
    except Exception:
        app.logger.warning("drop history record failed", exc_info=True)
    try:
        progress = gui.progress.snapshot()
    except Exception as exc:
        # 进度快照里任何一个属性取不到都不该把整个 /api/state 打挂（面板会显示"连接中断"）
        app.logger.warning(f"progress snapshot failed: {exc}")
        progress = {}
    return jsonify({
        "logged_in": bool(user_id),
        "user_id": str(user_id or ""),
        "state": state_name,
        "status_message": gui.status.message,
        "icon_state": gui.tray.icon_state,
        "games": sorted(getattr(g, "name", "") for g in gui.games if g),
        "campaign_count": len(getattr(client, "inventory", []) or []),
        "channel_count": len(gui.channels.all_channels),
        "pending_claims": pending,
        "load": gui.load_snapshot(),
        "login": gui.login.snapshot(),
        "websockets": gui.websockets.statuses,
        "progress": progress,
        "watching": {
            "iid": _g(watching, "iid", default=None),
            "name": _g(watching, "name", "login", default=""),
            "game": _g(_g(watching, "game", default=None), "name", default=""),
            "viewers": int(_g(watching, "viewers", default=0) or 0),
        } if watching else None,
        "current_drop": {
            "name": _g(drop, "name", default=""),
            "campaign": _g(_g(drop, "campaign", default=None), "name", default=""),
            "current": int(_g(drop, "current_minutes", default=0) or 0),
            "required": int(_g(drop, "total_required_minutes", "required_minutes", default=0) or 0),
            "time_left": str(_g(drop, "time_left_string", default="")),
        } if drop else None,
        "notifications": list(gui.tray.notifications)[:12],
        "version": _version(),
        "languages": _languages(),
        "priority_mode": str(_g(_g(settings, "priority_mode", default=None), "name",
                                default="ENDING_SOONEST")),
        "server_time": time.time(),
    })


def _version() -> str:
    try:
        from version import __version__
        return str(__version__)
    except Exception:
        return ""


def _languages() -> list:
    try:
        from translate import _
        return list(_.languages)
    except Exception:
        return []


@app.route("/api/history")
@require_auth
def api_history():
    client = _client()
    if client is None:
        return jsonify({"error": "核心尚未启动"}), 503
    try:
        history.record(client)
        data = history.snapshot(client)
    except Exception as exc:
        app.logger.warning("history snapshot failed: %s", exc)
        return jsonify({"error": str(exc)}), 500
    return jsonify(data)


@app.route("/api/campaigns")
@require_auth
def api_campaigns():
    client = _client()
    if client is None:
        return jsonify({"error": "核心尚未启动"}), 503
    settings = getattr(client, "settings", None)
    out = []
    for campaign in getattr(client, "inventory", []) or []:
        try:
            out.append(_campaign_json(campaign, settings))
        except Exception as exc:
            app.logger.warning(f"campaign render failed: {exc}")
    return jsonify({"campaigns": out, "count": len(out)})


@app.route("/api/channels")
@require_auth
def api_channels():
    client = _client()
    if client is None:
        return jsonify({"error": "核心尚未启动"}), 503
    gui = core["gui"]
    watching = gui.channels.watching
    out = []
    for channel in gui.channels.all_channels:
        try:
            out.append(_channel_json(channel, getattr(watching, "iid", None)))
        except Exception as exc:
            app.logger.warning(f"channel render failed: {exc}")
    # 上游 Treeview 按核心给的顺序插入，不按观众排序；这里只把离线的沉到底部方便看
    out.sort(key=lambda c: ({"online": 0, "pending": 1, "offline": 2}[c["status"]],
                            -(c["viewers"] or 0)))
    return jsonify({"channels": out[:300], "count": len(out)})


@app.route("/api/logs")
@require_auth
def api_logs():
    gui = core["gui"]
    if gui is None:
        return jsonify({"lines": [], "seq": 0})
    try:
        since = int(request.args.get("since", 0))
    except ValueError:
        since = 0
    lines = [row for row in gui.logs if row["seq"] > since]
    return jsonify({"lines": lines[-300:], "seq": gui.log_seq})


def _t(*path) -> str:
    """取上游自己的文案（lang/*.json），保证面板用词与桌面版一致。"""
    try:
        from translate import _
        return str(_(*path))
    except Exception:
        return path[-1]


def _bool(value) -> bool:
    return bool(value)


@app.route("/api/settings")
@require_auth
def api_settings():
    client = _client()
    if client is None:
        return jsonify({"error": "核心尚未启动"}), 503
    s = client.settings
    # 候选游戏名：与上游一致，只来自已加载的库存（twitch.py:786 set_games）
    games = set()
    for campaign in getattr(client, "inventory", []) or []:
        name = _g(_g(campaign, "game", default=None), "name", default=None)
        if name:
            games.add(name)
    games.update(list(getattr(s, "priority", []) or []))
    games.update(set(getattr(s, "exclude", set()) or set()))
    mode = getattr(s, "priority_mode", None)
    return jsonify({
        "priority_mode": getattr(mode, "name", "ENDING_SOONEST"),
        "priority_modes": {
            "PRIORITY_ONLY": _t("gui", "settings", "priority_modes", "priority_only"),
            "ENDING_SOONEST": _t("gui", "settings", "priority_modes", "ending_soonest"),
            "LOW_AVBL_FIRST": _t("gui", "settings", "priority_modes", "low_availability"),
        },
        "priority": list(getattr(s, "priority", []) or []),
        "exclude": sorted(getattr(s, "exclude", set()) or set()),
        "proxy": str(getattr(s, "proxy", "") or ""),
        "connection_quality": int(getattr(s, "connection_quality", 1)),
        "language": str(getattr(s, "language", "") or ""),
        "dark_mode": _bool(getattr(s, "dark_mode", False)),
        "autostart_tray": _bool(getattr(s, "autostart_tray", False)),
        "tray_notifications": _bool(getattr(s, "tray_notifications", True)),
        "unlinked_campaigns": _bool(getattr(s, "unlinked_campaigns", True)),
        "enable_badges_emotes": _bool(getattr(s, "enable_badges_emotes", False)),
        "available_drops_check": _bool(getattr(s, "available_drops_check", False)),
        "autostart": autostart_enabled(),
        "autostart_available": autostart_available(),
        "tray_available": False,
        "catalog_interval": int(catalog.configured_interval()),
        "catalog_interval_options": [300, 600, 900, 1800, 3600],
        "available_games": sorted(games),
        "labels": {
            "general": _t("gui", "settings", "general", "name"),
            "advanced": _t("gui", "settings", "advanced", "name"),
            "warning": _t("gui", "settings", "advanced", "warning"),
            "warning_text": _t("gui", "settings", "advanced", "warning_text"),
            "tray_notifications": _t("gui", "settings", "general", "tray_notifications"),
            "dark_mode": _t("gui", "settings", "general", "dark_mode"),
            "priority_mode": _t("gui", "settings", "general", "priority_mode"),
            "proxy": _t("gui", "settings", "general", "proxy"),
            "badges_emotes": _t("gui", "settings", "advanced", "enable_badges_emotes"),
            "drops_check": _t("gui", "settings", "advanced", "available_drops_check"),
            "priority": _t("gui", "settings", "priority"),
            "exclude": _t("gui", "settings", "exclude"),
            "game_name": _t("gui", "settings", "game_name"),
            "reload": _t("gui", "settings", "reload"),
            "reload_text": _t("gui", "settings", "reload_text"),
        },
    })


# ------------------------------------------------------------- 写操作 API

def _require_json(*fields):
    data = request.get_json(silent=True) or {}
    missing = [f for f in fields if f not in data]
    return (None, jsonify({"error": "缺少参数: " + ", ".join(missing)}), 400) if missing else (data, None, None)


@app.route("/api/settings", methods=["POST"])
@require_auth
def api_settings_save():
    client = _client()
    data, err, code = _require_json()
    if err:
        return err, code
    s = client.settings
    from constants import PriorityMode
    from yarl import URL
    language_changed = False
    if "priority_mode" in data:
        try:
            s.priority_mode = PriorityMode[data["priority_mode"]]
        except KeyError:
            return jsonify({"error": "未知的优先模式"}), 400
    if "connection_quality" in data:
        try:
            q = int(data["connection_quality"])
            s.connection_quality = min(max(q, 1), 6)  # 与 twitch.py:565 的钳制一致
        except (TypeError, ValueError):
            return jsonify({"error": "连接质量需为 1-6"}), 400
    if "proxy" in data:
        # 上游 proxy_validate：host 与 port 都有才写入，否则清空
        raw = str(data["proxy"] or "").strip()
        url = URL(raw)
        if raw and not (url.host is not None and url.port is not None):
            return jsonify({"error": "代理地址需要带主机与端口，例如 http://127.0.0.1:7890"}), 400
        s.proxy = url if raw else URL()
    if "language" in data:
        lang = str(data["language"] or "")
        try:
            from translate import _
            _.set_language(lang)  # 与上游“需要重启”一致：核心状态文案要重启后才是新语言
        except Exception:
            return jsonify({"error": "未知语言"}), 400
        s.language = lang
        language_changed = True
    if "catalog_interval" in data:
        try:
            catalog.set_interval(int(data["catalog_interval"]))
        except (TypeError, ValueError):
            return jsonify({"error": "刷新间隔需为整数秒"}), 400
    if "autostart" in data:
        try:
            set_autostart(bool(data["autostart"]))
        except RuntimeError:
            return jsonify({"error": "开机自启钩子尚未安装"}), 400
    for field in ("dark_mode", "autostart_tray", "tray_notifications", "unlinked_campaigns",
                  "enable_badges_emotes", "available_drops_check"):
        if field in data:
            setattr(s, field, bool(data[field]))
    s.alter()
    s.save()
    if language_changed:
        try:
            run_coro(_restart_core(), timeout=10)
        except Exception:
            app.logger.warning("language changed but core restart was not requested")
    return jsonify({"ok": True, "autostart": autostart_enabled()})


@app.route("/api/priority", methods=["POST"])
@require_auth
def api_priority():
    client = _client()
    data, err, code = _require_json("action")
    if err:
        return err, code
    s = client.settings
    action = data["action"]
    if action == "add":
        game = str(data.get("game", "")).strip()
        if not game:
            return jsonify({"error": "游戏名不能为空"}), 400
        if game not in s.priority:
            s.priority.append(game)
    elif action == "remove":
        game = str(data.get("game", ""))
        if game in s.priority:
            s.priority.remove(game)
    elif action == "move":
        try:
            idx = int(data["index"])
            new = idx - int(data.get("direction", 0))
            if 0 <= idx < len(s.priority) and 0 <= new < len(s.priority):
                item = s.priority.pop(idx)
                s.priority.insert(new, item)
        except (KeyError, ValueError, TypeError):
            return jsonify({"error": "索引或方向无效"}), 400
    elif action in ("top", "bottom"):
        # 上游 PaddedListbox 的 ⇈ / ⇊ 两个按钮
        try:
            idx = int(data["index"])
        except (KeyError, ValueError, TypeError):
            return jsonify({"error": "索引无效"}), 400
        if 0 <= idx < len(s.priority):
            item = s.priority.pop(idx)
            s.priority.insert(0 if action == "top" else len(s.priority), item)
    else:
        return jsonify({"error": "未知操作"}), 400
    s.alter()
    s.save()
    return jsonify({"ok": True, "priority": list(s.priority)})


@app.route("/api/exclude", methods=["POST"])
@require_auth
def api_exclude():
    client = _client()
    data, err, code = _require_json("action", "game")
    if err:
        return err, code
    s = client.settings
    game = str(data["game"]).strip()
    if not game:
        return jsonify({"error": "游戏名不能为空"}), 400
    if data["action"] == "add":
        s.exclude.add(game)
    elif data["action"] == "remove":
        s.exclude.discard(game)
    else:
        return jsonify({"error": "未知操作"}), 400
    s.alter()
    s.save()
    return jsonify({"ok": True, "exclude": sorted(s.exclude)})

async def _switch(iid: int):
    client = _client()
    channel = client.channels.get(iid)
    if channel is None:
        raise LookupError("找不到该频道")
    if not client.can_watch(channel):
        raise RuntimeError("当前无法观看该频道（离线或游戏不在目标内）")
    client.gui.channels.set_selection(channel)
    client.change_state(State.CHANNEL_SWITCH)


@app.route("/api/channel/switch", methods=["POST"])
@require_auth
def api_switch():
    data, err, code = _require_json("iid")
    if err:
        return err, code
    try:
        run_coro(_switch(int(data["iid"])))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True})


async def _claim(drop_id: str):
    client = _client()
    drop = client._drops.get(str(drop_id))
    if drop is None:
        raise LookupError("找不到该掉宝")
    if not drop.can_claim:
        raise RuntimeError("该掉宝当前不可领取")
    await drop.claim()


@app.route("/api/drop/claim", methods=["POST"])
@require_auth
def api_claim():
    data, err, code = _require_json("drop_id")
    if err:
        return err, code
    try:
        run_coro(_claim(str(data["drop_id"])), timeout=60)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True})


async def _reload():
    # 上游 SettingsPanel 的「刷新」按钮就是 INVENTORY_FETCH（gui.py:1867）；
    # State 枚举里根本没有 RELOAD，之前写错会让这个按钮 500。
    _client().change_state(State.INVENTORY_FETCH)


async def _restart_core():
    _client().change_state(State.RESTART)


@app.route("/api/reload", methods=["POST"])
@require_auth
def api_reload():
    try:
        run_coro(_reload())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True})


async def _invalidate_token():
    """对齐 gui.HelpTab._invalidate_token：真的向 Twitch 撤销令牌，再 RESTART。"""
    client = _client()
    auth = await client.get_auth()
    async with client.request(
        "POST",
        "https://id.twitch.tv/oauth2/revoke",
        data={"client_id": client._client_type.CLIENT_ID, "token": auth.access_token},
    ) as response:
        revoked = response.status == 200
        if not revoked:
            app.logger.error(f"Failed to invalidate the auth token: {response.status}")
    if revoked:
        auth.invalidate(delete_cookies=True)
    try:
        client.gui.login.clear(login=True, password=True, token=True)
    except Exception:
        pass
    client.change_state(State.RESTART)
    return revoked


@app.route("/api/twitch/logout", methods=["POST"])
@require_auth
def api_logout():
    try:
        revoked = run_coro(_invalidate_token(), timeout=40)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True, "revoked": bool(revoked)})


async def _relogin(clear_cookies: bool):
    client = _client()
    client._auth_state.invalidate(delete_cookies=clear_cookies)
    try:
        client.gui.login.clear(login=True, password=True, token=True)
    except Exception:
        pass
    client.change_state(State.RESTART)


@app.route("/api/twitch/relogin", methods=["POST"])
@require_auth
def api_relogin():
    """清掉本地会话并触发一次重新登录（走设备码）。"""
    try:
        run_coro(_relogin(True))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True})


@app.route("/api/twitch/confirm", methods=["POST"])
@require_auth
def api_login_confirm():
    """用户在浏览器里输完设备码后点这个按钮，放行核心里等待的登录流程。"""
    gui = core["gui"]
    if gui is None:
        return jsonify({"error": "核心尚未启动"}), 503
    gui.login.press()
    return jsonify({"ok": True})


@app.route("/api/twitch/password", methods=["POST"])
@require_auth
def api_login_password():
    from webgui import LoginData
    gui = core["gui"]
    data, err, code = _require_json("username", "password")
    if err:
        return err, code
    gui.login.submit_credentials(LoginData(
        username=str(data["username"]),
        password=str(data["password"]),
        token=str(data.get("token", "")),
    ))
    return jsonify({"ok": True})


# ------------------------------------------------------------- 启动入口

def serve(host: str, port: int):
    app.run(host=host, port=port, debug=False, threaded=True)
