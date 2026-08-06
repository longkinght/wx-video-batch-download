---
name: wxvideo-download-hb
description: "微信视频号下载助手（单条 / 批量）。依托本机已运行的 wx_video_download_safe 工具（ltaoo/wx_channels_download 的 _safe 构建，默认监听 127.0.0.1:2022），接收用户给的视频号分享链接 / sph 短链 / feed id / 作者 username，自动提交到工具下载队列（gopeed 内核下载 + WASM 解密）。两种场景：①单个视频——一条 weixin.qq.com/sph/... 短链或 feed id，默认只下这一个；②批量视频——作者 username(v2_xxx@finder)或作者主页，或短链加 --all，展开该作者全部视频批量下载。触发词：视频号、视频号下载、视频号批量、单个视频号下载、wx_video_download、wx_download、stodownload、finder.video.qq.com、视频号 share link、weixin.qq.com/sph。当用户提到视频号视频下载、想下某个作者的全部视频、或给一段含视频号链接/作者的文本希望自动处理时调用。"
---

# 微信视频号下载（单条 / 批量）

## 两种使用场景

本 skill 支持两种规模，按用户输入自动路由：

| 场景 | 触发输入 | 命令示例 | 行为 |
|---|---|---|---|
| **① 单个视频下载** | 一条视频号分享链接（含 `weixin.qq.com/sph/...` 短链）、feed id、或一条 `finder.video.qq.com` URL | `go <sph链接>` / `go <feed_id>` | 只下这**一个**视频（`resolve_sph` 解析出 feed_id 单条提交） |
| **② 批量视频下载（按作者）** | 作者 username（`v2_xxx@finder`）、作者主页链接，或对某条视频加 `--all` | `go <作者username>` / `go <sph链接> --all` | 展开该作者**全部**视频（受 `--max-per-author` / `--since` 约束）批量提交 |

要点：
- **sph 短链默认 = 单条**。`go https://weixin.qq.com/sph/XXXX` 只下该视频；要连同作者其它视频一起下，加 `--all`。
- 作者 username / 作者主页 = 批量（整作者）。
- 也可用 `add <feed_id>` 走单条、`author <username>` 走整作者，等价但 `go` 更一体化（自动拉起工具 + 等通道 + 整理命名）。

## 打包分发说明（给其他人用）

**重要前提**：`wx_video_dl.py` 不是独立实现——它是"驾驶舱"，依赖
`wx_video_download.exe`（官方工具）这个"引擎"提供三个核心能力：
① 代理拦截微信流量拿登录态 ② gopeed 多线程下载 ③ WASM 视频解密。
**exe 必须一起分发，不能省。**

**exe 来源（官方开源构建）**：
- 仓库：https://github.com/ltaoo/wx_channels_download （MIT，可自由分发）
- 官方 Releases：https://github.com/ltaoo/wx_channels_download/releases
- 用户本地的 `wx_video_download_safe_v260714_windows_x86_64` 就是官方 v260714
  release 的 `wx_video_download_safe_v260714_windows_x86_64.zip`（20MB）

**打包清单**（三样一起发）：
```
wx_video_download_safe_v260714_windows_x86_64\   ← 官方工具目录（引擎）
wx_video_dl.py                                     ← 驾驶舱脚本（本 skill scripts/ 下）
SKILL.md                                           ← 本说明
```

**对方的使用步骤**（零安装，只需 Python 3.10+）：
1. 解压工具目录，双击运行 `wx_video_download.exe`（首次会装证书+设代理）
2. 微信 PC 版 → 视频号 → 点开任意一个视频，看到下载按钮（让注入脚本连上 WS）
3. 运行脚本：`python wx_video_dl.py go <链接或作者>...`

**路径可配置**：若对方把工具放别处，改脚本顶部 `TOOL_EXE` / `TOOL_ROOT` 两个常量，
或直接改 `config.yaml` 里 `api.hostname/port` 指向对方机器的 2022 端口。

## 何时调用

