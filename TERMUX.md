# Valentin-Metz/TwitchDropsMiner + 中文网页面板（手机 Termux，:8081）

核心：<https://github.com/Valentin-Metz/TwitchDropsMiner>（上游 DevilXD 的 fork，commit `726099f`，`__version__ = 16.dev`）
它本身只有 tkinter 界面（Docker 版靠 Xvfb 顶着，登录还要 zendriver 拉真 Chrome），**在 Termux 上跑不起来**。所以这里给它加了一层界面：假 GUI 接管 + Flask 面板，上游 `.py` 零改动。

## 结构

| 路径 | 归属 |
| --- | --- |
| `twitch.py` `channel.py` `inventory.py` `settings.py` `constants.py` `translate.py` `utils.py` `websocket.py` `registry.py` `cache.py` `exceptions.py` `lang/` | 上游原样，**零改动** |
| `gui.py` | 上游文件，运行时被 `webgui` 顶掉（`sys.modules['gui'] = webgui`） |
| `webgui.py` | 假 GUI：捕获状态/频道/活动/进度/日志/托盘通知，并把登录表单桥到网页 |
| `run.py` | 入口：装假 GUI → 覆盖客户端类型 → 设语言 → 起核心 → 起 Flask 线程 → 优雅退出 |
| `catalog.py` | 公开掉宝目录回退：补 SMARTBOX 被 Twitch 屏蔽的“未参与活动”发现（见下节） |
| `history.py` | 已领取掉宝历史：扫描库存里的 is_claimed 掉落，落盘 `history.json`，按游戏分组（优先列表排前） |
| `server/api.py` | 面板后端：只读状态 + 写操作回投核心、pbkdf2 口令、会话、i18n |
| `server/templates/*.html`、`server/static/app.{css,js}` | 单页面板，**无任何 CDN/框架** |
| `termux/shims/` | tkinter 与 PIL 的空壳（`utils.py`/`cache.py` 顶层要 import 它们，headless 下永不真正调用） |
| `termux/*.sh` | 部署脚手架：打包/推送/安装/启停/状态/开机自启/验收 |

设备侧安装在 `/data/data/com.termux/files/home/twitchdrops/`，venv 在 `twitchdrops/env`，监听 `0.0.0.0:8081`。

## 控制方式（PC 的 Git Bash）

```bash
cd /e/Tool/QODER/tdm-vm/termux
bash push.sh            # 打包 + 推送 + 后台安装（改代码后跑）
bash push.sh follow     # 看安装日志
bash push.sh scripts    # 只更新代码/脚本，不动依赖
bash push.sh start|stop|restart|status
bash push.sh boot       # 重装 service.d 自启钩子
bash push.sh verifyboot # 冷停 → 跑钩子 → 断言端口回来（含 autostart 开关）
```

运行时文件（`panel.json`、`.env`、`settings.json`、`cookies.jar`、`boot.disabled`、`termux/boot.installed`）只存在于手机；`push.sh` 打包时全部排除，并在混入时 FATAL 拒推。

## 面板做了什么（与上游 GUI 逐项对齐）

页签、控件、文案都按 `gui.py` 与 `lang/*.json` 还原；固定文案走上游翻译（默认 简体中文），面板自己的提示只有中英两份。

