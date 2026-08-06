# -*- coding: utf-8 -*-
"""生成视频号下载核查清单（Markdown）—— 通用版。

用法：
    python make_manifest.py --username "v2_xxx@finder" [--author 作者名] [--dir 下载目录]

功能：拉取作者在工具侧的全部视频（feed id + 标题 + 发布时间），
与本地下载目录里的文件逐条匹配，输出核查清单，确保无遗漏。
匹配规则：
  - 标题匹配忽略空白差异（工具标题常带换行 \n#话题，文件名空格被压平）
  - 同名不同日期的视频（作者发多条同标题）各自独立匹配
  - 画质不同（xWT111/xWT156）不影响标题匹配
  - 图片集内容为 .zip 也计入
"""
import argparse
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wx_video_dl as m  # noqa: E402


def norm(s: str) -> str:
    """去掉所有空白差异（换行/空格），便于标题匹配。"""
    return re.sub(r"\s+", "", s)


def main():
    ap = argparse.ArgumentParser(description="生成下载核查清单")
    ap.add_argument("--username", required=True, help="作者 username（v2_xxx@finder）")
    ap.add_argument("--author", default="", help="作者显示名（用于清单标题与文件名前缀，缺省取视频里的昵称）")
    ap.add_argument("--dir", default="", help="下载目录（缺省用 wx_video_dl 的 PREFERRED_DL_DIR）")
    ap.add_argument("--out", default="", help="清单输出路径（缺省 <下载目录>/<作者>_下载清单_<日期>.md）")
    args = ap.parse_args()

    client = m.WXChannelsClient()

    # 通道检测：避免裸报错
    if not client.channels_available():
        print("⚠ 视频号通道未就绪（WS 未连接）。")
        print("  请在微信 PC 版视频号点开任意一个视频（看到下载按钮）后重试。")
        sys.exit(1)

    # ---- 工具侧全量 ----
    videos = {}
    marker = ""
    seen = set()
    while True:
        data = client.contact_feed_list(args.username, marker)
        obj = (data.get("data") or {}).get("object") or []
        inner = data.get("data") or {}
        for item in obj:
            videos[str(item.get("id"))] = {
                "title": ((item.get("objectDesc") or {}).get("description") or "").strip(),
                "ct": item.get("createtime") or 0,
            }
        lb = inner.get("lastBuffer", "") if isinstance(inner, dict) else ""
        cont = inner.get("continueFlag", 0) if isinstance(inner, dict) else 0
        if not cont or not lb or lb in seen:
            break
        seen.add(lb)
        marker = lb

    # 作者显示名：优先命令行，其次从任一视频的 contact 拿
    author = args.author
    if not author and videos:
        try:
            data = client.contact_feed_list(args.username, "")
            obj = (data.get("data") or {}).get("object") or []
            if obj:
                author = ((obj[0].get("contact") or {}).get("nickname") or "").strip()
        except Exception:
            pass
    if not author:
        author = args.username.split("@")[0]

    # ---- 本地文件 ----
    dst = args.dir or m.PREFERRED_DL_DIR
    local_map = {}
    for f in os.listdir(dst):
        if not f.startswith(author):
            continue
        if not f.lower().endswith((".mp4", ".zip")):
            continue
        m2 = re.match(
            r"%s_(?:20\d{2}-)?\d{2}-\d{2}_(.+?)(?:_xWT\d+(?:\(\d+\))?\.(?:mp4|zip))$"
            % re.escape(author),
            f,
        )
        title = norm(m2.group(1)) if m2 else norm(f)
        p = os.path.join(dst, f)
        local_map[title] = {
            "file": f,
            "size": os.path.getsize(p),
            "mtime": datetime.datetime.fromtimestamp(
                os.path.getmtime(p)
            ).strftime("%Y-%m-%d %H:%M"),
        }

    # ---- 逐条匹配 ----
    rows = []
    unmatched_local = set(local_map.keys())
    for fid, v in sorted(videos.items(), key=lambda kv: kv[1]["ct"]):
        t = re.sub(r"\s+", " ", v["title"])
        tn = norm(t)
        hit = None
        for lt in local_map:
            if tn == norm(lt) or tn[:12] in norm(lt) or norm(lt)[:12] in tn:
                hit = lt
                break
        d = datetime.datetime.fromtimestamp(v["ct"]).strftime("%Y-%m-%d")
        if hit:
            unmatched_local.discard(hit)
            lf = local_map[hit]
            rows.append((d, t, lf["file"], lf["size"], lf["mtime"], "OK"))
        else:
            rows.append((d, t, "(MISSING)", 0, "", "MISS"))

    for lt in unmatched_local:
        lf = local_map[lt]
        rows.append(("", "(EXTRA)", lf["file"], lf["size"], lf["mtime"], "EXTRA"))

    # ---- 写 Markdown ----
    today = datetime.date.today().strftime("%Y-%m-%d")
    out = args.out or os.path.join(dst, "%s_下载清单_%s.md" % (author, today))
    ok_n = sum(1 for r in rows if r[5] == "OK")
    bad_n = len(rows) - ok_n
    total_size = sum(r[3] for r in rows)
    lines = []
    lines.append("# %s · 视频号全量下载清单" % author)
    lines.append("")
    lines.append("- 作者：%s" % author)
    lines.append("- 核对时间：%s" % today)
    lines.append("- 工具侧视频总数：%d 个" % len(videos))
    lines.append("- 本地文件：%d 个（匹配 %d / 异常 %d）" % (len(rows), ok_n, bad_n))
    lines.append("- 下载目录：`%s`" % dst)
    lines.append("- 总大小：%.2f GB" % (total_size / 1e9))
    lines.append("")
    lines.append("| # | 发布日期 | 标题 | 本地文件 | 大小 | 状态 |")
    lines.append("|---|----------|------|----------|------|------|")
    for i, (d, t, fname, size, _mtime, status) in enumerate(rows, 1):
        t_clean = t.replace("|", "\\|")[:60]
        f_clean = fname.replace("|", "\\|")[:70]
        size_s = "%.1fMB" % (size / 1e6) if size else "-"
        lines.append("| %d | %s | %s | %s | %s | %s |" % (i, d, t_clean, f_clean, size_s, status))

    with open(out, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines) + "\n")

    print("清单已生成：%s" % out)
    print("共 %d 行，匹配 %d，异常 %d" % (len(rows), ok_n, bad_n))
    if bad_n:
        print("⚠ 有异常，请人工核查 MISS / EXTRA 行！")
        sys.exit(1)


if __name__ == "__main__":
    main()
