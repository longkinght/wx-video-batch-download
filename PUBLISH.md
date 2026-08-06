# 发布指引（GitHub）

把本目录内容推上 GitHub 的完整步骤。分两步：**仓库文件** + **Release 附件（兜底 exe）**。

## 一、推送仓库

```bash
cd "<你的发布工作目录>"

git init
git add .
git commit -m "init: wxvideo-download-hb skill + scripts + 兜底工具包说明"

# 用 gh 建仓库并推送（需先 gh auth login）
gh repo create wxvideo-download-hb --public --source=. --push
```

不装 gh 的话：去 github.com 手动新建空仓库，然后：
```bash
git remote add origin https://github.com/<你的用户名>/wxvideo-download-hb.git
git branch -M main
git push -u origin main
```

## 二、上传 Release 附件（兜底 exe，20MB）

1. 在 GitHub 仓库页打开 **Releases → 新建 Release**
2. Tag：`v1.0.0`（或跟随工具版本如 `v260714`）
3. 标题/说明：简述功能 + 指向官方仓库
4. **附件**：把 `wx_video_download_safe_v260714_windows_x86_64.zip`（本目录下）和
   `checksums.txt` 拖进去
5. 发布

> 为什么不把 zip 放仓库文件区：GitHub 仓库体积会被 20MB 二进制永久占用，
> 每个 clone 都要下载；Release 附件不占仓库体积、按需下载、可多版本共存。

## 三、发布后检查清单

- [ ] 仓库文件区不含 `.zip`（zip 只在 Release 附件）
- [ ] `README.md` 里的"兜底下载"段指向自己的 Release 页
- [ ] `scripts/wx_video_dl.py` 无个人路径残留（默认值可被 `WX_DL_*` 环境变量覆盖）
- [ ] `checksums.txt` 与 Release 附件的 zip 一致
- [ ] 试跑一遍：另一台机器 clone → 下载工具 zip → 解压 → `python wx_video_dl.py status`

## 四、License 与版权提示

- 本仓库脚本/文档：MIT（见 LICENSE）
- 附带的 exe：官方 [ltaoo/wx_channels_download](https://github.com/ltaoo/wx_channels_download)
  的 MIT 开源构建，随 zip 内含其 LICENSE；README 已注明来源与免责声明
