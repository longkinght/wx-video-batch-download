---
name: wx-video-batch-download
description: "微信视频号批量下载助手。依托本机运行的 wx_video_download_safe 工具（ltaoo/wx_channels_download 的 _safe 构建，默认监听 127.0.0.1:2022），接收用户给的视频号链接 / 视频号 feed id / 视频号作者 username，自动提交到工具自带的下载队列（gopeed 内核完成下载 + WASM 解密）。触发词：视频号、wx_video_download、视频号下载、批量下视频号、wx_download、stodownload、finder.video.qq.com、视频号 share link。当用户提到视频号视频下载、想批量下某个作者的视频、或给我一段含视频号链接/作者 username 的文本希望我自动处理时调用。"
---

# 微信视频号批量下载

## 工具依赖（必须）

本 skill 是"驾驶舱"，依赖官方工具 `wx_video_download.exe`（"引擎"）的三个核心能力：
① 代理拦截微信流量拿登录态 ② gopeed 多线程下载 ③ WASM 视频解密。**exe 必须预先安装。**

- 官方仓库（MIT 协议）：https://github.com/ltaoo/wx_channels_download
- 官方下载：https://github.com/ltaoo/wx_channels_download/releases
- 下载 `wx_video_download_safe_v<版本>_windows_x86_64.zip` 并解压（Windows）
- 默认工具路径：`D:\信息收集中心\wx_video_download_safe_v260714_windows_x86_64\`（可改）

## 路径配置（分发用）

脚本顶部常量支持**环境变量覆盖**，便于在不同机器使用：

| 环境变量 | 作用 | 默认值 |
| --- | --- | --- |
| `WX_DL_TOOL_EXE` | 工具 exe 路径 | `D:\信息收集中心\...\wx_video_download.exe` |
| `WX_DL_TOOL_ROOT` | 工具目录 | `D:\信息收集中心\wx_video_download_safe_v260714_windows_x86_64` |
| `WX_DL_DL_DIR` | 下载目录 | `D:\信息收集中心\视频\video` |
| `WX_DL_TEMPLATE` | 文件名模板 | `{{author}}_{{download_at}}_{{filename}}_{{spec}}` |

例：`WX_DL_TOOL_ROOT=C:\tools\wx_download python wx_video_dl.py status`

## 何时调用

- 用户说："视频号下载"、"微信视频号批量"、"把这段里视频号链接下了"、"视频号作者主页都下了"
- 用户给一段文本（含视频号 share link、feed id、username），希望自动识别后下载
- 用户给我一个作者 username（`v2_xxx@finder`），希望批量下这个作者全部视频
- 用户希望"看一眼"任务进度、查看已下/待下/失败

## 前置条件

1. **工具已启动**：`wx_video_download.exe` 跑起来占 127.0.0.1:2022（脚本能自动拉起）
2. **视频号通道**（WS `/ws/channels` 注入）：
   - 工具重启后需在微信 PC 版视频号点开任意一个视频看到下载按钮，注入脚本才连上 WS
   - `status` 的 `available` 是脚本实测得出（工具源码 handleStatus 恒返回 false，勿信原始值）
   - 通道可能中途断（报"请先初始化客户端 socket 连接"）→ 用户微信重新点开视频即恢复
3. **Python 3.10+ + requests 库**：`pip install requests`

## 核心命令

```bash
python wx_video_dl.py status                          # 工具状态 + 通道探测
python wx_video_dl.py list --summary                  # 任务总览
python wx_video_dl.py list --status done --verbose    # 完成项 + 真实 URL
python wx_video_dl.py go <链接|作者|feed id>... --since 2026-06-30
#   go = 全自动：启动工具→体检配置→等通道→提交→等待→整理命名
python wx_video_dl.py author 'v2_xxx@finder' --since 2026-06-30 --yes
python wx_video_dl.py share '<分享链接>'
python wx_video_dl.py task start_all / pause_all / clear
python wx_video_dl.py organize --dir "下载目录" --apply   # 秒时间戳→YYYY-MM-DD
python make_manifest.py                                  # 下载后核对生成清单
```

## 输入识别规则

| 输入 | 识别为 |
| --- | --- |
| `1` 开头 17-22 位整数 | feed id，直接提交 |
| `https://weixin.qq.com/sph/<短码>` | 短码=eid，解析作者后按作者批量 |
| `https://channels.weixin.qq.com/web/pages/feed?feed_id=...` | 提取 feed id |
| `#小程序://视频号/.../<id>`（微信转发格式） | 提取末尾 id |
| `https://finder.video.qq.com/.../stodownload?...` | 走 create_channels 后端解析 |
| `v2_xxx@finder` | 作者 username，批量展开 |

## 技术要点（源码确认）

- `POST /api/task/create_channels {oid|url|eid}`：只需给 oid/url/eid 之一，后端自解析
  详情（finder URL + 解密 key）并创建+解密下载。**纯脚本批量下载的正确入口**。
- `POST /api/task/create` 需完整 url+key（来自浏览器注入），纯脚本会 500，不用它。
- 作者视频列表：`GET /api/channels/contact/feed/list?username=&next_marker=`
  翻页（lastBuffer 递归，continueFlag 控制），object[] 含 id + createtime（秒时间戳）。
- sph 短链：短码=eid → `GET /api/channels/feed/profile?eid=<短码>` 解析作者。
- 返回结构注意：feed/profile 返回透传 `{errCode, errMsg, data:{object...}, payload}`，
  object 在 `resp["data"]["object"]`；feed/list 经 unwrap 后 object 在 `data.data.object`。
- 图片集内容下载为 `.zip`（非 mp4）；画质可能不同（xWT111/xWT156），匹配用 `_xWT` 通配。
- 工具 config 不热加载：改 config.yaml 后必须重启工具。

## 下载后核对（防遗漏）

用 `make_manifest.py`（改 username 为作者）生成核查清单：
- 工具侧全量 vs 本地文件逐条匹配；标题匹配忽略空白差异（工具标题带换行 `\n#话题`）
- 同名不同日期视频各自独立匹配；输出 `<作者>_下载清单_<日期>.md` 到下载目录
- 核对要求：匹配数 = 工具侧总数，异常 = 0