- 用户说："视频号下载"、"微信视频号下载"、"下这个视频号视频"、"把这段里视频号链接下了"
- 用户给一条视频号分享链接 / `weixin.qq.com/sph/...` 短链 / feed id → **单个视频下载**
- 用户说"视频号作者主页都下了"、"把这个作者的视频都下了"、"批量下视频号"
- 用户给一个作者 username（`v2_xxx@finder`）或作者主页链接 → **批量视频下载**
- 用户给一段文本（含视频号 share link、feed id、username），希望我自动识别后下载
- 用户给我一条 `https://finder.video.qq.com/.../stodownload?` URL，希望下载
- 用户希望"看一眼"任务进度、查看已下/待下/失败

## 何时不要调用

- 用户问的是抖音/快手/B站等其他平台 → 不在范围
- 用户希望看视频号网页内容（爬虫/分析）→ 这是另一个工具流，不是下载
- 工具未启动 / 端口未开 → 不要硬试，提示用户先启动工具

## 前置条件（必须在第一次对话里确认）

1. **工具已启动**：`wx_video_download.exe（由 WX_DL_TOOL_EXE / WX_DL_TOOL_ROOT 环境变量指定；默认在脚本同级目录的 wx_video_download_safe_v260714_windows_x86_64\ 下）` 跑起来，占 127.0.0.1:2022。**脚本能自动拉起**（`go` 命令的 ensure_tool_running），无需手动。
2. **视频号通道**（WS `/ws/channels` 注入）：
   - 工具重启后需在**微信 PC 版视频号点开任意一个视频**看到下载按钮，注入脚本才连上 WS
   - `status` 命令的 `available` 是脚本实测得出的（工具源码 handleStatus 恒返回 false，勿信原始值）
   - **通道可能中途断**（报"请先初始化客户端 socket 连接"）→ 让用户微信重新点开视频即可恢复
3. **Python + requests 库可用**：本机 Python 3.10+，`pip install requests`

## 默认配置（可自定义）

- **下载目录**：`~/Downloads/wx_video_dl（由 WX_DL_DL_DIR 环境变量指定）`（工具 config.yaml `download.dir`）
- **文件名模板**：`{{author}}_{{download_at}}_{{filename}}_{{spec}}`
  （`{{download_at}}` 是秒时间戳，可用 `organize` 子命令转 YYYY-MM-DD）
- **注意**：工具**不热加载配置**——改 config.yaml 后必须重启工具才生效；未重启时新文件
  会落旧目录 `~/Downloads（即 %UserDownloads%）` 且旧命名（`标题_xWT111.mp4`），需手动整理

## 调用约定

### 工作流速记

1. 先确认工具在线：`GET /api/status` 应返回 `code:0`
2. 看一眼任务列表，避免重复：`scripts/wx_video_dl.py list`
3. 解析用户输入：
   - 单条/多条 feed id、share link → `add <items...>`
   - 作者 username → `author <username>`（前置是 available:true）
   - 整段文本混合 → `probe --paste <...>` 或 `probe < file.txt`
   - 一条 finder URL → `url <URL>`（注意：会得到加密 mp4，必须经工具内核解密；首选走 add）
4. 启动任务：`add` / `author` 已经创建了 gopeed 任务
5. 监控进度：`watch` 子命令轮询直到全部 settled
6. 报告下载目录：`list --status done` 输出里 `name` 列就是文件保存路径（由工具按 `config.yaml` 的 `download.filenameTemplate` 命名）

### 一键全自动：`go` 命令（推荐主入口）

`go` 把整个流程打包成一条命令，WorkBuddy 调用 skill 时直接跑它：

```
python scripts/wx_video_dl.py go <feed_id|分享链接|作者username|sph短链>... [--spec xWT111] [--all]
```

内部流程（全自动，无需人工干预）：
1. **启动工具**：检测 127.0.0.1:2022，未运行自动拉起 `wx_video_download.exe`
2. **体检配置**：检查 config.yaml 是否已按用户偏好（下载目录 + 作者日期模板）
3. **等待视频号通道**：探测 `/api/channels/contact/search`；未就绪时提示
   「请在微信视频号点开一个视频」（这是**唯一需要用户手动的步骤**），轮询等待
