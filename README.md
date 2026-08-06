# wxvideo-download-hb

微信视频号下载（单条 / 批量）的 WorkBuddy Skill —— 给它一个视频号链接（单条）或作者主页（批量），自动解析、下载并生成核查清单。

> 本仓库是**使用层工具集**（Skill + 脚本），不包含下载引擎本体。引擎是官方开源工具
> [ltaoo/wx_channels_download](https://github.com/ltaoo/wx_channels_download)（MIT 协议），
> 请从官方 Releases 下载。

## 原理

本仓库的脚本是"驾驶舱"，负责编排；下载引擎是官方工具 `wx_video_download.exe`，负责：
代理拦截微信视频号流量 → 拿登录态 → gopeed 多线程下载 → WASM 解密。

```
你给链接/作者
   ↓
wx_video_dl.py（本仓库）—— 解析作者、按日期过滤、提交任务、等待、整理命名
   ↓ 调用本地 API (127.0.0.1:2022)
wx_video_download.exe（官方工具，需自行下载）—— 下载 + 解密
   ↓
本地目录：作者_日期_标题_画质.mp4
```

## 安装

### 1. 下载官方工具（必需）

- 仓库：https://github.com/ltaoo/wx_channels_download
- Releases：https://github.com/ltaoo/wx_channels_download/releases
- 下载 `wx_video_download_safe_v<版本>_windows_x86_64.zip`，解压到任意目录
- 默认路径配置在 `scripts/wx_video_dl.py` 顶部常量（可用环境变量覆盖，见下）

> **兜底下载**：本仓库 Release 附件里也附带了一份
> `wx_video_download_safe_v260714_windows_x86_64.zip`（官方 v260714 构建，含 exe +
> 默认配置 + LICENSE）。若官方仓库不可用，可从本仓库 Release 附件下载；
> 可用时仍建议优先用官方最新版。校验和见 `checksums.txt`。

### 2. 安装 Python 依赖

```
pip install requests
```

### 3. 安装 Skill（WorkBuddy 用户）

把本仓库的 `SKILL.md` 和 `scripts/` 复制到：

- Windows：`C:\Users\<你>\.workbuddy\skills\wxvideo-download-hb\`

```
wxvideo-download-hb/
├── SKILL.md
└── scripts/
    ├── wx_video_dl.py
    └── make_manifest.py
```

## 快速开始

```bash
# 1) 启动工具（也可由脚本自动拉起）
wx_video_download.exe &

# 2) 微信 PC 版 → 视频号 → 点开任意一个视频（看到下载按钮，建立注入通道）

# 3) 下载某个作者的全部视频
python scripts/wx_video_dl.py go "https://weixin.qq.com/sph/XXXXXXXX" --since 2026-06-30

# 4) 等下载完成并查看
python scripts/wx_video_dl.py list --summary

# 5) 生成核查清单
python scripts/make_manifest.py   # 脚本内修改 username 为你的目标作者
```

## 命令一览

```
python wx_video_dl.py status                          工具状态 + 视频号通道探测
python wx_video_dl.py go <链接|作者|feed id>... [--since YYYY-MM-DD] [--spec xWT111]
                                                     全自动：启动→体检→等通道→提交→等待→整理
python wx_video_dl.py add <feed id|share link>...    提交任务
python wx_video_dl.py author '<v2_xxx@finder>' --since 2026-06-30 --yes
                                                     按作者批量（可日期过滤）
python wx_video_dl.py share '<分享链接>'             分享链接解析后下载
python wx_video_dl.py list / watch / task ...        查看/等待/控制任务
python wx_video_dl.py organize --dir <目录> --apply  秒时间戳文件名 → YYYY-MM-DD
```

## 路径配置（环境变量）

| 变量 | 作用 | 默认 |
| --- | --- | --- |
| `WX_DL_TOOL_EXE` | 工具 exe 路径 | 脚本顶部常量 |
| `WX_DL_TOOL_ROOT` | 工具目录 | 脚本顶部常量 |
| `WX_DL_DL_DIR` | 下载目录 | `~/Downloads/wx_video_dl` |
| `WX_DL_TEMPLATE` | 文件名模板 | `{{author}}_{{download_at}}_{{filename}}_{{spec}}` |

## 常见问题

**Q: 提示"请先初始化客户端 socket 连接"？**
A: 视频号通道断了。在微信 PC 版视频号重新点开任意一个视频，看到下载按钮后重试。

**Q: 下载的是 `.zip` 而不是 mp4？**
A: 该视频是图片集内容，工具会打包成 zip，属正常行为。

**Q: `status` 显示 `available: false` 但能用？**
A: 正常。工具源码 handleStatus 恒返回 false，脚本已改为实测探测。

**Q: 改完 config.yaml 不生效？**
A: 工具不热加载配置，修改后必须重启 `wx_video_download.exe`。

## 免责声明

- 本仓库仅提供自动化编排脚本，不包含任何抓取、解密引擎实现（引擎为第三方开源项目）。
- 请仅下载你有权保存的内容（自己发布的、已获授权转载的等），并遵守微信平台服务条款与所在地法律法规。
- 工具的下载、使用、分发请遵循其 MIT 协议及官方说明。


## 关于作者

本 Skill 由 **[@longkinght](https://github.com/longkinght)** 编写并维护。

> 喜欢把重复性的下载 / 整理 / 归档工作自动化，习惯用 WorkBuddy Skill 把繁琐流程封装成「一句话就能跑」的工具。欢迎在仓库提 Issue 与 PR，也欢迎交流自动化玩法。

## License

本仓库脚本与文档采用 MIT 协议（见 [LICENSE](./LICENSE)）。
引擎 `wx_video_download.exe` 为 [ltaoo/wx_channels_download](https://github.com/ltaoo/wx_channels_download) 的 MIT 开源构建。