- **主面板**：**掉宝活动进度置顶**（游戏封面 + 游戏/活动名、活动进度 + 已领/总数、剩余倒计时每秒本地推进；掉宝奖励图+名称、掉宝进度；**本次任务已领取的物品**也会列出图片和名称，含本次启动前在 Twitch 领过的；只有当前掉宝/已领取集合变化才重建图片节点，每秒只更新文字/方格）、状态（核心原文 + 运行状态/活动/频道/可领取 + 服务器时间）、库存载入方格（`gui.status.adding_campaigns` 的等价物）、Websocket 8 槽位（状态 + 订阅 N/50）、登录Twitch账户（状态/用户ID、设备码大字+链接+有效期、重新登录、账号密码兜底表单）、运行日志（等价 `ConsoleOutput`，增量拉取、自动滚底）、活动频道表（直播频道/状态三态/游戏/🎁/观众/📋 + 切换）、已领取通知（托盘通知的网页版）。
- **掉宝库存**：5 个筛选（默认 `not_linked` 绑 PRIORITY_ONLY，落 localStorage）+ 刷新；`_update_visibility` 逐条复刻（含 `required_minutes<=0` 的订阅活动永不显示）；活动卡：封面、名称、上线/即将/已结束、开始/结束时间、账户已关联（可点 `link_url`）、ACL 频道（>5 时 4 + 还有N个）、每条掉宝的 benefit 图/名、状态文案（已领取/可领取/`{minutes}分钟的{percent}`/`{minutes}分钟` + 开始/结束行）、方格、可领取时的「领取」。
- **设置**：语言（切换后重启核心 + 刷新页面）、开机自启（Termux 等价物 = service.d 钩子 + `boot.disabled` 开关）、开机自启并最小化（安卓无托盘，禁用并注明）、启用托盘通知（网页通知 + 面板收件箱）、夜间模式、允许挖掘未关联账户的活动、掉宝挖掘模式、代理（host+port 校验）、连接质量（仅 settings.json，上游 GUI 未暴露）；高级设置 2 项 + 警告；优先列表（手输/候选格子 + ⇈↑↓❌）；排除列表（手输/候选格子 + ❌）；刷新库存。所有改动立即写盘。
- **帮助**：About/仓库/本 fork/版本/捐赠、Twitch 库存与活动链接、工作原理、入门设置、退出登录（真调 `oauth2/revoke` + 清 cookies + RESTART）。
- **鉴权**：首次 `/setup` 设面板密码（pbkdf2-sha256 24 万次，`panel.json`）；会话 `PANEL_SECRET` 持久化在 `.env`（**已修：重启沿用旧密钥，登录态不丢**），7 天免登录；`/api/*` 未鉴权 401。

## 活动发现修复（2026-10-29 22:56）

**症状**：面板只能看到“已经参与并有进度”的活动；没参与的活动永远不出现，必须先去 Twitch 网页参加一次才被 `Inventory` 看到。

**根因**：Twitch 2026-09-18 给 `ViewerDropsDashboard` / `DropCampaignDetails` 加了完整性校验。WEB 客户端报 `IntegrityCheckFailed`；SMARTBOX/ANDROID_APP 不报错，静默返回 `dropCampaigns: null` / `dropCampaign: null`。`Inventory` 仍然正常，所以只有进行中的活动可见。上游 issue #1162 与 PR #1174/#1179/#1180 记录了这个变化；我们为了设备码登录必须用 SMARTBOX，所以必然踩到。

**修法**（不改上游 `.py`）：`catalog.py` 在 `run.py` 里对 `Twitch` 打两个补丁：
- `_fetch_available_campaigns` → 改读公开目录 `https://drops.sunkwi.com/api/twitch/drops`（groups[].rewards[] 与 `DropCampaignDetails` 同形）；
- `fetch_campaigns` → 直接返回目录条目，不再打被屏蔽的详情查询。
账号库存、进度、Websocket、看播、领取仍全部走 Twitch；`Inventory` 数据在合并时覆盖目录数据（含 `dropInstanceID`/`isClaimed`）。

**注意**：
- 公开目录免费档是 **每 IP 每 5 分钟 1 次**；`catalog.py` 有 310s 最小间隔 + 磁盘缓存 `catalog.cache.json`（超过 endAt 的会被 `_prune` 掉）。首次就 429 且无缓存时，5 分钟后会自动再触发一次 `INVENTORY_FETCH`。
- 目录不知道账号关联状态，目录-only 活动按 `isAccountConnected=True` 处理（与 PR #1180 一致），界面会显示“账户已关联”。若某个活动实际没关联游戏账号，挂它不会给奖励；用优先/排除列表或先点活动卡上的关联链接确认。
- 目录里同一时间可能有一百多个活动。`ENDING_SOONEST` 会优先追马上结束的（可能来不及），建议按需改成 `PRIORITY_ONLY` 并维护优先列表。

