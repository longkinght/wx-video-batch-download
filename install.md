# 安装为 WorkBuddy Skill

## 方法一：手动复制（最简单）

1. 把本仓库整个目录（或 `SKILL.md` + `scripts/`）复制到 WorkBuddy 技能目录：

   - Windows：`C:\Users\<你>\.workbuddy\skills\wx-video-batch-download\`
   - macOS / Linux：`~/.workbuddy/skills/wx-video-batch-download/`

   最终结构：

   ```
   wx-video-batch-download/
   ├── SKILL.md
   ├── scripts/
   │   ├── wx_video_dl.py
   │   └── make_manifest.py
   └── (README.md / LICENSE 可选)
   ```

2. 重启 WorkBuddy（或新开会话），skill 即被识别。

3. 在对话里说"下这个视频号" / "视频号批量下载"即可触发。

## 方法二：git clone 到技能目录

```bash
git clone https://github.com/<你>/wx-video-batch-download.git \
  ~/.workbuddy/skills/wx-video-batch-download
```

## 前提

- 安装官方工具（引擎）：见仓库 README「安装」一节
- Python 3.10+，`pip install requests`
- 首次使用：启动工具 → 微信视频号点开一个视频（建立注入通道）

## 路径自定义

不同机器上工具路径不同，可用环境变量覆盖（免改代码）：

```bash
# Windows PowerShell
$env:WX_DL_TOOL_ROOT = "C:\tools\wx_video_download_safe"
$env:WX_DL_DL_DIR    = "D:\我的视频号视频"

# macOS / Linux
export WX_DL_TOOL_ROOT="$HOME/tools/wx_video_download_safe"
export WX_DL_DL_DIR="$HOME/视频/video"
```

也支持写入 `~/.workbuddy/skills/wx-video-batch-download/scripts/.env`（若使用 dotenv）或直接改脚本顶部常量。
