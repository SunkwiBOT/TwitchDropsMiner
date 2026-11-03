"""claims.py - 阻止 Twitch 对同一个 drop 反复返回“已领取”导致日志/通知刷屏。

上游 `Twitch._run()` 在每次库存刷新后的 `GAMES_UPDATE` 里，会对所有
`can_claim` 的 drop 调 `drop.claim()`；而某些 drop 在 Twitch 的 Inventory
里 `self.isClaimed` 永远是 false、也不出现在 `gameEventDrops`，于是每次刷新
都会再 claim 一次，并打一条 `Claimed drop: ...`。

这里在进程内记住“成功 claim 过的 drop id”，持久化到 `claimed_drops.json`：
- `TimedDrop.claim`：已记住的 id 直接返回 True，不再请求/打日志；
- `TimedDrop.can_claim`：已记住的 id 返回 False，让 GAMES_UPDATE 循环跳过；
- `Twitch.process_drops`：收到的 drop-claim 事件如果对应已记住/已领取的
  drop，直接忽略，避免重复的 sleep/切台/日志。

不改上游 .py；`run.py` 里 `claims.install(Twitch, TimedDrop)` 即可。
`claimed_drops.json` 属设备运行时状态，push.sh 会排除。
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from constants import WORKING_DIR

logger = logging.getLogger("TwitchDrops")

CLAIMED_PATH = WORKING_DIR / "claimed_drops.json"
MAX_IDS = 5000

_lock = threading.Lock()
_ids: set[str] = set()
_loaded = False


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        raw = json.loads(CLAIMED_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except Exception as exc:
        logger.warning("Claimed-drop cache: failed to load: %s", exc)
        return
    ids = raw.get("ids") if isinstance(raw, dict) else raw
    if isinstance(ids, list):
        _ids.update(str(value) for value in ids if value)


def _save_locked() -> None:
    try:
        tmp = CLAIMED_PATH.with_name(CLAIMED_PATH.name + ".new")
        tmp.write_text(json.dumps({"ids": sorted(_ids)}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(CLAIMED_PATH)
    except Exception as exc:
        logger.warning("Claimed-drop cache: failed to save: %s", exc)


def _remember(drop_id: str) -> None:
    if not drop_id:
        return
    _load()
    with _lock:
        if drop_id in _ids:
            return
        if len(_ids) >= MAX_IDS:
            # 超过上限时清掉一半，保持文件有界；drop id 只是去重用，丢失最坏多打一条日志
            for old in sorted(_ids)[: MAX_IDS // 2]:
                _ids.discard(old)
        _ids.add(drop_id)
        _save_locked()


def install(twitch_cls: type, timed_drop_cls: type) -> None:
    _load()

    original_claim = timed_drop_cls.claim
    if not getattr(original_claim, "_claims_patched", False):
        async def claim(self):
            if str(getattr(self, "id", "")) in _ids:
                return True
            result = await original_claim(self)
            if result:
                _remember(str(getattr(self, "id", "")))
            return result

        claim._claims_patched = True
        timed_drop_cls.claim = claim

    original_can_claim = timed_drop_cls.can_claim.fget
    if not getattr(original_can_claim, "_claims_patched", False):
        def can_claim(self):
            if str(getattr(self, "id", "")) in _ids:
                return False
            return original_can_claim(self)

        can_claim._claims_patched = True
        timed_drop_cls.can_claim = property(can_claim)

    original_process_drops = twitch_cls.process_drops
    if not getattr(original_process_drops, "_claims_patched", False):
        async def process_drops(self, user_id, message):
            try:
                if isinstance(message, dict) and message.get("type") == "drop-claim":
                    data = message.get("data") or {}
                    drop_id = str(data.get("drop_id") or "")
                    drop = self._drops.get(drop_id)
                    if drop_id in _ids or (drop is not None and getattr(drop, "is_claimed", False)):
                        if drop_id:
                            _remember(drop_id)
                        return
            except Exception:
                pass
            return await original_process_drops(self, user_id, message)

        process_drops._claims_patched = True
        twitch_cls.process_drops = process_drops
