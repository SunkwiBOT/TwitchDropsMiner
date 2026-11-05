"""catalog.py - 用公开的 Twitch Drops 目录补上 SMARTBOX 客户端的活动发现缺口。

背景（Twitch 2026-09-18 起，见 DevilXD/TwitchDropsMiner #1162/#1174/#1180）：
`ViewerDropsDashboard` 与 `DropCampaignDetails` 加了完整性校验。WEB 客户端直接报
`IntegrityCheckFailed`；ANDROID_APP / SMARTBOX 客户端更糟——不报错，静默返回
`dropCampaigns: null` / `dropCampaign: null`。于是核心只能看到 `Inventory` 里的
“已经在进行中的活动”，任何尚未参与的活动永远发现不了。

本模块只负责“公开活动元数据”的发现，账号库存、进度、Websocket、看播与领取仍然全部
走 Twitch 自己的接口。数据源是 PR #1180 同款的公开目录（drops.sunkwi.com），
免费额度是每 IP 每 5 分钟 1 次，所以这里做了磁盘缓存 + 最小请求间隔；失败时退回缓存，
不会把已发现的活动清空。

在 run.py 里 `catalog.install(Twitch)` 即可，不改上游 .py。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from constants import ClientType, WORKING_DIR
from utils import timestamp

logger = logging.getLogger("TwitchDrops")

CATALOG_URL = "https://drops.sunkwi.com/api/twitch/drops"
CACHE_PATH = WORKING_DIR / "catalog.cache.json"
CONFIG_PATH = WORKING_DIR / "catalog.config.json"
# 免费档：每 IP 每 5 分钟 1 次；留一点余量。用户可在设置页把刷新间隔调大。
API_MIN_INTERVAL = 310.0
DEFAULT_INTERVAL = 600.0
CONFIG_MIN_INTERVAL = 300
CONFIG_MAX_INTERVAL = 86400
APPLICABLE_STATUSES = ("ACTIVE", "UPCOMING")

_cache: dict[str, Any] = {"payload": None, "fetched_at": 0.0, "campaigns": {}}
_last_attempt = 0.0
_lock: asyncio.Lock | None = None
_retry_clients: set[int] = set()
_config_interval: float | None = None
_config_mtime = 0.0


def configured_interval() -> float:
    """面板设置的刷新间隔（秒）；每 5 分钟最低，默认 10 分钟。"""
    global _config_interval, _config_mtime
    try:
        mtime = CONFIG_PATH.stat().st_mtime
    except OSError:
        _config_interval = None
        _config_mtime = 0.0
        return DEFAULT_INTERVAL
    if mtime != _config_mtime:
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            value = int(raw.get("interval_seconds", DEFAULT_INTERVAL))
        except Exception as exc:
            logger.warning("Campaign catalog: invalid config: %s", exc)
            value = int(DEFAULT_INTERVAL)
        value = min(max(value, CONFIG_MIN_INTERVAL), CONFIG_MAX_INTERVAL)
        _config_interval = float(value)
        _config_mtime = mtime
    return _config_interval or DEFAULT_INTERVAL


def set_interval(seconds: int) -> int:
    """写入刷新间隔并返回钳制后的秒数；文件更新后下一次 get_campaigns 生效。"""
    value = min(max(int(seconds), CONFIG_MIN_INTERVAL), CONFIG_MAX_INTERVAL)
    tmp = CONFIG_PATH.with_name(CONFIG_PATH.name + ".new")
    tmp.write_text(json.dumps({"interval_seconds": value}), encoding="utf-8")
    tmp.replace(CONFIG_PATH)
    global _config_mtime
    try:
        _config_mtime = CONFIG_PATH.stat().st_mtime
    except OSError:
        _config_mtime = 0.0
    return value


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def _load_disk_cache() -> None:
    if _cache["payload"] is not None:
        return
    try:
        raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    payload = raw.get("payload")
    if isinstance(payload, dict) and isinstance(payload.get("games"), list):
        _cache["payload"] = payload
        _cache["fetched_at"] = float(raw.get("fetched_at") or 0)
        _cache["campaigns"] = _transform(payload)
        logger.info(
            "Campaign catalog: loaded %d cached campaigns from disk", len(_cache["campaigns"])
        )


def _save_disk_cache(payload: dict, fetched_at: float) -> None:
    try:
        tmp = CACHE_PATH.with_name(CACHE_PATH.name + ".new")
        tmp.write_text(
            json.dumps({"fetched_at": fetched_at, "payload": payload}, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(CACHE_PATH)
    except Exception as exc:
        logger.warning("Campaign catalog: failed to write cache: %s", exc)


def _prune(campaigns: dict[str, dict]) -> dict[str, dict]:
    """缓存里的活动可能在这期间结束；每次返回前按 endAt 再筛一遍。"""
    now = datetime.now(timezone.utc)
    alive: dict[str, dict] = {}
    for cid, campaign in campaigns.items():
        try:
            if timestamp(str(campaign["endAt"])) <= now:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        alive[cid] = campaign
    return alive


def _transform(payload: dict) -> dict[str, dict]:
    """把公开目录的 groups[].rewards[] 转成 DropCampaignDetails 的形状。"""
    groups = payload.get("games")
    if not isinstance(groups, list):
        return {}
    now = datetime.now(timezone.utc)
    campaigns: dict[str, dict] = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        box_art = group.get("gameBoxArtURL") or ""
        rewards = group.get("rewards")
        if not isinstance(rewards, list):
            continue
        for raw in rewards:
            if not isinstance(raw, dict):
                continue
            campaign_id = raw.get("id")
            if not isinstance(campaign_id, str) or not campaign_id:
                continue
            if raw.get("status") not in APPLICABLE_STATUSES:
                continue
            try:
                starts_at = timestamp(str(raw["startAt"]))
                ends_at = timestamp(str(raw["endAt"]))
            except (KeyError, TypeError, ValueError):
                continue
            # 目录可能比 Twitch 慢一拍：过了 endAt 的绝不再当成 ACTIVE
            if ends_at <= now:
                continue
            game = raw.get("game")
            if not isinstance(game, dict) or not game.get("id"):
                continue
            campaign = deepcopy(raw)
            game = dict(game)
            game.setdefault("boxArtURL", box_art)
            if not game.get("displayName") and game.get("name"):
                game["displayName"] = game["name"]
            if not game.get("name") and game.get("displayName"):
                game["name"] = game["displayName"]
            campaign["game"] = game

            # 公开目录不知道账号是否已关联；和 PR #1180 一样按“可参与”处理，
            # 真正的关联校验由 Twitch 服务端决定。库存数据会在合并时覆盖这里。
            self_data = campaign.get("self")
            if not isinstance(self_data, dict):
                self_data = {}
            self_data.setdefault("isAccountConnected", True)
            campaign["self"] = self_data

            allow = campaign.get("allow")
            if not isinstance(allow, dict):
                allow = {"isEnabled": False, "channels": None}
            allow.setdefault("channels", None)
            campaign["allow"] = allow

            drops = campaign.get("timeBasedDrops")
            if not isinstance(drops, list):
                drops = []
            clean_drops: list[dict] = []
            for drop in drops:
                if not isinstance(drop, dict):
                    continue
                try:
                    timestamp(str(drop["startAt"]))
                    timestamp(str(drop["endAt"]))
                except (KeyError, TypeError, ValueError):
                    continue
                drop = dict(drop)
                edges = drop.get("benefitEdges")
                edges = [e for e in edges if isinstance(e, dict) and isinstance(e.get("benefit"), dict)] \
                    if isinstance(edges, list) else []
                for edge in edges:
                    benefit = edge["benefit"]
                    if not isinstance(benefit.get("imageAssetURL"), str):
                        benefit["imageAssetURL"] = ""
                    if not isinstance(benefit.get("distributionType"), str):
                        benefit["distributionType"] = "UNKNOWN"
                drop["benefitEdges"] = edges
                pre = drop.get("preconditionDrops")
                drop["preconditionDrops"] = pre if isinstance(pre, list) else []
                if not isinstance(drop.get("requiredMinutesWatched"), (int, float)):
                    drop["requiredMinutesWatched"] = 0
                clean_drops.append(drop)
            campaign["timeBasedDrops"] = clean_drops
            campaign.setdefault("accountLinkURL", "")
            campaign.setdefault("imageURL", "")
            campaigns[campaign_id] = campaign
    return campaigns


async def _fetch_payload(settings: Any) -> dict | None:
    request_kwargs: dict[str, Any] = {"headers": {"Accept": "application/json"}}
    proxy = getattr(settings, "proxy", None)
    if proxy:
        request_kwargs["proxy"] = str(proxy)
    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(
            timeout=timeout,
            cookie_jar=aiohttp.DummyCookieJar(),
            headers={"User-Agent": "TwitchDropsMiner campaign fallback"},
        ) as session:
            async with session.get(CATALOG_URL, **request_kwargs) as response:
                if response.status == 429:
                    logger.warning(
                        "Campaign catalog: rate limited (1 request / 5 min per IP); "
                        "keeping cached campaigns"
                    )
                    return None
                if response.status != 200:
                    logger.warning("Campaign catalog: HTTP %s", response.status)
                    return None
                payload = await response.json()
    except Exception as exc:
        logger.warning("Campaign catalog: request failed: %s", exc)
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("games"), list):
        logger.warning("Campaign catalog: invalid payload")
        return None
    return payload


async def get_campaigns(settings: Any) -> dict[str, dict]:
    """返回 {campaign_id: 详情}；优先实时目录，失败/限流时退回缓存。"""
    global _last_attempt
    _load_disk_cache()
    async with _get_lock():
        now = time.time()
        interval = configured_interval()
        fresh = _cache["payload"] is not None and (now - _cache["fetched_at"]) < interval
        if fresh:
            return _prune(_cache["campaigns"])
        if now - _last_attempt < API_MIN_INTERVAL:
            # 上一次请求刚失败（或刚成功但还没到 5 分钟），别再去撞限流
            return _prune(_cache["campaigns"])
        _last_attempt = now
        payload = await _fetch_payload(settings)
        if payload is not None:
            campaigns = _transform(payload)
            _cache["payload"] = payload
            _cache["fetched_at"] = now
            _cache["campaigns"] = campaigns
            _save_disk_cache(payload, now)
            logger.info("Campaign catalog: %d active/upcoming campaigns", len(campaigns))
            return _prune(campaigns)
        if _cache["campaigns"]:
            age = int(now - _cache["fetched_at"]) if _cache["fetched_at"] else -1
            logger.warning(
                "Campaign catalog: using cached data (%d campaigns, age %ss)",
                len(_cache["campaigns"]), age,
            )
            return _prune(_cache["campaigns"])
        return {}


async def _retry_discovery(client: Any) -> None:
    """目录为空（首次就 429）时，5 分钟后主动再来一次库存刷新，而不是等一小时维护。"""
    key = id(client)
    if key in _retry_clients:
        return
    _retry_clients.add(key)
    try:
        await asyncio.sleep(API_MIN_INTERVAL)
        from constants import State
        client.change_state(State.INVENTORY_FETCH)
        logger.info("Campaign catalog: retried discovery after rate limit")
    except Exception:
        pass
    finally:
        _retry_clients.discard(key)


def install(twitch_cls: type) -> None:
    """把 SMARTBOX 的“发现活动”与“活动详情”两条路径换成公开目录。"""
    original_fetch_available = twitch_cls._fetch_available_campaigns
    original_fetch_campaigns = twitch_cls.fetch_campaigns

    def _is_smartbox(client) -> bool:
        try:
            return client._client_type is ClientType.SMARTBOX
        except Exception:
            return False

    async def _fetch_available_campaigns(self):
        if not _is_smartbox(self):
            return await original_fetch_available(self)
        campaigns = await get_campaigns(self.settings)
        if not campaigns:
            asyncio.create_task(_retry_discovery(self))
        return {
            cid: campaign
            for cid, campaign in campaigns.items()
            if campaign.get("status") in APPLICABLE_STATUSES
        }

    async def fetch_campaigns(self, campaigns_chunk):
        # 目录条目本身就是 DropCampaignDetails 的形状，无需再打 Twitch 的详情查询
        if _is_smartbox(self):
            return dict(campaigns_chunk)
        return await original_fetch_campaigns(self, campaigns_chunk)

    twitch_cls._fetch_available_campaigns = _fetch_available_campaigns
    twitch_cls.fetch_campaigns = fetch_campaigns