4. **提交任务**：按输入类型路由——
   - **单条**：feed id / finder URL / `sph` 短链 → 直接解析出 feed_id 单条提交
   - **批量**：作者 username / 作者主页 → `expand_author` 展开全部视频；`sph` 短链加 `--all` 也走批量
5. **等待完成**：轮询直到全部 done/error
6. **整理命名**：默认自动跑 organize（秒时间戳 → YYYY-MM-DD）

**用户唯一需要手动做的事**：
- 首次/工具重启后：`wx_video_download.exe` 起来后，在微信 PC 版视频号点开任意
  一个视频看到下载按钮（让注入脚本连上 WS 通道）
- **改 config.yaml 后必须重启工具**（工具不是热加载配置）

### 关键命令

```bash
# 在 skill 安装目录下：
python scripts/wx_video_dl.py status         # 工具状态
python scripts/wx_video_dl.py list --summary  # 任务总览
python scripts/wx_video_dl.py list --status done --verbose  # 看完成项 + 真实 URL

python scripts/wx_video_dl.py add <feed_id>        # 单 feed id（走 create_channels）
python scripts/wx_video_dl.py add 'https://channels.weixin.qq.com/web/pages/feed?feed_id=...'  # share link
python scripts/wx_video_dl.py author 'v2_xxx@finder' --yes   # 全部视频
python scripts/wx_video_dl.py probe --paste "..." --yes      # 文本里啥格式都行
python scripts/wx_video_dl.py share '<分享链接>'             # 分享链接解析后下载
python scripts/wx_video_dl.py task start_all / pause_all / clear
python scripts/wx_video_dl.py task start --id <task_id> / pause / resume / delete
python scripts/wx_video_dl.py follow                        # 关注列表（需 available:true）
python scripts/wx_video_dl.py watch                          # 阻塞等待完成
```

### 任务提交逻辑（2026-08-06 二次勘探后修正）

- **`POST /api/task/create_channels`**（body `{oid, nid, eid, url, spec, mp3, cover}`）—— 只需给
  feed id / URL / eid 之一，**后端自己调视频号接口拉详情（真实 finder URL + 解密 key），自动创建 +
  解密下载**。这是纯脚本批量下载的**正确入口**。缺 channels 登录态时后端报
  `JSAPI_JSONPARSE_FAILED`，此时单视频 409（已存在）也能证明链路是通的。
- `POST /api/task/create`（body `{id, nonce_id, url, title, filename, key, spec, suffix,
  overwrite, duplicate}`）—— 需**完整 url + key**（来自浏览器注入脚本抓到的页面数据），
  纯脚本场景多半 500（`unsupported protocol` = url 为空）。
- `POST /api/task/create_batch`（body `{feeds: [...]}`）—— 批量创建，后端按 `id|spec|suffix`
  自动去重。
- 作者维度：`GET /api/channels/contact/feed/list?username=&next_marker=`（lastBuffer 翻页，
  返回 `data.data.data.object[]` 每个 `id` 即 feed id）→ 批量 create_channels。RSS
  （`/rss/channels`）作为回退。
- 分享链接解析：`GET /api/channels/shared_feed/profile?url=`、`GET /api/channels/feed/profile`
  （oid/nid/url/eid）、`GET /api/channels/parse_sph?url=`（走腾讯元宝 API，需
  `config.yaml` 配 `cloudflare.sphCookie`）。

### 完整 API 清单（来自源码 internal/api/routes.go）

视频号（需 channels.available:true）：`/api/channels/contact/search`、
`/api/channels/contact/feed/list`、`/api/channels/feed/profile`、
`/api/channels/live/replay/list`、`/api/channels/interactioned/list`、
`/api/channels/follow/list`、`/api/channels/shared_feed/profile`、
`/api/channels/feed/comment/list`、`/api/channels/feed/share_url`、
`/api/channels/parse_sph`、`/rss/channels`

任务（无需登录态）：`/api/task/list`、`/api/task/profile`、`/api/task/create`、
`/api/task/create_batch`、`/api/task/create_channels`、`/api/task/create2`、
`/api/task/create3`、`/api/task/start`、`/api/task/start_all`、`/api/task/pause`、
`/api/task/pause_all`、`/api/task/resume`、`/api/task/delete`、`/api/task/clear`