验证：修复后设备端 `campaign_count = 122`、`/api/campaigns` 420 KB 全带 drops/封面，核心对从未手动参加过的 `RavenQuest | Fortune's Frontier #7` 打出 `Drop progress ...: 2/120`。

## 历史掉宝页（2026-10-31）

新增第 5 个页签「历史」，`#history` 可直接深链。

**数据源是 Twitch Inventory 的 `gameEventDrops`，也就是网页“掉宝与奖励 → 已领取”那张列表**，不是当前活动里 `is_claimed` 的库存项（后者可能只是“库里已有/进行中”，不代表 Twitch 已记为领取）。

- `history.install_inventory(Twitch)` 包住 `gql_request`，每次核心拉 Inventory 时把 `gameEventDrops` 存到 `client._game_event_drops`；面板每次 `/api/state` 调 `history.record(client)` 合并进 `history.json`（按 benefit id 去重，保留 `lastAwardedAt`、图片、`totalCount`，最多 2000 条）。
- `history.json` 里 `source=claimed` 才是新语义；旧版本按库存扫描的记录在加载时直接丢弃（version 2）。
- 游戏归属：用当前库存活动里同 benefit id 的奖励反查游戏/活动；查不到（活动已过期、从公开目录消失）就查手动归属表，再查不到才放「未归类（旧活动）」，**不猜**。Twitch 这条已领取流水本身 `game` 为 null。
- 手动归属表 `$APP/history_game_map.json`（设备侧，push 包排除）：`{ "benefit_id 或奖励名": "游戏名" }`，`history.record` 每次按 mtime 热加载。本次已把截图里 5 条旧奖励归好：4 条 EA/ALGS（`"Respawning"` Holospray、APEX Pack ×2、Charge Rifle Skin）→ Apex Legends，`Random TF Archon Shard` → Warframe；Update 15.9 Mission #3 由库存活动反查到 World of Warships。同时写了奖励名条目（APEX Pack / Charge Rifle Skin / `"Respawning"` Holospray / Random TF Archon Shard），以后同名的新奖励也能自动归类。
- 分组顺序：优先列表里的游戏按列表顺序排最前，**没有记录也显示「暂无领取记录」**；然后是「未归类」；其余游戏按最近领取时间倒序。支持「只看优先列表游戏」开关（localStorage）。
- 每件物品显示奖励图、名称、所属活动（能查到才有）、领取时间、领取次数（`×N`）；组头显示封面、件数、最近时间、`优先 #n` 徽章。
- 领取时间直接来自 Twitch 的 `lastAwardedAt`，所以和网页“17小时前 / 昨天”是同一条流水；记录会一直保留，活动过期或 Twitch 六个月列表刷新都不会丢。
- `history.json` 是设备运行时状态，push 包已排除。

验收（真机 531px）：页签「历史」显示 6 件，和你截图里的已领取列表一一对应——Warframe #1 组 1 件（Random TF Archon Shard）、Apex Legends #2 组 4 件（`"Respawning"` Holospray、APEX Pack ×2、Charge Rifle Skin）、Minecraft #3 空组、World of Warships 组 1 件（Update 15.9 Mission #3）；没有「未归类」。图片、领取时间、优先徽章和筛选均正常，无横向溢出。

## 运行日志中文化（2026-11-03 22:40）

