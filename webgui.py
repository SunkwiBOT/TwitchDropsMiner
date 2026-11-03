"""webgui.py - 把上游的 tkinter 界面调用点换成可被 web 读取的数据容器。

上游（DevilXD/TwitchDropsMiner 及本 fork）只通过 `twitch.gui` 这一个对象与界面交互，
`twitch.py` / `channel.py` / `inventory.py` 里一共只有 32 处调用，签名见 gui.py 同名方法。
这里用同样签名的假实现接管它们：核心逻辑一行不改，界面数据全部留在内存里给 web 层读。

用法（见 run.py）：在导入 `twitch` 之前 `sys.modules['gui'] = webgui`。
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

# ---------------------------------------------------------------- 基础件


@dataclass
class LoginData:
    username: str = ""
    password: str = ""
    token: str = ""
    token_kind: Optional[str] = None


class _Button:
    def config(self, **kwargs):
        pass

    def __getattr__(self, name):
        return lambda *a, **k: None


class Help:
    """gui.help：只被用来 disable 一个按钮。"""

    def __init__(self):
        self._invalidate_button = _Button()


class StatusBar:
    def __init__(self):
        self.message: str = ""
        self.updated_at: float = time.time()

    def update(self, text: str):
        self.message = str(text) if text else ""
        self.updated_at = time.time()

    def clear(self):
        self.message = ""


class Tray:
    def __init__(self):
        self.icon_state = "idle"
        self.notifications: deque = deque(maxlen=50)

    def change_icon(self, state: str):
        self.icon_state = state

    def notify(self, message: str, title: str = ""):
        self.notifications.appendleft({"at": time.time(), "title": title, "message": message})

    def restore(self):
        pass

    def minimize(self):
        pass

    def stop(self):
        pass


class Websockets:
    def __init__(self):
        self.statuses: dict[int, dict] = {}

    def update(self, idx: int, status=None, topics=None):
        cur = self.statuses.setdefault(idx, {"status": None, "topics": 0})
        if status is not None:
            cur["status"] = status
        if topics is not None:
            cur["topics"] = topics

    def remove(self, idx: int):
        self.statuses.pop(idx, None)


class Progress:
    """对应上游 gui.CampaignProgress：秒级倒计时 + 掉宝/活动双进度。

    `minute_almost_done()` 不是装饰性的：核心的 `_watch_loop` 用它判断
    "Twitch 是不是停止上报进度了"，从而走 GQL 兜底（twitch.py:1041）。
    上游语义是 `timer_task is None or seconds <= 10`，所以这里必须真的把
    倒计时跑起来，恒返 False 会让进度卡住时失去自愈。签名与语义对齐 gui.py:758。
    """

    ALMOST_DONE_SECONDS = 10

    def __init__(self):
        self.current_drop = None
        self.countdown = False
        self.subone = False
        self._seconds: int = 0
        self._timer_task: Optional[asyncio.Task] = None

    # --- 时间计算（照搬 gui.CampaignProgress._divmod/_update_time） ---
    def _divmod(self, minutes: int) -> tuple:
        if self._seconds < 60 and minutes > 0:
            minutes -= 1
        return divmod(minutes, 60)

    def remaining_strings(self) -> dict:
        drop = self.current_drop
        if drop is not None:
            drop_minutes = drop.remaining_minutes
            campaign_minutes = drop.campaign.remaining_minutes
        else:
            drop_minutes = 0
            campaign_minutes = 0
        dseconds = self._seconds % 60
        hours, minutes = self._divmod(drop_minutes)
        drop_remaining = f"{hours:>2}:{minutes:02}:{dseconds:02}"
        hours, minutes = self._divmod(campaign_minutes)
        return {
            "drop": drop_remaining,
            "campaign": f"{hours:>2}:{minutes:02}:{dseconds:02}",
            "seconds": self._seconds,
        }

    async def _timer_loop(self):
        self._seconds = 60
        while self._seconds > 0:
            await asyncio.sleep(1)
            self._seconds -= 1
        self._timer_task = None

    def start_timer(self):
        if self._timer_task is None:
            if self.current_drop is None or self.current_drop.remaining_minutes <= 0:
                self._seconds = 60
            else:
                try:
                    self._timer_task = asyncio.create_task(self._timer_loop())
                except RuntimeError:
                    # 没有运行中的事件循环（离线自检时会出现）
                    self._seconds = 60

    def stop_timer(self):
        if self._timer_task is not None:
            self._timer_task.cancel()
            self._timer_task = None
        self._timer_task = None

    def minute_almost_done(self) -> bool:
        return self._timer_task is None or self._seconds <= self.ALMOST_DONE_SECONDS

    def display(self, drop, *, countdown: bool = True, subone: bool = False):
        self.current_drop = drop
        self.countdown = countdown
        self.subone = subone
        self.stop_timer()
        if drop is None:
            self._seconds = 0
            return
        if countdown:
            self.start_timer()
        elif subone:
            self._seconds = 0
        else:
            self._seconds = 60

    @staticmethod
    def _benefit_json(benefit) -> dict:
        try:
            return {
                "name": str(getattr(benefit, "name", "") or ""),
                "image": str(getattr(benefit, "image_url", "") or ""),
                "type": getattr(getattr(benefit, "type", None), "name", ""),
            }
        except Exception:
            return {"name": "", "image": "", "type": ""}

    @classmethod
    def _claimed_items(cls, campaign) -> list[dict]:
        """当前活动里所有已领取的掉落物品（含本次启动前领取的）。"""
        items: list[dict] = []
        try:
            for timed_drop in campaign.drops:
                if not getattr(timed_drop, "is_claimed", False):
                    continue
                drop_name = str(getattr(timed_drop, "name", "") or "")
                try:
                    benefits = [cls._benefit_json(b) for b in (timed_drop.benefits or [])]
                except Exception:
                    benefits = []
                if not benefits:
                    benefits = [{"name": drop_name, "image": "", "type": ""}]
                for benefit in benefits:
                    benefit["drop"] = drop_name
                items.extend(benefits)
        except Exception:
            return items
        return items[:20]

    def snapshot(self) -> dict:
        """给面板的『掉宝活动进度』区块用，字段与上游 Label 一一对应。

        额外带上封面/奖励图与当前活动已领取的物品：主面板要显示游戏封面、
        掉落物品图片，以及本次任务已经领到的东西。
        """
        drop = self.current_drop
        if drop is None:
            return {
                "drop": {
                    "rewards": "...", "progress": 0.0, "percentage": "-%",
                    "benefits": [],
                },
                "campaign": {
                    "name": "...", "game": "...", "progress": 0.0,
                    "percentage": "-%", "claimed": 0, "total": 0, "image": "",
                    "claimed_items": [],
                },
                "remaining": self.remaining_strings(),
            }
        campaign = drop.campaign
        try:
            benefits = [self._benefit_json(b) for b in (drop.benefits or [])]
        except Exception:
            benefits = []
        try:
            claimed_items = self._claimed_items(campaign)
        except Exception:
            claimed_items = []
        return {
            "drop": {
                "id": getattr(drop, "id", ""),
                "rewards": drop.rewards_text(),
                "progress": float(drop.progress),
                "percentage": f"{drop.progress:6.1%}",
                "current": int(drop.current_minutes),
                "required": int(drop.total_required_minutes),
                "time_left": str(getattr(drop, "time_left_string", "") or ""),
                "benefits": benefits,
            },
            "campaign": {
                "id": getattr(campaign, "id", ""),
                "name": campaign.name,
                "game": getattr(campaign.game, "name", ""),
                "progress": float(campaign.progress),
                "percentage": f"{campaign.progress:6.1%} ({campaign.claimed_drops}/{campaign.total_drops})",
                "claimed": int(campaign.claimed_drops),
                "total": int(campaign.total_drops),
                "image": str(getattr(campaign, "image_url", "") or ""),
                "claimed_items": claimed_items,
            },
            "remaining": self.remaining_strings(),
            "almost_done": self.minute_almost_done(),
        }


class Channels:
    def __init__(self):
        self._items: dict[Any, Any] = {}
        self.watching = None
        self._selection = None

    def display(self, channel, *, add: bool = False):
        self._items[channel.iid] = channel

    def remove(self, channel):
        self._items.pop(channel.iid, None)
        if self.watching is not None and self.watching.iid == channel.iid:
            self.watching = None

    def clear(self):
        self._items.clear()
        self.watching = None

    def shrink(self):
        pass

    def set_watching(self, channel):
        self.watching = channel

    def clear_watching(self):
        self.watching = None

    def get_selection(self):
        return self._selection

    def set_selection(self, channel):
        self._selection = channel

    def clear_selection(self):
        self._selection = None

    @property
    def all_channels(self):
        return list(self._items.values())


class Inventory:
    """活动/掉宝的捕获点。add_campaign 是上游逐条刷新进度的地方。

    上游 `twitch.py:1687` 在执行 `gui.inv.clear()` 之后才开始逐条 `add_campaign`，
    而 `self.inventory` 在那之前已经装好，所以第一次 add 时能拿到准确的总数，
    等价于状态栏那句 `正在将掉宝活动列表添加至库存...(i/n)` 的分母。
    """

    def __init__(self, gui: "GUIManager"):
        self._gui = gui
        self.campaigns: dict[str, Any] = {}

    async def add_campaign(self, campaign) -> None:
        gui = self._gui
        if gui.load_total <= 0:
            client = gui.client
            total = len(getattr(client, "inventory", []) or []) if client is not None else 0
            gui.begin_campaign_load(total)
        self.campaigns[campaign.id] = campaign
        gui.note_campaign_added()

    def update_drop(self, drop) -> None:
        pass

    def clear(self) -> None:
        self.campaigns.clear()
        self._gui.reset_campaign_load()


class LoginForm:
    """网页版登录表单：设备码与账号密码两条路都桥到浏览器。"""

    def __init__(self, gui: "GUIManager"):
        self._gui = gui
        self.status = ""
        self.user_id = None
        self.kind = "idle"          # idle | code | password
        self.user_code = ""
        self.verification_uri = ""
        self.code_expires_at = 0.0
        self.code_started_at = 0.0
        self._press = asyncio.Event()
        self._credentials = asyncio.Queue()

    # --- 上游调用点 -------------------------------------------------
    def update(self, status: str, user_id):
        self.status = status or ""
        self.user_id = user_id

    def clear(self, login: bool = False, password: bool = False, token: bool = False):
        if login and password:
            self.kind = "idle"
            self.user_code = ""
            self.verification_uri = ""

    async def wait_for_login_press(self) -> None:
        self._press.clear()
        await self._press.wait()

    async def ask_enter_code(self, page_url, user_code) -> None:
        """只负责把验证码公布出去，不阻塞。

        核心在这之后自己会按 interval 轮询 /oauth2/token 直到授权成功，
        所以这里不能等按钮 —— 等按钮会让整条登录链卡死（实测：用户在
        Twitch 完成授权，面板却永远显示未登录）。press 事件保留，只作为
        「立即刷新」的信号。
        """
        self.kind = "code"
        self.user_code = user_code
        self.verification_uri = str(page_url)
        self.code_started_at = time.time()
        self.code_expires_at = self.code_started_at + 1800
        self._press.clear()

    async def ask_login(self) -> LoginData:
        self.kind = "password"
        data = await self._credentials.get()
        self.kind = "idle"
        return data

    # --- 网页侧调用 -------------------------------------------------
    def press(self):
        self._press.set()

    def submit_credentials(self, data: LoginData):
        self._credentials.put_nowait(data)

    def snapshot(self) -> dict:
        return {
            "kind": self.kind,
            "status": self.status,
            "user_id": self.user_id,
            "user_code": self.user_code,
            "verification_uri": self.verification_uri,
            "started_at": self.code_started_at,
            "expires_at": self.code_expires_at,
        }


# ---------------------------------------------------------------- 主体


class LogHandler(logging.Handler):
    """等价上游 gui._TKOutputHandler（gui.py:74）：把核心日志灌进界面的『运行日志』。

    少了这一步，网页抽屉里只会看到我们自己 print 的两行，核心的
    `Drop progress: ...`、`Changing state to ...` 等全部看不见。
    """

    def __init__(self, manager: "GUIManager"):
        super().__init__()
        self._manager = manager

    def emit(self, record):
        try:
            self._manager.print(self.format(record))
        except Exception:
            pass


class GUIManager:
    """签名对齐 gui.GUIManager，行为全部走内存。"""

    def __init__(self, client=None):
        self.client = client
        self.close_requested = False
        self._closed = asyncio.Event()
        self.logs: deque = deque(maxlen=600)
        self.log_seq = 0
        self.games: set = set()
        # 活动载入进度
        self.load_total = 0
        self.load_done = 0
        self.load_started_at = 0.0
        self.load_finished_at = 0.0

        self.status = StatusBar()
        self.tray = Tray()
        self.websockets = Websockets()
        self.progress = Progress()
        self.channels = Channels()
        self.inv = Inventory(self)
        self.login = LoginForm(self)
        self.help = Help()

        # 注册日志转发（对齐 gui.py:2315-2320）
        self._handler = LogHandler(self)
        self._handler.setFormatter(logging.Formatter(
            "%(asctime)s: %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        logging.getLogger("TwitchDrops").addHandler(self._handler)

    # --- 生命周期 ---------------------------------------------------
    def start(self):
        pass

    def stop(self):
        pass

    def close(self, *args):
        self.close_requested = True
        logging.getLogger("TwitchDrops").removeHandler(self._handler)
        self._closed.set()
        return 0

    def close_window(self):
        pass

    def prevent_close(self):
        pass

    def grab_attention(self, *, sound: bool = True):
        pass

    async def wait_until_closed(self):
        await self._closed.wait()

    async def coro_unless_closed(self, coro):
        if self.close_requested:
            # 与上游一致：关掉时不再等待
            task = asyncio.ensure_future(coro)
            task.cancel()
            return None
        return await coro

    # --- 数据入口 ---------------------------------------------------
    def print(self, message: str):
        self.log_seq += 1
        self.logs.append({"seq": self.log_seq, "at": time.time(), "text": str(message)})

    def save(self, *, force: bool = False) -> None:
        """对齐 gui.GUIManager.save：上游在状态切换/退出时把 settings.json 落盘。

        少了这一步，面板里改的设置只在内存里活着，重启后全部丢失。
        """
        client = self.client
        if client is None:
            return
        try:
            client.settings.save(force=force)
        except Exception:
            logging.getLogger("TwitchDrops").exception("保存 settings.json 失败")

    def set_games(self, games: Iterable) -> None:
        self.games = set(games)

    def display_drop(self, drop, *, countdown: bool = True, subone: bool = False):
        self.progress.display(drop, countdown=countdown, subone=subone)

    def clear_drop(self):
        self.progress.display(None)

    # --- 载入进度 ---------------------------------------------------
    def begin_campaign_load(self, total: int):
        self.load_total = int(total)
        self.load_done = 0
        self.load_started_at = time.time()
        self.load_finished_at = 0.0

    def reset_campaign_load(self):
        self.load_total = 0
        self.load_done = 0
        self.load_started_at = 0.0
        self.load_finished_at = 0.0

    def note_campaign_added(self):
        self.load_done += 1
        if self.load_total and self.load_done >= self.load_total:
            self.load_finished_at = time.time()

    def load_snapshot(self) -> dict:
        return {
            "total": self.load_total,
            "done": self.load_done,
            "started_at": self.load_started_at,
            "finished_at": self.load_finished_at,
        }


# gui.py 里被 TYPE_CHECKING 引用的名字，这里补齐，避免任何 `from gui import X` 出错
WebsocketStatus = Websockets
InventoryOverview = Inventory
ChannelList = Channels
CampaignProgress = Progress
StatusBar = StatusBar  # noqa: F811
TrayIcon = Tray


def install():
    """把本模块冒充成 gui 包，必须在 import twitch 之前调用。"""
    import sys
    sys.modules["gui"] = sys.modules[__name__]