WebSocket：`/ws/downloader`、`/ws/channels`；文件：`/play`、`/file`、`/preview`

### 重要细节

- **视频号视频文件本身是加密的 mp4**（XOR + WASM key）。直接 `url` 下载拿到的是加密片，普通播放器打不开。要可播放的，必须走 `add` / `author` 让 gopeed 内核自动解密并存盘到工具配置的 `download.dir`（默认 `%UserDownloads%`，即 `~/Downloads（即 %UserDownloads%）`）。
- **文件名**：`add` / `author` 调用 `--prefix` + `--spec`（如 `xWT111`）拼接，会被 gopeed 按 `config.yaml` 的 `filenameTemplate` 二次命名。最终落到 `download.dir` 时是 `{{filename}}_{{spec}}.mp4`，所以重复运行会产生同名文件（任务状态变 done，但磁盘上被覆盖/跳过）。
- **任务重复保护**：相同 `id` 重复 `add` 会返回 `409 已存在该下载内容`，不会真重复下载——脚本对这种情况把消息返回给用户即可。
- **可用画质**（`X-snsvideoflag`）：xWT98 / xWT111 / xWT127 等，规格越高越大。具体可下画质由视频号接口和视频上传时的编码决定。

### 当 `channels.available:false` 时

- 单 share link / 单 feed id **仍能 add**（任务入队到 gopeed，但 500 报 `unsupported protocol`，因为后端拿不到真实 URL）
- **作者维度的 `author` 子命令会失败**
- 兜底：先让用户在浏览器打开视频号对应的视频/作者主页（让工具嗅探到 cookie），再重试

## 短链接/分享链接 解析规则

| 输入形式 | 解析方式 |
| --- | --- |
| `<feed_id>`（1开头 17-22 位） | 当作 feed id 直接 add |
| `https://channels.weixin.qq.com/web/pages/feed?feed_id=ABC` | 提取 ABC 当 feed id |
| `#小程序://视频号/.../<id>`（微信转发格式） | 提取末尾 id |
| `pages/feed/feed.html?feed_id=ABC`（小程序路径） | 提取 ABC |
| `https://finder.video.qq.com/.../stodownload?...`（raw 下载地址） | 建议走 add 自动解密，或 url 直下（加密 mp4） |
| `v2_xxxxxx@finder` | 当作者 username |

## 失败处理

| 现象 | 处理 |
| --- | --- |
| `connection refused` | 工具没启动 → 让用户启动 `wx_video_download.exe` |
| `404` | API 路径错误（基本不会发生） |
| `400 不合法的参数` 或 `缺少 feed id` | feed id 字段名错了 / 缺失；脚本已经处理 |
| `409 已存在该下载内容` | 之前已下过 → 跳过，列出已完成项 |
| `500 unsupported protocol` | 用错了接口（task/create 需要完整 url+key）；应走 create_channels |
| `status.available=false` | **勿信**——源码 handleStatus 恒写死 false。用 `status` 命令会改调 contact/search 实测；返回 true 即可用 |
| 下载缓慢/中断 | 通常是 CDN 抖动，重试 `add` 即可；工具默认多线程（`MaxRunning:3`） |
| 文件不是 mp4 格式 | 加密 mp4——必须用 add 让内核解密 |

## 实战验收（2026-08-06 全链路跑通）

### 标准工作流（已验证，可直接复用）

给一个**视频号分享链接**（如 `https://weixin.qq.com/sph/XXXX`）要下作者全部视频时：

1. **解析作者**：sph 短码就是视频 eid → `GET /api/channels/feed/profile?eid=<短码>` 返回
   `data.data.object`（含 id / contact.username / contact.nickname / createtime）。
   短链 301 到 `channels.weixin.qq.com/finder-preview/pages/sph?id=<短码>`，短码即 eid。
   ⚠️ 返回结构是透传的 `{errCode, errMsg, data:{object...}, payload}`，**object 在
   `resp["data"]["object"]`**（不是两层 data）。