面板的「运行日志」之前混着核心英文日志（Checking login / Websocket connected / Claimed drop 等），而且 `LogHandler` 把时间+级别再套了一层，显示成双时间戳。现在：
- `webgui.LogHandler` 只上传 `record.levelname` + `record.getMessage()`，不再拼时间/级别；前端统一显示 `时间 + 中文级别 + 消息`。
- 新增 `logi18n.py`：仅简体中文界面生效，按整行精确匹配 + 正则模板翻译登录、WebSocket、频道状态、掉宝进度/领取、活动目录、历史/去重缓存、常见错误；频道/游戏/活动/掉宝名和错误详情原样保留，未匹配的英文行原样显示，后续可继续补。
- `log.txt` 仍是英文原文（FileHandler 独立），方便排查；面板只翻译显示层。
- 级别徽章：信息 / 警告 / 错误 / 调试 / 调用；浅色模式有独立颜色。

## About 与中文翻译修正（2026-11-03 22:13）

- About 页改正为：应用作者 **bplhkx**（链接到 github.com/bplhkx）/ 上游仓库 DevilXD/TwitchDropsMiner / 基线 fork Valentin-Metz/TwitchDropsMiner / 本仓库 bplhkx/TwitchDropsMiner / 核心版本 v16.dev / 面板 Termux Web Panel；捐赠行已按用户要求删除。
- 上游 `lang/简体中文.json` 缺少 `gui.settings.general.unlinked_campaigns`，导致设置页显示英文；已补「允许挖掘未关联账户的活动」。该翻译随 `_.set_language` 在启动时加载，改完需重启（本次已重启）。

## 活动刷新频率与历史堆叠（2026-11-03）

- 设置页新增「掉宝活动刷新频率（分钟）」，写入设备侧 `$APP/catalog.config.json`：`{"interval_seconds": 600}`，范围 300–86400 秒（UI 5–1440 分钟）。`catalog.configured_interval()` 按文件 mtime 热加载；公开目录 API 的请求下限仍是 310 秒。核心每 5 分钟探测一次，所以实际生效最多再晚 5 分钟。
- 历史页对同一游戏下同名的多条奖励做堆叠：默认只显示一张 `名称 ×N` 卡片，点击展开每次领取的时间/活动/缩略图；不影响后端 `history.json` 的逐条记录。
- 面板总标题改为 **Twitch 挖宝鼠**（顶部、浏览器标签、登录/设置页标题）。

## 重复领取日志修复（2026-11-03 21:52）

**症状**：运行日志反复出现同一批 `Claimed drop: ...`（ARKNIGHTS Sanctuary of Ink 5 条、ARC Raiders Frozen Trail 2 条），每次库存刷新来一轮；旧 log.txt 累计 1600+ 条。

**根因**：上游 `GAMES_UPDATE` 每次库存刷新都会对 `can_claim` 的 drop 调 `claim()`；这几个 drop 在 Twitch Inventory 里一直报 `can_claim`/未领取，但 claim 又返回成功（`ELIGIBLE_FOR_ALL` / `DROP_INSTANCE_ALREADY_CLAIMED`），且不出现在 `gameEventDrops`。公开目录让库存刷新变成约 10 分钟一次，于是同一批 claim 日志反复刷。

**修法**（不改上游 `.py`）：新增 `claims.py`，`run.py` 里 `claims.install(Twitch, TimedDrop)`：
- `TimedDrop.claim`：成功 claim 过的 drop id 直接返回 True，不再请求/打日志；
- `TimedDrop.can_claim`：已记住的 id 返回 False，GAMES_UPDATE 循环直接跳过；
- `Twitch.process_drops`：drop-claim 事件对应已记住/已领取的 drop 时忽略，避免重复 sleep/切台；
- 记录持久化在 `$APP/claimed_drops.json`（设备侧，push 排除），重启不丢；本次已把当前 12 个已领取 drop 预置进去。
- 前端 `/api/logs` 轮询加了 busy 锁，避免慢请求重叠导致同批日志追加两次。

验收：重启后 + 手动 `POST /api/reload` 强制库存刷新，`Claimed drop` 新增 0 条，`claimed_drops.json` 保持 12 个 id；核心正常回到 CHANNEL_SWITCH/IDLE。注意：这几个 drop 仍不会出现在 Twitch「已领取」列表里，这是 Twitch 侧的数据不一致；本修复只阻止重复请求和日志刷屏。

