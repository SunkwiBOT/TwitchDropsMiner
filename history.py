"""history.py - 本面板的 Twitch「已领取」掉宝记录。

数据源是 Twitch Inventory 的 `gameEventDrops`（就是网页“掉宝与奖励 → 已领取”
那张列表），而不是当前活动里 `isClaimed` 的库存项。每条记录按奖励物品保存：
名称、图片、领取时间、领取次数；活动过期、Twitch 六个月列表刷新都不会丢。

游戏归属：能从当前库存的活动里找到同一个 benefit id 时自动填游戏/活动；
找不到（活动已经过期、从目录消失）就放到「未归类」，不猜。
`history.json` 属于设备运行时状态，push.sh 会排除。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from constants import GQL_QUERIES, WORKING_DIR
from utils import timestamp

logger = logging.getLogger("TwitchDrops")

HISTORY_PATH = WORKING_DIR / "history.json"
# 可选的手动归属表：benefit id / 奖励名 -> 游戏名。活动过期、Twitch 流水 game=null
# 时用它把旧奖励归到对应游戏；设备侧文件，push 包排除。
GAME_MAP_PATH = WORKING_DIR / "history_game_map.json"
MAX_ITEMS = 2000

_lock = threading.Lock()
_items: dict[str, dict] | None = None
_dirty = False
_game_map: dict[str, str] = {}
_game_map_mtime = 0.0


def install_inventory(twitch_cls: type) -> None:
    """拦截核心的 Inventory GraphQL 响应，保存 gameEventDrops（已领取列表）。"""
    original = twitch_cls.gql_request
    if getattr(original, "_history_patched", False):
        return

    async def gql_request(self, ops):
        response = await original(self, ops)
        try:
            if ops is GQL_QUERIES["Inventory"]:
                inventory = response["data"]["currentUser"]["inventory"]
                self._game_event_drops = list(inventory.get("gameEventDrops") or [])
                self._game_event_drops_at = time.time()
        except Exception:
            pass
        return response

    gql_request._history_patched = True
    twitch_cls.gql_request = gql_request


def _load() -> None:
    global _items, _dirty
    if _items is not None:
        return
    _items = {}
    try:
        raw = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        items = raw.get("items")
        if isinstance(items, dict):
            for key, item in items.items():
                # 旧版本按库存 is_claimed 记录，语义不同；只保留 Twitch 已领取流水
                if isinstance(item, dict) and item.get("source") == "claimed":
                    _items[key] = item
            if len(_items) != len(items):
                _dirty = True
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.warning("Drop history: failed to load %s: %s", HISTORY_PATH, exc)


def _save_locked() -> None:
    global _dirty
    if not _dirty or _items is None:
        return
    try:
        tmp = HISTORY_PATH.with_name(HISTORY_PATH.name + ".new")
        tmp.write_text(
            json.dumps({"version": 2, "items": _items}, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(HISTORY_PATH)
        _dirty = False
    except Exception as exc:
        logger.warning("Drop history: failed to save: %s", exc)


def _load_game_map() -> dict[str, str]:
    global _game_map, _game_map_mtime
    try:
        mtime = GAME_MAP_PATH.stat().st_mtime
    except OSError:
        _game_map = {}
        _game_map_mtime = 0.0
        return _game_map
    if mtime != _game_map_mtime:
        try:
            raw = json.loads(GAME_MAP_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                _game_map = {str(k): str(v) for k, v in raw.items() if isinstance(v, str)}
            else:
                _game_map = {}
        except Exception as exc:
            logger.warning("Drop history: failed to load game map: %s", exc)
            _game_map = {}
        _game_map_mtime = mtime
    return _game_map


def _parse_time(raw: Any) -> float | None:
    if not raw:
        return None
    try:
        return timestamp(str(raw)).timestamp()
    except Exception:
        return None


def _enrichment(campaigns: list) -> dict[str, dict]:
    """benefit id -> 当前库存里的游戏/活动信息（活动还在时才能填）。"""
    enrichment: dict[str, dict] = {}
    for campaign in campaigns:
        try:
            game = str(campaign.game.name)
            campaign_id = str(getattr(campaign, "id", ""))
            campaign_name = str(campaign.name)
            campaign_image = str(getattr(campaign, "image_url", "") or "")
        except Exception:
            continue
        try:
            drops = list(campaign.drops)
        except Exception:
            continue
        for drop in drops:
            try:
                benefits = list(drop.benefits or [])
            except Exception:
                benefits = []
            drop_name = str(getattr(drop, "name", "") or "")
            for benefit in benefits:
                benefit_id = str(getattr(benefit, "id", "") or "")
                if not benefit_id:
                    continue
                enrichment[benefit_id] = {
                    "game": game,
                    "campaign_id": campaign_id,
                    "campaign_name": campaign_name,
                    "campaign_image": campaign_image,
                    "drop_name": drop_name,
                }
    return enrichment


def record(client: Any) -> bool:
    """把最新的 gameEventDrops 合并进历史；返回是否有变化。"""
    global _items, _dirty
    if client is None:
        return False
    _load()
    if _items is None:
        return False
    now = time.time()
    changed = False
    with _lock:
        try:
            campaigns = list(getattr(client, "inventory", None) or [])
        except Exception:
            campaigns = []
        enrichment = _enrichment(campaigns)
        game_map = _load_game_map()
        try:
            events = list(getattr(client, "_game_event_drops", None) or [])
        except Exception:
            events = []
        for entry in events:
            try:
                if not isinstance(entry, dict):
                    continue
                benefit_id = str(entry.get("id") or "")
                name = str(entry.get("name") or "")
                if not benefit_id and not name:
                    continue
                key = benefit_id or f"event:{name}"
                image = str(entry.get("imageURL") or "")
                claimed_at = _parse_time(entry.get("lastAwardedAt"))
                try:
                    count = max(1, int(entry.get("totalCount") or 1))
                except (TypeError, ValueError):
                    count = 1
                extra = enrichment.get(benefit_id) or {}
                mapped_game = game_map.get(benefit_id) or game_map.get(name) or ""
                extra_game = extra.get("game") or mapped_game
                item = _items.get(key)
                if item is None:
                    _items[key] = {
                        "key": key,
                        "benefit_id": benefit_id,
                        "name": name,
                        "image": image,
                        "game": extra_game,
                        "drop_name": extra.get("drop_name", ""),
                        "campaign_id": extra.get("campaign_id", ""),
                        "campaign_name": extra.get("campaign_name", ""),
                        "campaign_image": extra.get("campaign_image", ""),
                        "claimed_at": claimed_at,
                        "first_seen": now,
                        "count": count,
                        "source": "claimed",
                    }
                    changed = True
                    _dirty = True
                    continue
                updates = False
                if claimed_at and item.get("claimed_at") != claimed_at:
                    item["claimed_at"] = claimed_at
                    updates = True
                if count > int(item.get("count") or 1):
                    item["count"] = count
                    updates = True
                for field, value in (("name", name), ("image", image)):
                    if value and item.get(field) != value:
                        item[field] = value
                        updates = True
                if extra_game and item.get("game") != extra_game:
                    item["game"] = extra_game
                    updates = True
                for field in ("drop_name", "campaign_id", "campaign_name", "campaign_image"):
                    value = extra.get(field)
                    if value and item.get(field) != value:
                        item[field] = value
                        updates = True
                if updates:
                    changed = True
                    _dirty = True
            except Exception:
                continue
        if len(_items) > MAX_ITEMS:
            keep = sorted(
                _items.items(),
                key=lambda kv: kv[1].get("claimed_at") or kv[1].get("first_seen") or 0,
                reverse=True,
            )[:MAX_ITEMS]
            _items = dict(keep)
            changed = True
            _dirty = True
        _save_locked()
    return changed


def snapshot(client: Any) -> dict:
    """按游戏分组；优先列表排前，未归类紧随其后，其余按最近领取时间倒序。"""
    _load()
    with _lock:
        items = list((_items or {}).values())
    priority: list[str] = []
    try:
        priority = [str(name) for name in (client.settings.priority or [])]
    except Exception:
        priority = []
    priority_index = {name: index for index, name in enumerate(priority)}

    groups: dict[str, dict] = {}
    for index, name in enumerate(priority):
        groups[name] = {
            "game": name, "items": [], "image": "", "latest": 0,
            "count": 0, "in_priority": True, "priority_index": index,
        }
    for item in items:
        game = str(item.get("game") or "")
        group = groups.get(game)
        if group is None:
            group = groups[game] = {
                "game": game, "items": [], "image": "", "latest": 0,
                "count": 0, "in_priority": False, "priority_index": -1,
            }
        group["items"].append(item)
        stamp = item.get("claimed_at") or item.get("first_seen") or 0
        if stamp > group["latest"]:
            group["latest"] = stamp

    for group in groups.values():
        group["items"].sort(
            key=lambda it: it.get("claimed_at") or it.get("first_seen") or 0,
            reverse=True,
        )
        group["count"] = len(group["items"])
        group["unknown"] = not group["game"]
        for item in group["items"]:
            if item.get("campaign_image"):
                group["image"] = item["campaign_image"]
                break

    def sort_key(group: dict):
        if group["in_priority"]:
            return (0, group["priority_index"], -group["latest"])
        if group["unknown"]:
            return (1, 0, -group["latest"])
        return (2, 0, -group["latest"])

    ordered = sorted(groups.values(), key=sort_key)
    return {"total": len(items), "games": ordered, "priority": priority}
