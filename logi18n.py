"""logi18n.py - 把核心/面板的英文运行日志翻译成中文（仅面板显示，log.txt 保持原文）。

只在当前界面语言是简体中文时生效。按“整行精确匹配 → 正则模板”翻译；动态的
频道名、游戏名、活动名、掉宝名、错误详情原样保留。未匹配的英文行原样返回，
方便以后继续补规则。
"""
from __future__ import annotations

import re

EXACT: dict[str, str] = {
    "Checking login": "检查登录状态...",
    "Login flow started": "开始登录流程",
    "Restoring session from cookie": "从 cookies 恢复会话",
    "Restored session is invalid": "恢复的会话已失效",
    "Cookie client ID mismatch": "Cookie 的 client ID 不匹配",
    "Access token granted": "已获得访问令牌",
    "1000: CAPTCHA is required": "1000：需要完成 CAPTCHA",
    "3001: Login failed due to incorrect username or password": "3001：用户名或密码错误",
    "3012/23: Login failed due to incorrect 2FA code": "3012/23：双重验证码错误",
    "3011/22: 2FA token required": "3011/22：需要双重验证码",
    "Campaign catalog: invalid payload": "活动目录：返回数据无效",
    "Campaign catalog: retried discovery after rate limit": "活动目录：限流后已重试获取",
    "Maintenance task requests channels cleanup": "维护任务请求清理频道",
    "Maintenance task requests a reload": "维护任务请求重新载入库存",
    "Traceback (most recent call last):": "异常堆栈（最近调用在后）：",
    "The above exception was the direct cause of the following exception:":
        "上述异常是以下异常的直接原因：",
    "Future exception was never retrieved": "后台异常未被取回",
}

PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # 登录
    (re.compile(r"Login successful, user ID: (\d+)"), "登录成功，用户 ID：{}"),
    (re.compile(r"Login error code: (\d+)"), "登录错误码：{}"),
    # WebSocket
    (re.compile(r"Websocket\[(\d+)\] connecting\.\.\."), "WebSocket[{}] 正在连接..."),
    (re.compile(r"Websocket\[(\d+)\] connected\."), "WebSocket[{}] 已连接"),
    (re.compile(r"Websocket\[(\d+)\] stopped\."), "WebSocket[{}] 已停止"),
    (re.compile(r"Websocket\[(\d+)\] reconnecting\.\.\."), "WebSocket[{}] 正在重连..."),
    (re.compile(r"Websocket\[(\d+)\] didn't receive a PONG, reconnecting\.\.\."),
     "WebSocket[{}] 未收到 PONG，正在重连..."),
    (re.compile(r"Websocket\[(\d+)\] requested reconnect\."), "WebSocket[{}] 请求重连"),
    (re.compile(r"Websocket\[(\d+)\] closed unexpectedly: (.*)"), "WebSocket[{}] 意外关闭：{}"),
    (re.compile(r"Websocket\[(\d+)\] connection problem \(sleep: (\d+)s\)"),
     "WebSocket[{}] 连接异常（{} 秒后重试）"),
    (re.compile(r"Websocket\[(\d+)\] exiting backoff connect loop because session is closed \(RuntimeError\)"),
     "WebSocket[{}] 会话已关闭，退出重连循环"),
    (re.compile(r"Websocket\[(\d+)\] error: Unknown message: (.*)"),
     "WebSocket[{}] 错误：未知消息：{}"),
    (re.compile(r"Websocket\[(\d+)\] error: (.*)"), "WebSocket[{}] 错误：{}"),
    (re.compile(r"Websocket\[(\d+)\] received unknown payload: (.*)"),
     "WebSocket[{}] 收到未知数据：{}"),
    (re.compile(r"Exception in Websocket\[(\d+)\]"), "WebSocket[{}] 发生异常"),
    # 频道 / 直播状态
    (re.compile(r"(.+) goes ONLINE"), "{} 已开播"),
    (re.compile(r"(.+) goes OFFLINE"), "{} 已下播"),
    (re.compile(r"(.+) stays OFFLINE"), "{} 仍离线"),
    (re.compile(r"(.+) status has been updated, switching\.\.\. \(🎁: (.*) -> (.*)\)"),
     "{} 状态已更新，正在切换...（🎁：{} → {}）"),
    (re.compile(r"(.+) status has been updated \(🎁: (.*) -> (.*)\)"),
     "{} 状态已更新（🎁：{} → {}）"),
    (re.compile(r"Stream state change for a non-existing channel: (\d+)"),
     "收到不存在频道的直播状态变更：{}"),
    (re.compile(r"Broadcast settings update for a non-existing channel: (\d+)"),
     "收到不存在频道的直播信息更新：{}"),
    (re.compile(r"Unknown stream state: (.*)"), "未知的直播状态：{}"),
    (re.compile(r"Stream URL get error: (.*)"), "获取直播流地址失败：{}"),
    (re.compile(r"Send watch error: (.*)"), "发送观看请求失败：{}"),
    (re.compile(r"Watch requested failed for channel: (.*)"), "观看请求失败：{}"),
    # 掉宝进度 / 领取
    (re.compile(r"Drop progress: (.*)"), "掉宝进度：{}"),
    (re.compile(r"Drop progress from GQL: (.*)"), "掉宝进度（GQL）：{}"),
    (re.compile(r"Drop progress from active search: (.*)"), "掉宝进度（估算）：{}"),
    (re.compile(r"Drop update from websocket: (.*)"), "掉宝进度更新：{}"),
    (re.compile(r"Claimed drop: (.*)"), "已领取掉宝：{}"),
    (re.compile(r"Drop claim has potentially failed! Drop ID: (.*)"),
     "领取可能失败！掉宝 ID：{}"),
    (re.compile(r"Received a drop claim ID for a non-existing drop: (.*)"),
     "收到不存在掉宝的领取 ID：{}"),
    (re.compile(r"Drop claim ID: (.*)"), "领取 ID：{}"),
    (re.compile(r"At least one of the drops in campaign \"(.*)\((.*)\)\" has reached the maximum extra minutes limit!"),
     "活动「{}（{}）」中至少有一个掉宝达到额外分钟上限！"),
    # 活动目录 / 历史 / 去重
    (re.compile(r"Campaign change detected \((\d+) -> (\d+)\); requesting an inventory refresh"),
     "活动列表变化（{} → {}），请求刷新库存"),
    (re.compile(r"Campaign catalog: loaded (\d+) cached campaigns from disk"),
     "活动目录：从磁盘缓存载入 {} 个活动"),
    (re.compile(r"Campaign catalog: (\d+) active/upcoming campaigns"),
     "活动目录：{} 个进行中/即将开始的活动"),
    (re.compile(r"Campaign catalog: rate limited \(.*\)"),
     "活动目录：请求被限流，继续使用缓存"),
    (re.compile(r"Campaign catalog: using cached data \((\d+) campaigns, age (.*)s\)"),
     "活动目录：使用缓存（{} 个活动，缓存 {} 秒前）"),
    (re.compile(r"Campaign catalog: HTTP (.*)"), "活动目录：HTTP {}"),
    (re.compile(r"Campaign catalog: request failed: (.*)"), "活动目录：请求失败：{}"),
    (re.compile(r"Campaign catalog: invalid config: (.*)"), "活动目录：配置无效：{}"),
    (re.compile(r"Campaign catalog: failed to write cache: (.*)"), "活动目录：写入缓存失败：{}"),
    (re.compile(r"Campaign probe found no changes \((\d+) campaigns\)"),
     "活动探测无变化（{} 个活动）"),
    (re.compile(r"Drop history: failed to load (.*): (.*)"), "掉宝历史：加载 {} 失败：{}"),
    (re.compile(r"Drop history: failed to save: (.*)"), "掉宝历史：保存失败：{}"),
    (re.compile(r"Drop history: failed to load game map: (.*)"),
     "掉宝历史：加载游戏归属表失败：{}"),
    (re.compile(r"Claimed-drop cache: failed to load: (.*)"), "已领取缓存：加载失败：{}"),
    (re.compile(r"Claimed-drop cache: failed to save: (.*)"), "已领取缓存：保存失败：{}"),
    # 其他错误
    (re.compile(r"Failed to invalidate the auth token: (.*)"), "撤销授权令牌失败：{}"),
    (re.compile(r"Retrying a (.*) for (.*)"), "正在重试 {}：{}"),
    (re.compile(r"Exception in (.*) task"), "任务 {} 发生异常"),
]


def _is_simplified_chinese() -> bool:
    try:
        from translate import _
        return str(_.current).startswith("简体")
    except Exception:
        return False


def translate_line(line: str) -> str:
    if not line:
        return line
    stripped = line.strip()
    if stripped in EXACT:
        return EXACT[stripped]
    for pattern, replacement in PATTERNS:
        match = pattern.fullmatch(stripped)
        if match:
            try:
                return replacement.format(*match.groups())
            except Exception:
                return line
    # 部分动态文本里带 <Unknown>
    return line.replace("<Unknown>", "<未知>")


def translate(message: str) -> str:
    """只在简体中文界面翻译；保留换行和未匹配内容。"""
    if not _is_simplified_chinese():
        return message
    text = str(message)
    return "\n".join(translate_line(line) for line in text.splitlines())
