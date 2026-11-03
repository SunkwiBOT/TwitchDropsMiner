"""run.py - 无 tkinter 的核心 + 网页控制面板入口。

和上游 main.py 的差别只有四处，全部是运行环境适配，不改上游业务代码：
1. 用 `webgui` 顶掉 `gui` 模块（`sys.modules['gui'] = webgui`），核心一行不改；
2. 登录走设备码（`_oauth_login`），不用 fork 里依赖真 Chrome 的 zendriver；
3. 客户端类型覆盖为 SMARTBOX（Twitch 只给它下发设备码，见 TERMUX.md）；
4. 起一个 Flask 线程提供网页面板。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import threading
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import webgui  # noqa: E402
webgui.install()  # 必须在 import twitch 之前

from constants import FILE_FORMATTER, LOCK_PATH, LOG_PATH  # noqa: E402
from settings import Settings  # noqa: E402
from translate import _  # noqa: E402
from twitch import Twitch, _AuthState  # noqa: E402
from utils import lock_file  # noqa: E402

# fork 的 _validate 只会调 _browser_login（需要真 Chrome），这里指到设备码流程
_AuthState._browser_login = _AuthState._oauth_login

# Twitch 自 2026-09-18 起对 SMARTBOX 的 ViewerDropsDashboard / DropCampaignDetails
# 静默返回 null；用公开目录补上“发现未参与活动”的能力（详见 catalog.py）
import catalog  # noqa: E402
catalog.install(Twitch)

# 历史掉宝：从 Inventory 的 gameEventDrops（Twitch「已领取」列表）落盘
import history  # noqa: E402
history.install_inventory(Twitch)

from server import api  # noqa: E402


class ParsedArgs(argparse.Namespace):
    """对齐 main.py 的 ParsedArgs，供 Settings 透传读取。"""

    _verbose: int = 0
    _debug_ws: bool = False
    _debug_gql: bool = False
    log: bool = False
    tray: bool = False
    dump: bool = False


def setup_logging() -> int:
    level = int(os.environ.get("TDM_LOG_LEVEL", "20"))  # INFO
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_PATH, mode="a", encoding="utf-8"),
    ]
    logging.basicConfig(level=level, format=FILE_FORMATTER._fmt,
                        datefmt=FILE_FORMATTER.datefmt, style="{",
                        handlers=handlers, force=True)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.INFO)
    return level


async def main() -> int:
    log = logging.getLogger("run")
    args = ParsedArgs()
    settings = Settings(args)
    if not (ROOT / "settings.json").exists():
        # 首次运行：写一份默认设置，避免面板读到空文件
        settings.alter()
        settings.save(force=True)

    # 与上游 main.py 一致：语言要在任何界面文案生成之前设好
    try:
        _.set_language(settings.language)
    except ValueError:
        settings.language = "English"
        _.set_language("English")

    client = Twitch(settings)
    # 上游/fork 默认 ClientType.ANDROID_APP，但 Twitch 只对该 fork 用到的
    # SMARTBOX 客户端下发设备码（ANDROID_APP 下 /oauth2/device 返回里没有
    # device_code，实测会 KeyError 崩溃循环）。运行时覆盖，不改上游文件。
    from constants import ClientType
    client._client_type = ClientType.SMARTBOX

    api.init(asyncio.get_running_loop(), client)

    host = os.environ.get("TDM_WEB_HOST", "0.0.0.0")
    port = int(os.environ.get("TDM_WEB_PORT", "8081"))
    log.info(f"网页面板: http://{host}:{port}")
    client.gui.print(f"网页面板: http://{host}:{port}")

    try:
        await client.run()
    except Exception:
        log.error(f"核心异常退出:\n{traceback.format_exc()}")
        client.gui.print("核心异常退出，见日志")
        return 1
    finally:
        try:
            client.save(force=True)
        except Exception:
            pass
        await client.shutdown()
    return 0


def run() -> None:
    setup_logging()
    log = logging.getLogger("run")
    ok, handle = lock_file(LOCK_PATH)
    if not ok:
        log.error("已有一个实例在运行（lock.file 被占用），退出")
        sys.exit(3)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    web = threading.Thread(target=api.serve,
                           args=(os.environ.get("TDM_WEB_HOST", "0.0.0.0"),
                                 int(os.environ.get("TDM_WEB_PORT", "8081"))),
                           name="web", daemon=True)
    web.start()

    async def _runner() -> int:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: _close_soon())
            except (NotImplementedError, RuntimeError):
                pass
        return await main()

    def _close_soon() -> None:
        client = api.core.get("client")
        if client is not None:
            # gui.close() 只置“用户要求关闭”的旗标；核心若正停在 IDLE 等状态事件，
            # 还得 close() 把状态推到 EXIT 才能唤醒主循环。
            try:
                client.gui.close()
            except Exception:
                pass
            try:
                client.close()
            except Exception:
                pass

    try:
        code = loop.run_until_complete(_runner())
    except KeyboardInterrupt:
        code = 0
    finally:
        try:
            handle.close()
        except Exception:
            pass
        try:
            LOCK_PATH.unlink()
        except OSError:
            pass
    sys.exit(code)


if __name__ == "__main__":
    run()
