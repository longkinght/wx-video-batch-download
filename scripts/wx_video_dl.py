#!/usr/bin/env python3
"""
wx_video_dl.py — 微信视频号批量下载 CLI

适用工具：wx_video_download_safe (ltaoo/wx_channels_download 的 _safe 构建)。
本脚本依托该工具内置的本地 API (127.0.0.1:2022) 完成批量下载。

支持输入格式：
  - video feed id       : 14955143242446412170
  - video share link    : https://channels.weixin.qq.com/web/pages/feed?feed_id=14955143242446412170
                          https://finder.video.qq.com/251/20302/stodownload?encfilekey=...&token=...
  - video 号短链 share   : #小程序://视频号/.../14955143242446412170
  - 微信小程序路径        : pages/feed/feed.html?feed_id=14955143242446412170
  - 作者 username       : v2_060000227c00b4e03daaa37a34a752d074338ffea675@finder

子命令：
  list        列出当前 gopeed 任务（默认全部；可 --status 过滤）
  status      查看工具状态（API 是否在线、channels 是否可用、版本号）
  add         将一组 video 标识加入 gopeed 下载队列（id / share link）
  author      输入作者 username，批量拉取其下所有视频并下载
  url         输入一条 finder.video.qq.com URL 直接 curl 下载（绕过 gopeed）
  pull        抓取 /api/task/list 里所有未完成的任务并触发/监控
  watch       持续轮询任务状态，直到全部 done 或失败
  probe       从一段文本里自动识别所有可下载目标（feed id / share link / username）

设计前提：
  - 工具已启动并占用 127.0.0.1:2022
  - 用户的浏览器已登录视频号，且至少访问过一次视频号页面（让工具嗅探到 cookie）
  - 工具默认将视频保存到配置里的 download.dir (config.yaml)，可通过
    --out-dir 改写到其它目录（需目标可写）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

try:
    import requests  # type: ignore
except ImportError:
    sys.stderr.write(
        "缺少 requests 库。请运行:  python -m pip install requests\n"
    )
    sys.exit(2)


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_API_BASE = "http://127.0.0.1:2022"
DEFAULT_DOWNLOAD_DIR = os.path.join(
    os.path.expanduser("~"), "Downloads", "wx_video_dl"
)
DEFAULT_POLL_INTERVAL = 2.5
DEFAULT_DONE_TIMEOUT = 60 * 60  # 1 小时
MAX_CONCURRENT_DOWNLOAD = 3  # 与工具 config.yaml 的 MaxRunning=3 对齐

# 工具本体（wx_channels_download _safe 构建）
# 可通过环境变量覆盖，便于分发：
#   WX_DL_TOOL_EXE / WX_DL_TOOL_ROOT / WX_DL_DL_DIR / WX_DL_TEMPLATE
_TOOL_EXE_ENV = os.environ.get("WX_DL_TOOL_EXE", "").strip()
_TOOL_ROOT_ENV = os.environ.get("WX_DL_TOOL_ROOT", "").strip()
TOOL_EXE = _TOOL_EXE_ENV or os.path.join(TOOL_ROOT, "wx_video_download.exe")
HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_ROOT = _TOOL_ROOT_ENV or os.path.join(HERE, "wx_video_download_safe_v260714_windows_x86_64")
TOOL_CONFIG = os.path.join(TOOL_ROOT, "config.yaml")

# 下载目录与文件名模板（与工具 config.yaml 对齐，可被环境变量覆盖）
PREFERRED_DL_DIR = os.environ.get("WX_DL_DL_DIR", "").strip() or DEFAULT_DOWNLOAD_DIR
PREFERRED_TEMPLATE = os.environ.get("WX_DL_TEMPLATE", "").strip() or "{{author}}_{{download_at}}_{{filename}}_{{spec}}"

# 常见视频号 feed id、finder URL、share link 的识别正则。
# 视频号 feed id 是 1 开头的长整数，长度不是固定的（常见 18-22 位）。
RE_FEED_ID = re.compile(r"(?<!\d)(1\d{16,22})(?!\d)")
RE_SHARE_LINK_SHORT = re.compile(r"#小程序[:：]视频号/\S+?/(\d{16,22})")
RE_FEED_PAGE = re.compile(r"/web/pages/(?:feed|video)/[^?]*\?feed_id=(\d{16,22})")
RE_FINDER_URL = re.compile(
    r"https?://finder\.video\.qq\.com/\S+?(?=&token=|&X-snsvideoflag=|$)"
)
RE_USERNAME = re.compile(r"v2_[\w]+@finder")


# ---------------------------------------------------------------------------
# 工具客户端
# ---------------------------------------------------------------------------


class APIError(RuntimeError):
    """API 返回非 0 code 时抛出。"""

    def __init__(self, code: int, msg: str, payload: dict | None = None):
        super().__init__(f"[code={code}] {msg}")
        self.code = code
        self.msg = msg
        self.payload = payload


class WXChannelsClient:
    """包装 127.0.0.1:2022 上的 wx_video_download API。"""

    def __init__(
        self,
        api_base: str = DEFAULT_API_BASE,
        timeout: float = 8.0,
        session: requests.Session | None = None,
    ):
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    # ---- 低层 ----
    def _get(self, path: str, params: dict | None = None) -> dict:
        url = self.api_base + path
        r = self.session.get(url, params=params or {}, timeout=self.timeout)
        r.raise_for_status()
        return self._unwrap(self._json_or_error(r))

    def _post(self, path: str, json_body: dict | None = None) -> dict:
        url = self.api_base + path
        r = self.session.post(
            url, json=json_body or {}, timeout=self.timeout
        )
        r.raise_for_status()
        return self._unwrap(self._json_or_error(r))

    @staticmethod
    def _unwrap(body: dict) -> dict:
        """API 统一返回 {code, msg, data}，把错码扔异常。"""
        if not isinstance(body, dict):
            raise APIError(-1, "非 JSON 响应", {"raw": body})
        if body.get("code", 0) != 0:
            raise APIError(
                body.get("code", -1), body.get("msg", ""), body
            )
        return body.get("data", {})

    @staticmethod
    def _json_or_error(r) -> dict:
        """把响应体解析成 JSON；非 JSON（如工具返回 HTML 错误页）时转成 APIError。"""
        try:
            return r.json()
        except ValueError:
            raise APIError(
                -1, f"非 JSON 响应 (HTTP {r.status_code})", {"text": r.text[:500]}
            )

    # ---- 高层 ----
    def status(self) -> dict:
        return self._get("/api/status")

    def ping(self) -> bool:
        """工具 API 是否存活。"""
        try:
            self.status()
            return True
        except Exception:
            return False

    def channels_available(self) -> bool:
        """探测视频号 WS 通道是否可用。

        ⚠️ 工具源码 handleStatus 把 channels.available 永远写死为 false
        （routes.go 里 available 初始 false 且只有 err!=nil 时才再置 false），
        所以不能信 /api/status 的 available 字段。真实判定是调一个需要
        WS 通道的接口（contact/search 或 follow/list），能通即可用。
        """
        try:
            self.contact_search("a", limit=1)
            return True
        except APIError:
            return False
        except Exception:
            return False

    def contact_search(self, keyword: str, limit: int = 10) -> list[dict]:
        """GET /api/channels/contact/search：作者搜索（WS 通道可用时成功）。"""
        data = self._get(
            "/api/channels/contact/search", {"keyword": keyword}
        )
        info = (data.get("infoList") or [])[:limit]
        return info

    def task_list(self, status: str | None = None, page: int = 1) -> dict:
        params: dict[str, Any] = {"page": page}
        if status:
            params["status"] = status
        return self._get("/api/task/list", params=params)

    def iter_all_tasks(self, statuses: Iterable[str]) -> list[dict]:
        """按 status 一次性返回每个列表后合并。"""
        out: list[dict] = []
        for s in statuses:
            data = self.task_list(status=s)
            out.extend(data.get("list", []))
        return out

    def task_create(
        self,
        feed_id: str,
        filename: str | None = None,
        spec: str | None = None,
    ) -> dict:
        """POST /api/task/create（FeedDownloadTaskBody）。

        源码字段：id / nonce_id / url / title / filename / key / spec /
        suffix / overwrite / duplicate。id 必填；url 为空时后端拿不到
        真实视频地址会 500（unsupported protocol）。因此此接口通常
        需要前端注入脚本给出 url+key；纯脚本场景优先用 create_channels。
        """
        body: dict[str, Any] = {"id": feed_id}
        if filename:
            body["filename"] = filename
        if spec:
            body["spec"] = spec
        return self._post("/api/task/create", body)

    def task_create_channels(
        self,
        *,
        oid: str | None = None,
        nid: str | None = None,
        url: str | None = None,
        eid: str | None = None,
        spec: str | None = None,
        mp3: bool = False,
        cover: bool = False,
    ) -> dict:
        """POST /api/task/create_channels（ChannelsDownloadPayload）。

        只需 oid / nid / url / eid 之一，后端自己调视频号接口拉详情
        （含真实 finder URL + 解密 key），自动创建 + 解密下载。
        这是纯脚本批量下载的正确入口（需要 channels.available:true）。
        """
        body: dict[str, Any] = {
            "oid": oid or "",
            "nid": nid or "",
            "eid": eid or "",
            "url": url or "",
            "spec": spec or "",
            "mp3": mp3,
            "cover": cover,
        }
        return self._post("/api/task/create_channels", body)

    def task_create_batch(
        self, feeds: list[dict]
    ) -> dict:
        """POST /api/task/create_batch：批量创建（后端按 id|spec|suffix 去重）。

        feeds 每项为 FeedDownloadTaskBody 字段。
        """
        return self._post("/api/task/create_batch", {"feeds": feeds})

    def task_action(self, action: str, task_id: str | None = None,
                    delete_files: bool = False) -> dict:
        """POST /api/task/{action}：start / pause / resume / delete /
        start_all / pause_all / clear。"""
        body: dict[str, Any] = {}
        if task_id:
            body["id"] = task_id
        if action == "delete":
            body["delete_files"] = delete_files
        return self._post(f"/api/task/{action}", body)

    def task_profile(self, task_id: str) -> dict:
        """GET /api/task/profile?id=... 单任务详情。"""
        return self._get("/api/task/profile", {"id": task_id})

    def contact_feed_list(
        self, username: str, next_marker: str = ""
    ) -> dict:
        """GET /api/channels/contact/feed/list（作者视频列表，翻页）。"""
        params: dict[str, str] = {"username": username}
        if next_marker:
            params["next_marker"] = next_marker
        return self._get("/api/channels/contact/feed/list", params)

    def feed_profile(
        self, oid: str = "", nid: str = "", url: str = "", eid: str = ""
    ) -> dict:
        """GET /api/channels/feed/profile（单视频详情）。"""
        params = {"oid": oid, "nid": nid, "url": url, "eid": eid}
        return self._get("/api/channels/feed/profile", params)

    def shared_feed_profile(self, url: str) -> dict:
        """GET /api/channels/shared_feed/profile?url= 分享链接解析。"""
        return self._get("/api/channels/shared_feed/profile", {"url": url})

    def parse_sph(self, url: str) -> dict:
        """GET /api/channels/parse_sph?url= 腾讯元宝 API 分享链接解析
        （需要 config.yaml 配 cloudflare.sphCookie）。"""
        return self._get("/api/channels/parse_sph", {"url": url})

    def search_author(self, keyword: str, limit: int = 10) -> list[dict]:
        data = self._get(
            "/api/channels/contact/search", {"keyword": keyword}
        )
        info = (data.get("infoList") or [])[:limit]
        return info

    def rss_author(self, username: str, count: int = 20) -> str:
        """返回一段 RSS XML 字符串。"""
        r = self.session.get(
            self.api_base + "/rss/channels",
            params={"username": username, "count": count},
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.text


# ---------------------------------------------------------------------------
# 工具本体生命周期（自动启动 / 配置体检 / WS 等待）
# ---------------------------------------------------------------------------


def ensure_tool_running(timeout: float = 30.0) -> bool:
    """确保 wx_video_download.exe 已启动且 API 可用。

    若 2022 端口未监听，则自动拉起工具（不弹黑窗口，等待端口就绪）。
    返回 True=API 可用。
    """
    # 1) 已在线
    try:
        r = requests.get(DEFAULT_API_BASE + "/api/status", timeout=2)
        if r.status_code == 200:
            return True
    except Exception:
        pass

    # 2) 自动启动
    if not os.path.exists(TOOL_EXE):
        sys.stderr.write(
            f"[工具] 找不到 exe：{TOOL_EXE}\n"
            f"       请确认 wx_video_download.exe 已解压到该路径，\n"
            f"       或修改脚本顶部 TOOL_EXE / TOOL_ROOT 常量指向你的工具目录。\n"
            f"       工具是开源项目（https://github.com/ltaoo/wx_channels_download），\n"
            f"       可在 Releases 下载官方构建包。\n"
        )
        return False
    sys.stderr.write("[工具] 未运行，正在自动启动 wx_video_download.exe ...\n")
    try:
        DETACHED_PROCESS = 0x00000008  # CREATE_NO_WINDOW
        subprocess.Popen(
            [TOOL_EXE],
            cwd=TOOL_ROOT,
            creationflags=DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        sys.stderr.write(f"[工具] 启动失败：{exc}\n")
        return False

    # 3) 等端口
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = requests.get(DEFAULT_API_BASE + "/api/status", timeout=2)
            if r.status_code == 200:
                sys.stderr.write("[工具] 已就绪\n")
                return True
        except Exception:
            pass
        time.sleep(1)
    sys.stderr.write(f"[工具] 等待 API 就绪超时（{timeout}s）\n")
    return False


def check_config() -> list[str]:
    """体检 config.yaml 是否已按用户偏好配置。

    返回警告列表；空列表 = 配置 OK。
    """
    warns: list[str] = []
    try:
        with open(TOOL_CONFIG, "r", encoding="utf-8") as fp:
            text = fp.read()
    except OSError as exc:
        warns.append(f"读不到 config.yaml：{exc}")
        return warns
    # 解析 download: 块
    m = re.search(r"download:\s*\n((?:[ \t]+.*\n)+)", text)
    if m:
        block = m.group(1)
        if f'dir: "{PREFERRED_DL_DIR}"' not in block.replace("\\\\", "\\") and \
           f"dir: {PREFERRED_DL_DIR!r}" not in block:
            warns.append(
                f"download.dir 不是 {PREFERRED_DL_DIR}，请修改 config.yaml 后重启工具"
            )
        if PREFERRED_TEMPLATE not in block:
            warns.append(
                "download.filenameTemplate 未包含作者+日期模板"
                f"（期望 {PREFERRED_TEMPLATE}），请修改后重启工具"
            )
    else:
        warns.append("config.yaml 里没有 download 块")
    return warns


def wait_channels_available(
    timeout: float = 300.0, poll: float = 3.0
) -> bool:
    """等待视频号 WS 通道就绪（依赖用户在微信视频号打开过视频）。

    返回 True=可用。超时给出可操作提示（这是唯一需要用户手动的步骤）。
    """
    client = WXChannelsClient()
    if client.channels_available():
        return True
    sys.stderr.write(
        "[通道] 视频号通道未就绪。请在【微信 PC 版 → 视频号】点开任意一个视频，\n"
        "        看到下载按钮后本脚本会自动继续……（最长等待 "
        f"{int(timeout)}s）\n"
    )
    t0 = time.time()
    while time.time() - t0 < timeout:
        if client.channels_available():
            sys.stderr.write("[通道] 已就绪\n")
            return True
        time.sleep(poll)
    sys.stderr.write(
        "[通道] 等待超时。请确认：① 工具已启动 ② 微信视频号已点开视频看到下载按钮\n"
    )
    return False


# ---------------------------------------------------------------------------
# 输入识别与解析
# ---------------------------------------------------------------------------


@dataclass
class Target:
    """一个待下载的视频目标。

    kind:
      - feed_id : 视频号 video id（19 位整数）
      - url     : finder.video.qq.com/... 完整 URL
      - author  : 视频号作者 username，仅作为"展开"入口
    """

    kind: str  # feed_id | url | author
    value: str
    hint: str = ""  # 原始文本，便于排错


def detect_feed_id(text: str) -> str | None:
    m = RE_FEED_ID.search(text)
    if m:
        return m.group(1)
    m = RE_FEED_PAGE.search(text)
    if m:
        return m.group(1)
    m = RE_SHARE_LINK_SHORT.search(text)
    if m:
        return m.group(1)
    return None


def detect_finder_url(text: str) -> str | None:
    m = RE_FINDER_URL.search(text)
    if m:
        return m.group(0)
    # 也兼容 user 把 token/... 后的 URL 用空格断开
    if "finder.video.qq.com" in text:
        # 从字符串里截取 URL 部分
        start = text.find("https://finder.video.qq.com")
        if start == -1:
            start = text.find("http://finder.video.qq.com")
        if start != -1:
            return text[start:].split()[0]
    return None


def detect_username(text: str) -> str | None:
    m = RE_USERNAME.search(text)
    if m:
        return m.group(0)
    return None


def parse_targets(text_or_lines: str | Iterable[str]) -> list[Target]:
    """从一段文本里抽取所有可下载目标。

    规则顺序：
      1. finder URL → url
      2. feed id → feed_id
      3. username → author
    同一条文本里多种都能识别，都返回。
    """
    if isinstance(text_or_lines, str):
        lines = text_or_lines.splitlines()
    else:
        lines = list(text_or_lines)

    targets: list[Target] = []
    seen: set[tuple[str, str]] = set()

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        for fn, kind in (
            (detect_finder_url, "url"),
            (detect_feed_id, "feed_id"),
            (detect_username, "author"),
        ):
            hit = fn(line)
            if hit and (kind, hit) not in seen:
                seen.add((kind, hit))
                targets.append(Target(kind=kind, value=hit, hint=raw))
    return targets


def sanitize_filename(name: str, default: str = "video.mp4") -> str:
    """Windows 文件名清洗。"""
    bad = '<>:"/\\|?*\x00'
    cleaned = "".join("_" if c in bad else c for c in name)
    cleaned = cleaned.strip().rstrip(".") or default
    if len(cleaned) > 200:
        cleaned = cleaned[:200]
    if not cleaned.lower().endswith(".mp4"):
        cleaned += ".mp4"
    return cleaned


# ---------------------------------------------------------------------------
# 直接下载（绕开 gopeed，单纯用 curl/aria2）
# ---------------------------------------------------------------------------


DOWNLOAD_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def direct_download(
    url: str,
    out_dir: str,
    filename: str | None = None,
    max_size: int | None = None,
) -> Path:
    """直接用 curl/aria2/requests 下载一段 URL 到本地。

    优先用 aria2c（更快、支持多线程），回退到 requests 流式下载。
    finder.video.qq.com 对 User-Agent 有要求，强制带上 Chrome UA。
    """
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    if not filename:
        filename = "video_" + str(int(time.time())) + ".mp4"
    filename = sanitize_filename(filename)
    out_path = Path(out_dir) / filename

    # 1) aria2c
    if _which("aria2c"):
        cmd = [
            "aria2c",
            "--quiet=true",
            "--console-log-level=warn",
            f"--user-agent={DOWNLOAD_UA}",
            "--max-connection-per-server=4",
            "--split=4",
            "-d",
            str(out_dir),
            "-o",
            filename,
            url,
        ]
        if max_size:
            cmd[2:2] = [f"--max-file-size={max_size}"]
        r = subprocess.run(cmd, check=False)
        if r.returncode == 0 and out_path.exists():
            return out_path

    # 2) requests 流式
    headers = {"User-Agent": DOWNLOAD_UA, "Referer": "https://channels.weixin.qq.com"}
    try:
        with requests.get(
            url, stream=True, timeout=60, headers=headers
        ) as resp:
            resp.raise_for_status()
            with open(out_path, "wb") as fp:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        fp.write(chunk)
        return out_path
    except Exception:
        if out_path.exists():
            out_path.unlink(missing_ok=True)
        raise

    # 3) curl CLI 兜底
    cmd = [
        "curl",
        "-L",
        "-s",
        "-A",
        DOWNLOAD_UA,
        "-o",
        str(out_path),
        url,
    ]
    subprocess.run(cmd, check=False)
    if out_path.exists():
        return out_path
    raise RuntimeError(f"下载失败：{url}")


def _which(cmd: str) -> str | None:
    from shutil import which

    return which(cmd)


# ---------------------------------------------------------------------------
# 高层动作：作者展开、批量提交、轮询
# ---------------------------------------------------------------------------


def expand_author(
    client: WXChannelsClient,
    username: str,
    limit: int = 20,
    since_ts: int | None = None,
) -> list[str]:
    """展开作者维度的入口，返回该作者的 feed id 列表。

    优先用 `/api/channels/contact/feed/list`（翻页 lastBuffer 递归），
    失败回退 RSS（需要 channels.available），再失败给用户提示。

    since_ts：只保留 createtime >= since_ts 的视频（秒时间戳）。
    """
    feed_ids: list[str] = []

    # 1) contact/feed/list 翻页（权威路径，含 createtime 可过滤）
    try:
        marker = ""
        skipped = 0
        while True:
            data = client.contact_feed_list(username, marker)
            # contact_feed_list 经 _unwrap 后返回 {errCode, errMsg, data, payload}
            # object 数组在 data.data.object
            try:
                obj = (data.get("data") or {}).get("object") or []
            except (KeyError, TypeError):
                obj = []
            for item in obj:
                fid = (item or {}).get("id")
                if not fid:
                    continue
                if since_ts is not None:
                    ct = (item or {}).get("createtime", 0) or 0
                    if int(ct) < since_ts:
                        skipped += 1
                        continue
                feed_ids.append(str(fid))
            inner = (data.get("data") or {})
            last_buffer = inner.get("lastBuffer", "") if isinstance(inner, dict) else ""
            cont = inner.get("continueFlag", 0) if isinstance(inner, dict) else 0
            if not cont or not last_buffer or len(feed_ids) >= limit:
                break
            marker = last_buffer
        if since_ts:
            sys.stderr.write(
                f"[作者] 日期过滤：跳过 {skipped} 个更早的视频\n"
            )
        if feed_ids:
            return list(dict.fromkeys(feed_ids))[:limit]
    except Exception:
        pass

    # 2) RSS 回退（RSS 无时间信息，只能全量；不支持 since_ts 精确过滤）
    try:
        xml = client.rss_author(username, count=limit)
        for m in RE_FEED_PAGE.finditer(xml):
            feed_ids.append(m.group(1))
        for m in RE_FEED_ID.finditer(xml):
            feed_ids.append(m.group(1))
        if feed_ids:
            return list(dict.fromkeys(feed_ids))[:limit]
    except Exception:
        pass

    # 3) 只拿作者元数据，给用户提示
    info = client.search_author(username.split("@")[0], limit=3)
    if info:
        sys.stderr.write(
            f"[hint] 拿到作者元数据但未拿到视频列表（feed/list + RSS 都失败，"
            f"channels 可能未激活）。\n"
            f"       请在浏览器打开一次 https://channels.weixin.qq.com 并访问该作者主页，\n"
            f"       再重试。\n"
        )
    return feed_ids


def submit_tasks(
    client: WXChannelsClient,
    feed_ids: Iterable[str],
    prefix: str = "wx",
    spec: str | None = None,
) -> list[dict]:
    """逐个提交下载任务并收集结果。

    优先走 POST /api/task/create_channels（后端自解析 oid，自动解密）；
    失败（如 500/JSAPI 解析失败）回退 POST /api/task/create（带 url
    字段，需要前端注入脚本已经给出 url）。
    """
    feed_ids = list(dict.fromkeys(feed_ids))
    results: list[dict] = []
    for fid in feed_ids:
        filename = f"{prefix}_{fid}_{spec or 'auto'}.mp4"
        # 优先 create_channels（后端拿 oid 自己解析 url+key）
        try:
            res = client.task_create_channels(oid=fid, spec=spec or "")
            results.append(
                {
                    "id": fid,
                    "status": "submitted",
                    "name": filename,
                    "response": res,
                    "via": "create_channels",
                }
            )
            continue
        except APIError as exc:
            if exc.code not in (409,):
                # 非重复错误：尝试回退 create（需要已有 url，多半没有）
                # 记录 fallback 结果但继续
                results.append(
                    {
                        "id": fid,
                        "status": "error",
                        "code": exc.code,
                        "msg": exc.msg,
                        "via": "create_channels",
                    }
                )
                continue
            # 409 = 已存在，记录即可
            results.append(
                {
                    "id": fid,
                    "status": "dup",
                    "code": 409,
                    "msg": "已存在该下载内容",
                    "via": "create_channels",
                }
            )
            continue

        # 回退：task/create（不带 url 会 500，仅当工具给了 url 时才有效）
        try:
            res = client.task_create(fid, filename=filename, spec=spec)
            results.append(
                {
                    "id": fid,
                    "status": "submitted",
                    "name": filename,
                    "response": res,
                    "via": "create",
                }
            )
        except APIError as exc:
            results.append(
                {
                    "id": fid,
                    "status": "error",
                    "code": exc.code,
                    "msg": exc.msg,
                    "via": "create",
                }
            )
    return results


def filter_done_or_err(tasks: list[dict]) -> tuple[list[dict], list[dict], int]:
    done, error, ready = [], [], 0
    for t in tasks:
        s = t.get("status")
        if s == "done":
            done.append(t)
        elif s == "error":
            error.append(t)
        elif s in {"ready", "running", "wait"}:
            ready += 1
    return done, error, ready


def watch_until_done(
    client: WXChannelsClient,
    *,
    poll: float = DEFAULT_POLL_INTERVAL,
    timeout: float = DEFAULT_DONE_TIMEOUT,
) -> dict:
    """持续轮询所有任务直到总数 done + error = total。"""
    t0 = time.time()
    last_total = -1
    while time.time() - t0 < timeout:
        data = client.task_list()
        cnt = data.get("status_counts", {})
        total = cnt.get("total", 0)
        completed = cnt.get("done", 0) + cnt.get("error", 0)
        ready = cnt.get("ready", 0) + cnt.get("running", 0) + cnt.get("wait", 0)
        if total > 0:
            yield_stream = (
                f"[watch] done={cnt.get('done', 0)} "
                f"err={cnt.get('error', 0)} "
                f"running={cnt.get('running', 0)}/{MAX_CONCURRENT_DOWNLOAD} "
                f"wait={cnt.get('wait', 0)}  "
                f"total={total}  ({completed}/{total} settled)"
            )
        else:
            yield_stream = "[watch] 任务列表为空"
        if total != last_total:
            sys.stderr.write("\n" + yield_stream + "\n")
            last_total = total
        else:
            sys.stderr.write("\r" + yield_stream + "    ")
            sys.stderr.flush()
        if total == 0 or completed >= total and ready == 0:
            return data
        time.sleep(poll)
    raise TimeoutError(
        f"等待任务完成超时（>{int(timeout)}s）。仍在等待：{ready}。"
    )


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------


def cmd_status(args, client: WXChannelsClient):
    st = client.status()
    # 源码 handleStatus 把 channels.available 永远写死 false，
    # 真实可用性用 WS 探测接口判定。
    st["channels"]["available"] = client.channels_available()
    st["channels"]["note"] = (
        "工具源码 handleStatus 的 available 恒为 false，"
        "此值由 contact/search 实际探测得出"
    )
    print(json.dumps(st, indent=2, ensure_ascii=False))


def cmd_list(args, client: WXChannelsClient):
    statuses = [args.status] if args.status else [
        "ready",
        "running",
        "wait",
        "done",
        "error",
        "pause",
    ]
    tasks = client.iter_all_tasks(statuses)
    if args.summary:
        done, err, ready = filter_done_or_err(tasks)
        print(
            json.dumps(
                {
                    "ready": ready,
                    "done": len(done),
                    "error": len(err),
                    "pause": sum(1 for t in tasks if t.get("status") == "pause"),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return
    for t in tasks:
        meta = t.get("meta", {}) or {}
        req = meta.get("req", {}) or {}
        labels = meta.get("labels", {}) or {}
        print(
            f"{t.get('status'):8s} | "
            f"{(t.get('name') or ''):60.60s} | "
            f"id={t.get('id')} | "
            f"fid={labels.get('id', '')} | "
            f"spec={labels.get('spec', '')} | "
            f"size={t.get('progress', {}).get('downloaded', 0)}/{(meta.get('res') or {}).get('size', 0)}"
        )
        if args.verbose:
            print(f"   url: {req.get('url', '')[:160]}")


def cmd_add(args, client: WXChannelsClient):
    items = list(args.items)
    feed_ids: list[str] = []
    authors: list[str] = []
    for it in items:
        if RE_USERNAME.fullmatch(it):
            authors.append(it)
        elif "/sph/" in it or re.fullmatch(r"[A-Za-z0-9_-]{8,16}", it.strip()):
            # sph 短链/短码 = 单个视频，直接解析出 feed_id 单条提交
            try:
                info = resolve_sph(client, it)
                print(
                    f"  [sph] 解析成功：{info['nickname']}《{info['title'][:30]}》→ 单条"
                )
                feed_ids.append(info["feed_id"])
            except APIError as exc:
                print(f"  ✗ sph 解析失败：{exc.msg}")
        else:
            for t in parse_targets(it):
                if t.kind == "feed_id":
                    feed_ids.append(t.value)
                elif t.kind == "url":
                    feed_ids.append("URL:" + t.value)
                elif t.kind == "author":
                    authors.append(t.value)

    # 展开作者
    for au in authors:
        feed_ids.extend(expand_author(client, au, limit=args.max_per_author))

    final_ids = [x for x in feed_ids if not x.startswith("URL:")]
    if feed_ids and any(x.startswith("URL:") for x in feed_ids):
        urls = [x[4:] for x in feed_ids if x.startswith("URL:")]
        sys.stderr.write(
            "提示：列表里出现 finder URL，已自动改走 'url' 子命令提交下载。\n"
        )
        for u in urls:
            direct_download(u, args.out_dir, filename=None)

    if final_ids:
        results = submit_tasks(
            client, final_ids, prefix=args.prefix, spec=args.spec
        )
        for r in results:
            print(
                f"  {r['status']:9s} fid={r['id']}  msg={r.get('msg', '')}{('→ '+r['name']) if r['status']=='submitted' else ''}"
            )
    else:
        print("无可用 feed id（也没有 finder URL）。")


def cmd_author(args, client: WXChannelsClient):
    fids = expand_author(
        client, args.username,
        limit=args.max_per_author,
        since_ts=parse_since(args.since),
    )
    if not fids:
        sys.exit(
            "未拉取到视频，请先在浏览器打开视频号对应作者主页后再试。"
        )
    print(f"识别到 {len(fids)} 个视频（{args.since or '不限'} 之后）：{', '.join(fids[:8])}{'...' if len(fids)>8 else ''}")
    if not args.yes:
        ans = input("确认全部加入下载？[Y/n] ")
        if ans.strip().lower() not in ("", "y", "yes"):
            print("已取消。")
            return
    results = submit_tasks(
        client, fids, prefix=args.prefix, spec=args.spec
    )
    for r in results:
        print(f"  {r['status']:9s} fid={r['id']}  msg={r.get('msg', '')}")


def cmd_share(args, client: WXChannelsClient):
    """用分享链接解析视频详情，然后直接创建下载任务。

    分享链接示例：
      - https://channels.weixin.qq.com/web/pages/feed?feed_id=...
      - https://findermp.video.qq.com/...?...
      - 微信里转发的 #小程序://视频号/.../<id>
    后端会尝试 shared_feed/profile 与 feed/profile（带 eid/url）。
    """
    targets = parse_targets(args.url) or []
    if not targets:
        sys.exit(f"无法从输入识别出视频目标：{args.url}")
    for t in targets:
        print(f"  识别到 {t.kind}: {t.value}")
    # 尝试用后端解析：先 shared_feed/profile（需要 cookie），
    # 再尝试 create_channels（直接给 url，后端自己解析）
    try:
        resp = client.shared_feed_profile(args.url)
        obj = (
            resp.get("data", {})
            .get("data", {})
            .get("object", {})
        )
        fid = (obj or {}).get("id")
        if fid:
            print(f"  shared_feed/profile → feed id {fid}")
            return submit_and_print(client, [str(fid)], args)
    except APIError as exc:
        print(f"  [hint] shared_feed/profile 失败：{exc.msg}")
    # 直接交给 create_channels 让后端解析 URL
    try:
        res = client.task_create_channels(url=args.url)
        print(f"  create_channels: submitted id={res.get('id')}")
        return
    except APIError as exc:
        print(f"  create_channels 失败：{exc.msg}")
        sys.exit(1)


def submit_and_print(client, feed_ids, args):
    results = submit_tasks(
        client, feed_ids, prefix=args.prefix, spec=args.spec
    )
    for r in results:
        print(
            f"  {r['status']:9s} fid={r['id']}  via={r.get('via','')}  "
            f"msg={r.get('msg', '')}{('→ '+r['name']) if r['status']=='submitted' else ''}"
        )
    return results


def cmd_task(args, client: WXChannelsClient):
    """start / pause / resume / delete / clear 控制 gopeed 任务。"""
    action = args.action
    if action == "start_all":
        res = client.task_action("start_all")
        print(f"start_all ok: {res}")
        return
    if action == "pause_all":
        try:
            res = client.task_action("pause_all")
            print(f"pause_all ok: {res}")
        except APIError as exc:
            if "task not found" in exc.msg or exc.code == 500:
                print("pause_all: 没有正在运行的任务，无需暂停")
            else:
                print(f"pause_all 失败: {exc.msg}")
        return
    if action == "clear":
        res = client.task_action("clear")
        print(f"clear ok: {res}")
        return
    task_id = args.id
    if not task_id:
        sys.exit(f"{action} 需要一个任务 id（--id <task_id>）")
    try:
        res = client.task_action(action, task_id, delete_files=args.delete_files)
        print(f"{action} ok: {res}")
    except APIError as exc:
        sys.exit(f"{action} 失败: {exc.msg} (code={exc.code})")


def cmd_follow(args, client: WXChannelsClient):
    """列出关注的作者/内容（GET /api/channels/follow/list）。"""
    resp = client._get("/api/channels/follow/list")
    print(json.dumps(resp, indent=2, ensure_ascii=False)[:4000])


def cmd_url(args, client: WXChannelsClient):
    """直接下载 finder URL（绕过 gopeed 内核）。

    ⚠️ 注意：视频号视频文件是加密的（XOR + key）。从 URL 下载下来的 .mp4
    无法直接播放，必须借助工具内置的 WASM 解密（`__wx_channels_decrypt`）。
    想看能播放的视频请用 `add` 子命令提交任务到 gopeed，让它自动解密。
    这个 `url` 子命令主要用于：
      - 备份/导出原始加密片（事后可离线解密）
      - 调试下载链路
      - 网络可达性 / CDN 速度验证
    """
    url = args.url
    if not url and args.url_file:
        with open(args.url_file, "r", encoding="utf-8") as fp:
            url = fp.read().strip()
    if not url:
        url = sys.stdin.read().strip()
    if not url:
        sys.exit("需要 url 参数（或通过 stdin / --url-file 传入）")
    p = direct_download(
        url, args.out_dir, filename=args.filename
    )
    print(f"已下载到：{p}")
    sys.stderr.write(
        "[warn] 下载的是加密 mp4，需要工具的 WASM 解密步骤才能播放。\n"
        "       想要直接可播放文件请用 add 子命令提交到 gopeed。\n"
    )


def cmd_pull(args, client: WXChannelsClient):
    """从 task/list 抓所有未完成任务的 url，参考 curl 直下。"""
    tasks = client.iter_all_tasks(["ready", "running", "wait", "error"])
    if not tasks:
        print("没有未完成的任务。")
        return
    if args.dry_run:
        for t in tasks:
            print(f"  {t.get('status'):8s} {t.get('name')}")
        return
    for t in tasks:
        url = (t.get("meta", {}) or {}).get("req", {}).get("url", "")
        name = t.get("name") or "video.mp4"
        if not url:
            print(f"  skip {name}: url 为空")
            continue
        try:
            p = direct_download(url, args.out_dir, filename=name)
            print(f"  ok {name} → {p}")
        except Exception as exc:
            print(f"  err {name}: {exc}")


def cmd_watch(args, client: WXChannelsClient):
    final = watch_until_done(client, poll=args.poll, timeout=args.timeout)
    print()
    print(json.dumps(final.get("status_counts", {}), indent=2, ensure_ascii=False))


def parse_since(since: str | None) -> int | None:
    """把 '2026-06-30' 转成当天 0 点的秒时间戳。"""
    if not since:
        return None
    import datetime as _dt
    try:
        dt = _dt.datetime.strptime(since.strip(), "%Y-%m-%d")
        return int(dt.timestamp())
    except ValueError:
        sys.exit(f"--since 格式应为 YYYY-MM-DD，收到：{since}")


def resolve_sph(client: WXChannelsClient, url_or_shortcode: str) -> dict:
    """解析 weixin.qq.com/sph/<code> 短链 → 视频详情（含作者 username）。

    短码即视频的 eid/exportId，直接喂给 feed/profile 解析；
    也兼容完整 URL（自动提取短码）。
    返回 {feed_id, username, nickname, title}；失败抛 APIError。
    """
    code = url_or_shortcode.strip()
    # 从 URL 里提取短码
    m = re.search(r"/sph/([A-Za-z0-9_-]+)", code)
    if m:
        code = m.group(1)
    resp = client.feed_profile(eid=code)
    # feed/profile 返回 {errCode, errMsg, data:{BaseResponse, object, ...}, payload}
    # （_unwrap 已剥掉 {code,msg,data} 外包装，resp 即透传层）
    inner = resp.get("data", {}) if isinstance(resp, dict) else {}
    obj = inner.get("object", {}) or {}
    fid = obj.get("id")
    if not fid:
        raise APIError(-1, f"未解析到 feed id（eid={code}）", resp)
    contact = obj.get("contact", {}) or {}
    return {
        "feed_id": str(fid),
        "username": contact.get("username", ""),
        "nickname": contact.get("nickname", ""),
        "title": (obj.get("objectDesc", {}) or {}).get("description", ""),
    }


def cmd_go(args, client: WXChannelsClient):
    """全自动：启动工具 → 体检配置 → 等视频号通道 → 提交 → 等待 → 整理命名。

    这是给 WorkBuddy skill 用的主入口。唯一需要用户手动的步骤是
    「微信视频号点开一个视频」——脚本会等待并提示。
    """
    print("== 1/5 启动工具 ==")
    if not ensure_tool_running():
        sys.exit("工具启动失败，请手动打开 wx_video_download.exe 后重试")
    # 复用 main() 传入的 client（已按 --api 配置），不要自建默认 localhost 的

    print("== 2/5 检查配置 ==")
    warns = check_config()
    for w in warns:
        print(f"  ⚠ {w}")
    if warns:
        sys.stderr.write(
            "  → 配置未生效，新下载会按旧规则命名/落盘。\n"
            "    修改后需重启工具。是否继续？(y/n) "
        )
        if input().strip().lower() not in ("", "y", "yes"):
            sys.exit("已取消")
        sys.stderr.write("  → 继续执行（本次按旧配置）。\n")

    print("== 3/5 等待视频号通道 ==")
    if not wait_channels_available(timeout=args.wait_channel):
        sys.exit("视频号通道未就绪，请在微信视频号点开一个视频后重试")

    print("== 4/5 提交任务 ==")
    items = list(args.items)
    feed_ids: list[str] = []
    authors: list[str] = []
    for it in items:
        if RE_USERNAME.fullmatch(it):
            authors.append(it)
        elif "/sph/" in it or re.fullmatch(r"[A-Za-z0-9_-]{8,16}", it.strip()):
            # weixin.qq.com/sph/<code> 短链 = 单个视频
            #   默认：只下这一个视频（resolve_sph 拿到 feed_id 直接提交）
            #   --all：按作者批量（解析出作者后展开其全部视频）
            try:
                info = resolve_sph(client, it)
                print(
                    f"  [sph] 解析成功：{info['nickname']}《{info['title'][:30]}》"
                )
                if args.all and info["username"]:
                    print(f"  [sph] --all：按作者批量（{info['username']}）")
                    if info["username"] not in authors:
                        authors.append(info["username"])
                else:
                    feed_ids.append(info["feed_id"])
            except APIError as exc:
                print(f"  ✗ sph 解析失败：{exc.msg}")
        else:
            for t in parse_targets(it):
                if t.kind == "feed_id":
                    feed_ids.append(t.value)
                elif t.kind == "author":
                    authors.append(t.value)
                elif t.kind == "url":
                    # finder URL 直下会拿到加密 mp4，这里仍走 create_channels
                    # 让后端解析（后端吃 url 参数，可解析分享/feed 页链接）
                    feed_ids.append("URL:" + t.value)
    for au in authors:
        got = expand_author(
            client, au,
            limit=args.max_per_author,
            since_ts=parse_since(args.since),
        )
        print(f"  作者 {au} → {len(got)} 个视频（{args.since or '不限'} 之后）")
        feed_ids.extend(got)
    final_ids = [x for x in feed_ids if not x.startswith("URL:")]
    url_items = [x[4:] for x in feed_ids if x.startswith("URL:")]
    if url_items:
        print(f"  {len(url_items)} 条 URL 走 create_channels 后端解析")
        for u in url_items:
            try:
                res = client.task_create_channels(url=u, spec=args.spec or "")
                print(f"  ✓ {u[:60]}... → {res.get('id', '已提交')}")
            except APIError as exc:
                print(f"  ✗ {u[:60]}... → {exc.msg}")
    if final_ids:
        results = submit_tasks(
            client, final_ids, prefix=args.prefix, spec=args.spec
        )
        ok = [r for r in results if r["status"] == "submitted"]
        dup = [r for r in results if r["status"] == "dup"]
        err = [r for r in results if r["status"] == "error"]
        print(f"  提交 {len(results)}：成功 {len(ok)}，重复 {len(dup)}，失败 {len(err)}")
        for r in err:
            print(f"    ✗ fid={r['id']} {r.get('msg', '')}")
    if not feed_ids:
        sys.exit("没有可提交的目标")

    print("== 5/5 等待下载完成 ==")
    final = watch_until_done(client, poll=args.poll, timeout=args.timeout)
    cnt = final.get("status_counts", {})
    print(f"\n完成：done={cnt.get('done', 0)}  err={cnt.get('error', 0)}")
    if not args.no_organize:
        cmd_organize(args, client)
    print("\n下载文件在：", PREFERRED_DL_DIR if not warns else "(旧目录，见上方警告)")


def cmd_organize(args, client: WXChannelsClient):
    """整理下载目录：把文件名里的 Unix 秒时间戳改成 YYYY-MM-DD。

    工具 filenameTemplate 里的 {{download_at}} 是秒级时间戳（如 1785995513），
    不直观。本命令把下载目录中匹配 `_<10位数字>` 的文件重命名为
    `作者_2026-08-06_标题_spec.mp4` 形式，方便按日期归档总结。
    默认只列出改动计划（--apply 才真正改名）。
    """
    import datetime

    dl_dir = Path(args.dir)
    if not dl_dir.is_dir():
        sys.exit(f"目录不存在：{dl_dir}")
    # 匹配 `作者_1785995513_标题_xWT111.mp4` 里的秒时间戳段
    ts_pat = re.compile(r"^(.+?)_(1\d{9})_(.+)$")
    plan: list[tuple[Path, Path]] = []
    for f in sorted(dl_dir.iterdir()):
        if not f.is_file() or f.suffix.lower() not in (".mp4", ".mp3"):
            continue
        m = ts_pat.match(f.stem)
        if not m:
            continue
        author, ts_str, rest = m.group(1), m.group(2), m.group(3)
        try:
            dt = datetime.datetime.fromtimestamp(int(ts_str))
        except (ValueError, OSError):
            continue
        date_str = dt.strftime("%Y-%m-%d")
        new_name = f"{author}_{date_str}_{rest}{f.suffix}"
        new_path = dl_dir / new_name
        if new_path == f:
            continue
        plan.append((f, new_path))

    if not plan:
        print("未找到需要整理的文件（文件名里没有秒时间戳段）。")
        return
    print(f"发现 {len(plan)} 个可整理文件：")
    for src, dst in plan:
        print(f"  {src.name}\n    → {dst.name}")
    if not args.apply:
        print("\n[预览模式] 加 --apply 才会真正改名。")
        return
    for src, dst in plan:
        try:
            src.rename(dst)
            print(f"  ✓ {src.name} → {dst.name}")
        except OSError as exc:
            print(f"  ✗ {src.name}: {exc}")


def cmd_probe(args, client: WXChannelsClient):
    if args.file:
        with open(args.file, "r", encoding="utf-8") as fp:
            text = fp.read()
    elif args.paste:
        text = args.paste
    else:
        text = sys.stdin.read()
    targets = parse_targets(text)
    if not targets:
        print("未识别到任何目标。")
        return
    for t in targets:
        print(f"  {t.kind:8s} {t.value}    (from: {t.hint})")
    if not args.yes:
        ans = input("确认全部加入下载？[Y/n] ")
        if ans.strip().lower() not in ("", "y", "yes"):
            print("已取消。")
            return
    feed_ids = [t.value for t in targets if t.kind == "feed_id"]
    authors = [t.value for t in targets if t.kind == "author"]
    urls = [t.value for t in targets if t.kind == "url"]
    for u in urls:
        try:
            direct_download(u, args.out_dir, filename=None)
        except Exception as exc:
            print(f"  url 下载失败：{u[:80]}... ({exc})")
    for au in authors:
        feed_ids.extend(expand_author(client, au, limit=args.max_per_author))
    if feed_ids:
        results = submit_tasks(
            client, feed_ids, prefix=args.prefix, spec=args.spec
        )
        for r in results:
            print(f"  {r['status']:9s} fid={r['id']}  msg={r.get('msg', '')}")


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wx_video_dl",
        description="微信视频号批量下载 CLI（依托 wx_video_download_safe）。",
    )
    p.add_argument(
        "--api",
        default=DEFAULT_API_BASE,
        help="工具 API base，默认 http://127.0.0.1:2022",
    )
    p.add_argument(
        "--out-dir",
        default=DEFAULT_DOWNLOAD_DIR,
        help="直接下载（url/pull）的输出目录",
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="查看工具状态")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("list", help="列出当前 gopeed 任务")
    s.add_argument("--status", help="按状态过滤（ready/running/done/error/pause/wait）")
    s.add_argument("--summary", action="store_true", help="只输出汇总")
    s.add_argument("--verbose", action="store_true", help="附带打印 URL")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser(
        "add", help="提交一组 feed id / share link 加入下载队列"
    )
    s.add_argument(
        "items",
        nargs="+",
        help="feed id、视频号分享链接、小程序路径、author username（多个）",
    )
    s.add_argument("--prefix", default="wx", help="文件名前缀")
    s.add_argument("--spec", help="画质（如 xWT111）")
    s.add_argument("--max-per-author", type=int, default=15)
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("author", help="拉取作者主页视频并批量提交")
    s.add_argument("username", help="v2_xxx@finder")
    s.add_argument("--prefix", default="wx")
    s.add_argument("--spec", help="画质（如 xWT111）")
    s.add_argument("--max-per-author", type=int, default=20)
    s.add_argument(
        "--since", help="只下载 YYYY-MM-DD 之后发布的视频"
    )
    s.add_argument("--yes", "-y", action="store_true")
    s.set_defaults(func=cmd_author)

    s = sub.add_parser("url", help="直接下载一条 finder.video.qq.com URL")
    s.add_argument(
        "url",
        nargs="?",
        help="https://finder.video.qq.com/.../stodownload?...（可用 stdin）",
    )
    s.add_argument(
        "--url-file",
        help="把 URL 写到文件再传（绕过 shell 转义）",
    )
    s.add_argument(
        "--filename", help="保存文件名（缺省按 URL 末段+时间戳）"
    )
    s.set_defaults(func=cmd_url)

    s = sub.add_parser(
        "pull",
        help="把 gopeed 里 ready/error 的任务手动由 curl 重下（绕开 gopeed）",
    )
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_pull)

    s = sub.add_parser("watch", help="持续轮询直到全部任务 settled")
    s.add_argument("--poll", type=float, default=DEFAULT_POLL_INTERVAL)
    s.add_argument("--timeout", type=float, default=DEFAULT_DONE_TIMEOUT)
    s.set_defaults(func=cmd_watch)

    s = sub.add_parser(
        "go", help="全自动：启动工具→等通道→提交→等待→整理（skill 主入口）"
    )
    s.add_argument(
        "items",
        nargs="+",
        help="feed id / 分享链接 / author username / finder URL（可混合）",
    )
    s.add_argument("--prefix", default="wx", help="文件名前缀")
    s.add_argument("--spec", help="画质（如 xWT111）")
    s.add_argument("--max-per-author", type=int, default=20)
    s.add_argument(
        "--since", help="只下载 YYYY-MM-DD 之后发布的视频（对作者生效）"
    )
    s.add_argument("--poll", type=float, default=DEFAULT_POLL_INTERVAL)
    s.add_argument("--timeout", type=float, default=DEFAULT_DONE_TIMEOUT)
    s.add_argument(
        "--wait-channel", type=float, default=300,
        help="等待微信视频号通道就绪的最长秒数（默认 300）",
    )
    s.add_argument(
        "--no-organize", action="store_true",
        help="完成后不整理文件名（默认整理）",
    )
    s.add_argument(
        "--all", action="store_true",
        help="sph 短链/视频也按作者批量下载（默认只下该单个视频）",
    )
    s.set_defaults(func=cmd_go)

    s = sub.add_parser(
        "organize",
        help="整理下载目录：秒时间戳文件名 → YYYY-MM-DD 日期",
    )
    s.add_argument(
        "--dir",
        default=PREFERRED_DL_DIR,
        help="扫描目录，默认 ~/Downloads/wx_video_dl（可用 WX_DL_DL_DIR 覆盖）",
    )
    s.add_argument(
        "--apply", action="store_true",
        help="真正改名（缺省为预览模式）",
    )
    s.set_defaults(func=cmd_organize)

    s = sub.add_parser(
        "probe", help="从一段文本里识别并下载所有目标"
    )
    inp = s.add_mutually_exclusive_group()
    inp.add_argument("--paste", help="直接贴一段文本")
    inp.add_argument("--file", help="从文件读")
    inp.add_argument(
        "--stdin",
        action="store_true",
        help="从 stdin 读（与 file/paste 二选一；缺省走 stdin）",
    )
    s.add_argument("--prefix", default="wx")
    s.add_argument("--spec", help="画质")
    s.add_argument("--max-per-author", type=int, default=15)
    s.add_argument("--yes", "-y", action="store_true")
    s.set_defaults(func=cmd_probe)

    s = sub.add_parser(
        "share", help="用视频号分享链接解析并下载（交给后端解析）"
    )
    s.add_argument("url", help="分享链接 / feed URL / finder URL")
    s.add_argument("--prefix", default="wx")
    s.add_argument("--spec", help="画质")
    s.set_defaults(func=cmd_share)

    s = sub.add_parser(
        "task", help="控制 gopeed 任务（start/pause/resume/delete/clear）"
    )
    s.add_argument(
        "action",
        choices=[
            "start", "pause", "resume", "delete",
            "start_all", "pause_all", "clear",
        ],
        help="start_all/pause_all/clear 无需 id",
    )
    s.add_argument("--id", help="任务 id（start/pause/resume/delete 需要）")
    s.add_argument(
        "--delete-files", action="store_true",
        help="delete 时同时删文件",
    )
    s.set_defaults(func=cmd_task)

    s = sub.add_parser(
        "follow", help="列出关注列表（需 channels.available:true）"
    )
    s.set_defaults(func=cmd_follow)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    client = WXChannelsClient(api_base=args.api)
    # 工具未运行时给一个清晰报错而不是栈
    try:
        args.func(args, client)
    except APIError as exc:
        sys.stderr.write(f"\n[API错误] {exc.msg} (code={exc.code})\n")
        if exc.code in (400, 410):
            sys.stderr.write(
                "  → 常见原因：feed id 有误 / 文件名为空 / 当前 downloadEntry 不可用\n"
            )
        if exc.code == 500 and "unsupported protocol" in exc.msg:
            sys.stderr.write(
                "  → 提示：工具后端拿不到真实视频 URL。\n"
                "     请先在浏览器打开视频号对应视频页面（让工具嗅探到登录 cookie）后再试。\n"
            )
        sys.exit(1)
    except requests.exceptions.ConnectionError:
        sys.stderr.write(
            f"\n[连接失败] 无法连到 {args.api}。确认工具已启动并占用 2022 端口。\n"
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