2. **拉作者全量**：`GET /api/channels/contact/feed/list?username=&next_marker=` 翻页
   （lastBuffer 递归，continueFlag 控制），object[] 每项含 `id` + `createtime`（秒时间戳）。
   ⚠️ 经 `_unwrap` 后返回 `{errCode, errMsg, data:{object...}}`，**object 在 `data.data.object`**。
3. **按日期过滤**：`--since 2026-06-30`（`parse_since` 转当天 0 点时间戳），expand_author
   里 `createtime >= since_ts` 才保留。
4. **批量提交**：`submit_tasks` 走 `POST /api/task/create_channels`（body `{oid}`），
   已下过的自动 409 dup 跳过。
5. **等待**：`watch` 轮询 status_counts 直到全部 settled。
6. **整理归档**：从下载目录（旧配置时是 Downloads）把新文件移到下载目录，重命名
   `作者_日期_标题_画质.mp4`。⚠️ 画质可能不同（xWT111 / xWT156），匹配时用 `_xWT` 通配；
   图片集内容会下载成 `.zip`（如斯坦福AI系统课）。

### 下载后核对（防遗漏，必做）

用 `scripts/make_manifest.py`（先填 username）生成核查清单：
- 工具侧全量（feed id + 标题 + createtime）vs 本地文件逐条匹配
- 标题匹配要**忽略空白差异**（工具标题常带换行 `\n#话题`，本地文件名空格被压平）
- 同名不同日期的视频（作者发两条同标题）各自独立匹配
- 输出 `曲率出逃_下载清单_YYYY-MM-DD.md` 到下载目录，含 37 行明细 + 统计头
- 核对结果要求：匹配数 = 工具侧总数，异常 = 0

### 实测案例（曲率出逃，37/37 ✓）

- 工具侧全量 37 个（最新 08-04《真正的FDE人才》，最旧 03-11《大厂出手了全自动安装龙虾》）
- 6/30 后 26 个 + 6/30 前 11 个；之前误以为 15 个（limit 截断），修复翻页后正确
- 3 个早期视频画质 xWT156（非 xWT111），按 `_xWT` 通配才没漏
- 斯坦福AI系统课是图片集 → 下载为 .zip（3.3MB）
- 同标题《如何搭建企业AI知识库》×2（07-09、07-17），按发布日期区分
- 最终 下载目录 40 个文件（曲率出逃 37 + 飞书多维 3），1.20 GB
- 用户操作：全程只需 ① 启动工具 ② 微信点开一个视频（WS 注入）；断线时再点一次即可

## 演示：从 0 到可下载

```bash
# 1) 启动工具
"wx_video_download.exe"  # 或用 WX_DL_TOOL_EXE 指定完整路径

# 2) 确认上线
python scripts/wx_video_dl.py status

# 3) 浏览器打开 https://channels.weixin.qq.com 任一视频或作者主页，让工具嗅探 cookie
#    这一步至关重要！available:false 时作者维度无法展开，单视频 add 也容易 500

# 4) 查看可用——确认 available:true
python scripts/wx_video_dl.py status

# 5) 给我 feed id / share link / 文本，我调用：
python scripts/wx_video_dl.py add <id> --spec xWT111
python scripts/wx_video_dl.py author <username> --yes
python scripts/wx_video_dl.py probe --paste "<你的文本>" --yes

# 6) 等等看
python scripts/wx_video_dl.py watch
```

## 复盘与已知坑

- 工具有 `gopeed.db` SQLite 数据库，所有任务历史在里面；任务列表 `/api/task/list` 可以拉到（分页参数 `page`、`status`）
- `id=19位整数` 是**腾讯视频号内部字段**，不是用户能拿到的明文；只能从浏览器看到视频页面时让工具注入脚本自动抓
- 用户在微信里复制的链接里有时不是 feed_id 而是 `exportkey=...` 之类的分享 key——目前不在识别范围，需要用户手动进视频号分享给浏览器后才能用本 skill
- `task/create` 在 available:false 时因为 video URL 拿不到会 500——skill 不重试，建议让用户先打开浏览器看一次
- finder URL 真能直下，但**拿到的是加密 mp4**，不能播