## 必须记住的坑

1. **客户端类型**：fork 默认 `ClientType.ANDROID_APP`（`twitch.py:531`），Twitch 不给它下发设备码 → `/oauth2/device` 响应无 `device_code` → `_oauth_login` 抛 `KeyError` 崩溃循环。`run.py` 运行时覆盖成 `ClientType.SMARTBOX`。Token 与 client_id 绑定，`_validate` 发现不匹配会清空 cookies.jar 重登。
2. **登录入口**：`_validate` 只调 `_browser_login`（zendriver 真 Chrome，安卓没有）→ `_AuthState._browser_login = _AuthState._oauth_login`，网页「登录」页签才能出验证码。
3. **`ask_enter_code` 绝不能阻塞**：`_oauth_login` 在它**返回之后**才轮询 `/oauth2/token`；假 GUI 里 `await` 按钮事件会让登录链永远卡住。现在只发布验证码即返回，按钮只是提前刷新。
4. **设置必须真的落盘**：上游 `gui.save()` → `settings.save()`；假 GUI 早期是 `pass`，面板改的设置重启即丢。现在 `webgui.GUIManager.save` 会写 `settings.json`，写操作 API 也即时 `save()`。
5. **`client.save` 不能省**：`Twitch.save()` 会先 `gui.save()`；`run.py` 退出前 `client.save(force=True)`。
6. **`can_earn` 是方法不是属性**：`api._drop_json` 里必须 `drop.can_earn()`，否则 `getattr` 拿到永远为真的 bound method，所有掉宝都会显示成"进行中"。
7. **候选游戏只有库存那一份**：上游没有可掉宝游戏目录，`twitch.py:786` 只做 `set_games(campaign.game for campaign in inventory)`；别自创热门榜（之前试过、被否）。
8. **运行时状态绝不能进包**：`panel.json`、`.env`、`settings.json`、`cookies.jar`、`boot.disabled`、`termux/boot.installed`；`push.sh` 有两层防护（exclude + FATAL）。
9. **tkinter/PIL**：`utils.py`/`cache.py` 顶层 import 它们；Termux CPython 没有，靠 `PYTHONPATH=.../shims` 注入空壳；真调用会抛错。
10. **pip 只装 aiohttp + Flask**：`pystray`/`PyGObject`/`Pillow`/`zendriver` 都不进 venv（`gui` 被顶掉、PIL 走 shim）。`argon2-cffi-bindings>=25` 的 CMake 黑洞与本部署无关（面板口令用 pbkdf2）。

## 设备侧运维

```text
$APP=/data/data/com.termux/files/home/twitchdrops
$APP/log.txt                 核心日志（run.py 的 logging FileHandler）
$APP/logs/server.log         supervisor + run.py 的控制台输出
$APP/settings.json           面板/核心设置
$APP/cookies.jar             Twitch 会话（aiohttp CookieJar，Netscape 文本）
$APP/panel.json              面板口令（pbkdf2）
$APP/.env                    TDM_WEB_PORT / PANEL_SECRET
$APP/boot.disabled           存在 = 面板里关了开机自启
/data/adb/service.d/twitchdrops-termux.sh    root 开机钩子（可删）
/data/adb/service.d/twitchdrops-termux.log   钩子日志
```

## 已知限制

- 安卓没有系统托盘：`autostart_tray`（开机自启并最小化）只保留设置字段，不生效；托盘通知映射为网页通知。
- 面板是 Flask 开发服务器（多线程），局域网自用可以，别直接暴露公网。
- 账号侧 `currentUser.dropCampaigns = 0` 时面板如实显示空库存（与桌面版一致），不是面板故障。
- 上游更新时核对 `twitch.py`/`channel.py`/`inventory.py` 的 `self.gui.*` 调用点与 `gui.py` 的控件文案；`webgui.py` 的签名与它们对齐。
