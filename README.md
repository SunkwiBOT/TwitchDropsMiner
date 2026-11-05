# Twitch 挖宝鼠 — TwitchDropsMiner Termux 网页面板分支

在 Android / Termux 里**原生**运行 [TwitchDropsMiner](https://github.com/DevilXD/TwitchDropsMiner)，并把原本依赖 tkinter 的桌面界面换成一套可用的中文 Web 面板。不需要 X11 / Xvfb，不需要真 Chrome，也不是 proot/chroot。

> A headless, Termux-native fork of TwitchDropsMiner with a full Chinese web panel.

- 上游核心：[DevilXD/TwitchDropsMiner](https://github.com/DevilXD/TwitchDropsMiner)（MIT）
- 本分支基线：[Valentin-Metz/TwitchDropsMiner](https://github.com/Valentin-Metz/TwitchDropsMiner)（commit `726099f`，`__version__ = 16.dev`）
- 本仓库：[bplhkx/TwitchDropsMiner](https://github.com/bplhkx/TwitchDropsMiner)

上游 `.py` 业务代码保持原样；所有改动都是新增文件，加上 `run.py` 里的运行时补丁。

---

## 功能

- **纯 Termux 进程**：`run.py` 直接在 Termux 的 Python 里跑核心，Flask 面板在另一个线程；没有桌面、Docker 或虚拟显示依赖。
- **设备码登录**：强制使用 `ClientType.SMARTBOX`，登录走 Twitch 设备码，不依赖 zendriver/Chrome。登录会话保存在 `cookies.jar`。
- **全功能中文面板**：主面板 / 掉宝库存 / 历史 / 设置 / 帮助五个页签，文案来自上游 `lang/*.json`，支持 20+ 种语言切换；页面总标题为 **Twitch 挖宝鼠**。
- **运行日志中文化**：面板日志按“时间 + 级别 + 中文消息”展示，核心的登录/WebSocket/频道/掉宝进度/领取/活动目录等英文日志会在显示层翻译；`log.txt` 保留英文原文便于排查。
- **可调的活动刷新频率**：设置页可按分钟自定义公开目录/新活动的发现间隔（5–1440 分钟，受公开目录免费档限制）。
- **主面板掉宝进度置顶**：游戏封面、当前掉宝奖励图、活动/掉宝进度方格、秒级倒计时，以及**本次已领取的物品**。
- **掉宝库存**：上游同款 5 个筛选、活动卡、ACL 频道、奖励图与进度，筛选状态存浏览器 localStorage。
- **历史掉宝**：记录 Twitch「已领取」流水（`gameEventDrops`），活动过期、重启、Twitch 六个月列表刷新都不丢；按优先列表分组，支持手动游戏归属；同名奖励（如多个 APEX Pack）默认堆叠，点开看每次领取详情。
- **完整设置面**：语言、开机自启、托盘通知（映射为浏览器通知）、夜间模式、未关联活动、挖掘模式、代理、连接质量、优先/排除列表、刷新库存。
- **Termux 运维脚本**：一条命令完成打包/推送/安装/启停/状态/开机自启/冷启验证。
- **开机自启**：Magisk `/data/adb/service.d` 钩子，面板里可开关；`push.sh verifyboot` 做冷停恢复验收。
- **移动优先**：531px 宽度下无横向溢出，按钮触控尺寸和进度方格按手机调过。

> 桌面托盘（最小化、托盘菜单）在 Android 上不存在；对应设置保留说明但不生效。Docker/PyInstaller 相关文件仍是上游的，本分支不保证它们可用。

---

## 结构

```text
tdm-vm/
├── run.py                 # 入口：假 GUI + 设备码登录 + 核心 + Flask 线程
├── webgui.py              # 签名对齐 gui.py 的假 GUI，捕获状态/频道/活动/日志/通知
├── catalog.py             # 公开掉宝目录回退（补 SMARTBOX 看不到新活动的缺陷）
├── history.py             # Twitch「已领取」流水落盘、按游戏分组、手动归属表
├── logi18n.py             # 面板运行日志中文化（log.txt 保持英文）
├── server/
│   ├── api.py             # Flask 路由、鉴权、设置写入、i18n
│   ├── templates/         # index / login / setup
│   └── static/            # app.css / app.js（无 CDN）
├── termux/
│   ├── push.sh            # PC 侧控制入口
│   ├── install.sh         # 设备侧安装（venv + pip + 初始文件）
│   ├── supervise.sh       # 守护 run.py，退出/崩溃自动拉起
│   ├── tdm-*.sh           # start/stop/status/env/pids
│   ├── boot-*.sh          # 开机自启与冷启验收
│   ├── twitchdrops-termux.sh  # Magisk service.d 钩子
│   └── shims/             # tkinter / PIL 空壳（headless 运行时需要 import）
├── TERMUX.md              # 更深一层的部署、验收和踩坑记录
└── ……上游原有文件（core、lang、licenses 等）
```

运行链路：

```text
PC (adb) --termux/push.sh--> ~/twitchdrops
                               ├─ run.py
                               │   ├─ asyncio: Twitch 核心（登录/挖矿/领取）
                               │   └─ Flask 线程 :8081
                               ├─ webgui.py -> 冒充 gui 模块
                               ├─ catalog.py -> 公开目录发现活动
                               └─ history.py -> gameEventDrops 历史
```

---

## 环境要求

- 手机已安装 Termux（包名 `com.termux`），并开启 USB 调试。
- PC 上有 `adb`、`bash`；Windows 下用 Git Bash 即可。
- Termux 里 Python 3.10+（实测 3.14.6）。安装脚本会自动 `pkg install` 编译链和 `ca-certificates`。
- 可选：Magisk/root，用于安装 `/data/adb/service.d` 开机自启钩子。
- 一个 Twitch 账号。设备码登录需要手机能访问 Twitch。

默认按 Termux uid `10250`、包名 `com.termux` 编写。不同设备请在脚本里调整 `su` 的 uid，或设置 `TDM_UID`（`push.sh` 使用）。

---

## 快速开始

```bash
git clone https://github.com/bplhkx/TwitchDropsMiner.git
cd TwitchDropsMiner/termux
```

1. 连接手机，确认设备：

```bash
adb devices
```

2. 首次安装（解包 + venv + pip；Termux 上 pip 会现场编译 aiohttp，耗时几分钟）：

```bash
bash push.sh            # 自动选第一台 adb 设备；多设备用 TDM_SERIAL=<serial> bash push.sh
bash push.sh follow     # 看安装日志
```

3. 启动：

```bash
bash push.sh start
bash push.sh status
```

4. 打开面板：

```text
http://<手机局域网IP>:8081
```

首次进入 `/setup` 设置**面板密码**（与 Twitch 密码无关），然后在「主面板 → 登录Twitch账户」按页面上的设备码到 <https://www.twitch.tv/activate> 完成授权。授权成功后核心会自动轮询令牌并开始载入库存。

5. 可选：开机自启（需要 root）：

```bash
bash push.sh boot
bash push.sh verifyboot   # 冷停 -> 跑钩子 -> 断言端口/环境/单实例
```

### 常用控制

```bash
bash push.sh scripts      # 只更新代码/脚本，不动 venv
bash push.sh stop
bash push.sh restart
bash push.sh status
bash push.sh follow
```

---

## 面板页面

| 页签 | 内容 |
| --- | --- |
| 主面板 | 置顶的掉宝活动进度（游戏封面、奖励图、本次已领取）、核心状态、库存载入方格、Websocket 8 槽位、Twitch 登录、运行日志、活动频道表（可手动切换）、已领取通知 |
| 掉宝库存 | 5 个筛选（未关联/即将上线/已结束/不在优先列表/已领取）、活动卡、奖励图和进度、ACL 频道、领取按钮 |
| 历史 | Twitch「已领取」流水，按优先列表分组；物品图/名称/领取时间/次数；支持只看优先列表；活动过期后仍保留 |
| 设置 | 语言、掉宝活动刷新频率、开机自启、托盘通知、夜间模式、未关联活动、挖掘模式、代理、连接质量、优先/排除列表、刷新库存 |
| 帮助 | 上游 About/链接/工作原理/入门说明、退出登录（真正 revoke token） |

### 历史掉宝与手动归属

历史数据来自 Twitch `Inventory.gameEventDrops`，不是当前活动里的 `isClaimed` 库存项。能反查到活动时自动归组；活动过期、Twitch 流水 `game=null` 时，可在设备侧的手动归属表里指定游戏。同一游戏下同名的多条奖励会折叠成 `名称 ×N` 的卡片，点击展开每次领取的时间/活动/图片。

```text
/data/data/com.termux/files/home/twitchdrops/history_game_map.json
```

```json
{
  "APEX Pack": "Apex Legends",
  "Random TF Archon Shard": "Warframe",
  "某条 benefit id": "某游戏"
}
```

键可以是 benefit id，也可以是奖励名；`history.record` 按文件 mtime 热加载，不需要重启。该文件和 `history.json` 都是设备运行时数据，`.gitignore` 已排除。

---

## 配置与运行时文件

| 文件 | 作用 |
| --- | --- |
| `settings.json` | 核心/面板设置；面板改设置会即时写入 |
| `panel.json` | 面板口令（pbkdf2-sha256），首次 `/setup` 生成 |
| `.env` | `TDM_WEB_PORT` / `TDM_WEB_HOST` / `PANEL_SECRET`（会话签名密钥） |
| `cookies.jar` | Twitch 会话（aiohttp CookieJar JSON），**等同账号凭据** |
| `history.json` | 已领取掉宝历史（version 2，`source=claimed`） |
| `history_game_map.json` | 旧奖励的手动游戏归属表 |
| `claimed_drops.json` | 成功 claim 过的 drop id；避免 Twitch 反复报告可领取导致重复请求/日志 |
| `catalog.cache.json` | 公开掉宝目录缓存 |
| `catalog.config.json` | 用户自定义的活动刷新间隔（秒） |
| `log.txt` | 核心日志 |
| `logs/server.log` | supervisor / run.py 控制台日志 |

`.env`、`panel.json`、`cookies.jar`、`history*.json`、`catalog.cache.json`、`settings.json` 都不应提交到仓库；`.gitignore` 与 `push.sh` 都会排除它们。

---

## 活动发现：为什么需要公开目录

Twitch 自 **2026-09-18** 对 `ViewerDropsDashboard` / `DropCampaignDetails` 增加了完整性校验：

- WEB 客户端报 `IntegrityCheckFailed`；
- `SMARTBOX`/`ANDROID_APP` 不报错，静默返回 `dropCampaigns: null` / `dropCampaign: null`；
- `Inventory` 仍正常，所以只能看到“已经参与/有进度”的活动。

为了设备码登录，本分支必须使用 SMARTBOX，因此 `catalog.py` 用公开目录 <https://drops.sunkwi.com/api/twitch/drops> 做**公开元数据发现层**：

- 账号库存、进度、Websocket、看播和领取仍全部直连 Twitch；
- 目录免费档为每 IP 每 5 分钟 1 次，`catalog.py` 有 310 秒最小间隔 + `catalog.cache.json` 磁盘缓存；限流时退回缓存；
- 首次就 429 且无缓存时，5 分钟后会自动再触发一次库存刷新；
- 目录无法知道账号关联状态，目录-only 活动按“已关联”展示；如果实际没绑定游戏账号，挂了不会给奖励，用优先/排除列表控制，或先点活动卡上的关联链接确认；
- 目录可能同时有上百个活动。默认 `ENDING_SOONEST` 会不断追“马上结束”的活动，想稳定刷某个游戏建议改成“仅观看优先列表中的游戏”并维护优先列表。

相关上游记录：issue #1162、PR #1174 / #1179 / #1180。

---

## 与上游同步

上游 `.py` 没有改动，但以下位置是运行时补丁/新增，合并上游时重点核对：

- `run.py`：`sys.modules['gui'] = webgui`、`ClientType.SMARTBOX`、`_AuthState._browser_login = _oauth_login`、`catalog.install`、`history.install_inventory`；
- `webgui.py`：对齐 `twitch.py` / `channel.py` / `inventory.py` 里的 `self.gui.*` 调用点；
- `catalog.py`：依赖 `Twitch._fetch_available_campaigns` / `fetch_campaigns` / `gql_request` 的形状；
- `history.py`：依赖 Inventory 的 `gameEventDrops` 字段和 `gql_request`；
- `server/api.py`：依赖上游 `State`、`PriorityMode` 和设置字段。

推荐 remote：

```bash
git remote add upstream https://github.com/Valentin-Metz/TwitchDropsMiner.git
git fetch upstream
git merge upstream/master
```

本 fork 不使用上游的 CI / Docker / 自动 rebase 工作流：它们会构建桌面 GUI、发布 Docker 镜像或自动 rebase 上游，和 Termux 面板分支不匹配。需要桌面构建/Docker 请使用上游仓库。

---

## 已知限制

- 面板是 Flask 开发服务器（多线程），**只适合局域网自用**，不要直接暴露公网；需要外网访问请自行加反向代理和 TLS。
- 链接公开目录只能提供公开活动元数据，且免费档限流；目录不可用时依赖缓存。
- 旧奖励的 `game` 在 Twitch 流水里是 `null`，活动过期后无法可靠自动归组；用 `history_game_map.json` 手动归属，否则进「未归类」。
- 面板只能记录 Twitch 侧的“已领取”，无法知道奖励是否已经到账游戏内。
- 少数活动会在 Twitch Inventory 里反复报告 `can_claim`，但 claim 已成功且不进 `gameEventDrops`；面板用 `claimed_drops.json` 记住已 claim 的 drop，阻止重复请求和日志刷屏。
- Android 没有系统托盘；`autostart_tray` 不生效，托盘通知映射为浏览器通知。
- 本项目是个人 fork，不提供任何账号安全/封号风险担保；请遵守 Twitch 服务条款。

---

## 致谢与许可

- 核心与桌面 GUI：[DevilXD/TwitchDropsMiner](https://github.com/DevilXD/TwitchDropsMiner)（MIT）
- Docker/headless fork 基线：[Valentin-Metz/TwitchDropsMiner](https://github.com/Valentin-Metz/TwitchDropsMiner)
- 公开掉宝目录：[Drops API](https://drops.sunkwi.com/docs)
- Termux 部署与踩坑细节见 [TERMUX.md](TERMUX.md)

代码沿用仓库的 MIT License；上游版权归 DevilXD 所有。
