#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
crawler.py — 配置驱动的多站点研报采集引擎（最小可运行参考实现）

设计目标：**给别的 AI 一个能直接跑、能直接改的骨架**，而不是一个玩具。
核心特性（对应 SKILL.md 的铁律）：
  · 配置驱动：一站一条 JSON，改站不改代码
  · 通道可切：直连 / curl_cffi(TLS 指纹) / 代理，可选 playwright 渲染
  · 幂等：seen_links.json 只在【成功后】记账，中断重跑不重复下载
  · 产物闸门：is_complete_pdf(%%EOF) + is_error_page(含软404) —— 坏东西不落盘
  · 逐站限时：单大站不会拖死全量（--site-timeout）
  · 只读诊断：doctor 子命令离线验 pattern 命中数

依赖（都可选，缺失自动降级）：
  pip install curl_cffi beautifulsoup4 pypdf playwright && playwright install chromium

用法：
  python crawler.py --config sites.example.json doctor
  python crawler.py --config sites.example.json crawl --only "Fed" --limit 3
  python crawler.py --config sites.example.json crawl
  python crawler.py --config sites.example.json status
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

# ---------------------------------------------------------------- 可选依赖
try:
    from curl_cffi import requests as cffi_requests  # type: ignore
except Exception:  # pragma: no cover
    cffi_requests = None

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover
    BeautifulSoup = None

try:
    from pypdf import PdfReader  # type: ignore
except Exception:  # pragma: no cover
    try:
        from PyPDF2 import PdfReader  # type: ignore
    except Exception:  # pragma: no cover
        PdfReader = None

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# ---------------------------------------------------------------- 错误页判据
# ★ 标准 HTTP 状态行
_ERR_TITLE_RE = re.compile(
    r"^\s*(?:[45]\d\d|error|not found|access denied|forbidden|"
    r"just a moment|please wait|attention required|"
    r"security controls triggered|verification required|"
    r"azure waf|vercel security checkpoint)\b",
    re.I,
)
# ★★ 软 404 形态：404error：站点名 —— 无空格 + 小写 + 全角冒号
_SOFT_404_TITLE_RE = re.compile(r"^\s*\d{3}\s*error\s*[:：]", re.I)


def is_error_page(html: str) -> str | None:
    """返回错误页类型；None = 不是错误页。

    ★ 为什么必须单独处理「软 404」：`404error：站点名` 既无空格、又是小写、
      还是全角冒号 —— 标准的状态行正则 `^\\d{3} ` 会漏判，导致错误页入库。
    """
    if not html:
        return "empty"
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    if _SOFT_404_TITLE_RE.match(title):
        return "soft-404"
    if _ERR_TITLE_RE.match(title):
        return "error-page"
    # 登录墙：正文很短且标题提到 log in
    if re.search(r"log\s*in|sign\s*in|登录", title, re.I) and len(html) < 4000:
        return "login-wall"
    return None


def is_complete_pdf(path: Path) -> bool:
    """★★★ 截断判据：有 %PDF- 头 + 尾部 2048 字节能找到 %%EOF。"""
    try:
        size = path.stat().st_size
        if size < 8:
            return False
        with open(path, "rb") as f:
            if not f.read(5).startswith(b"%PDF-"):
                return False
            f.seek(max(0, size - 2048))
            return b"%%EOF" in f.read()
    except OSError:
        return False


def safe_name(name: str, limit: int = 120) -> str:
    """清洗成合法文件名（★ 绝不放 ID 进第二段，见 05-source-onboarding.md）。"""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name[:limit] or "untitled").strip()


# ---------------------------------------------------------------- 取回
class Fetcher:
    """三通道取回：直连 / curl_cffi / 代理。"""

    def __init__(self, site: dict, timeout: int = 30, proxy: str | None = None):
        self.site = site
        self.timeout = timeout
        self.proxy = proxy
        self.use_cffi = bool(site.get("use_cffi"))

    def get(self, url: str) -> bytes:
        # 1) curl_cffi（浏览器 TLS 指纹，过 CF TLS 层）
        if self.use_cffi and cffi_requests is not None:
            try:
                r = cffi_requests.get(url, impersonate="chrome131", timeout=self.timeout)
                if r.status_code < 400 and r.content:
                    return r.content
            except Exception:
                pass
        # 2) 直连 / 代理（urllib）
        req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                   "Accept-Language": "en-US,en;q=0.9"})
        if self.proxy and not self.site.get("no_proxy"):
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": self.proxy, "https": self.proxy}))
        else:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=self.timeout) as resp:
            return resp.read()

    def get_text(self, url: str) -> str:
        return self.get(url).decode("utf-8", "ignore")


# ---------------------------------------------------------------- 站点抓取
class CrawlResult:
    def __init__(self):
        self.links = 0
        self.saved = 0
        self.skipped_seen = 0
        self.rejected = 0          # 被闸门拦下的（错误页 / 截断）
        self.errors: list[str] = []


def _html_hrefs(html: str) -> list[str]:
    return re.findall(r'href\s*=\s*["\']([^"\']+)["\']', html, re.I)


def extract_links(site: dict, html: str, base: str) -> list[str]:
    pattern = site.get("link_pattern")
    if not pattern:
        return []
    raw = re.findall(pattern, html)
    out: list[str] = []
    for item in raw:
        link = item if isinstance(item, str) else (item[0] if item else "")
        if not link:
            continue
        out.append(urljoin(base, link.strip()))
    # 去重保序
    seen, uniq = set(), []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def crawl_site(site: dict, root: Path, seen: set[str], *, limit: int | None = None,
               proxy: str | None = None, timeout: int = 30,
               on_progress=None) -> CrawlResult:
    res = CrawlResult()
    name = site["name"]
    category = site.get("category", "未分类")
    out_dir = root / category / name
    out_dir.mkdir(parents=True, exist_ok=True)

    fetcher = Fetcher(site, timeout=timeout, proxy=proxy)

    # —— 1) 取列表页（支持 list_urls 多页）——
    list_urls = site.get("list_urls") or ([site["list_url"]] if site.get("list_url") else [])
    if not list_urls:
        res.errors.append("配置缺 list_url / list_urls")
        return res

    merged = []
    for lu in list_urls:
        try:
            merged.append(fetcher.get_text(lu))
        except Exception as e:  # noqa: BLE001
            res.errors.append(f"列表页失败 {lu}: {e}")

    if site.get("use_rss"):
        merged = ["".join(merged)]
    html = "\n".join(merged)

    # —— 2) 形态 5：list_url 本身就是 PDF ——
    if site.get("direct_pdf"):
        links = list_urls
    else:
        links = extract_links(site, html, site.get("base_url") or list_urls[0])

    res.links = len(links)
    if on_progress:
        on_progress(f"  {name}: 列表页命中 {len(links)} 条链接")

    pdf_pattern = site.get("pdf_pattern")
    pdf_only = bool(site.get("pdf_only", bool(pdf_pattern)))
    same_host = bool(site.get("pdf_same_host_only"))

    for link in links:
        if limit is not None and res.saved >= limit:
            break
        if link in seen:
            res.skipped_seen += 1
            continue

        # —— 3) 详情页 → PDF（或直接保存 HTML）——
        target, title, content = link, None, None
        try:
            if site.get("direct_pdf") or (pdf_pattern is None and link.lower().endswith(".pdf")):
                content = fetcher.get(link)
                title = Path(urlparse(link).path).stem
            else:
                detail = fetcher.get_text(link)
                err = is_error_page(detail)
                if err:
                    res.rejected += 1
                    seen.add(link)          # ★ 错误页也记账，避免反复重抓
                    continue
                if pdf_pattern:
                    m = re.search(pdf_pattern, detail)
                    if not m:
                        res.rejected += 1
                        seen.add(link)
                        continue
                    pdf_url = urljoin(link, m.group(1))
                    if same_host and urlparse(pdf_url).netloc != urlparse(link).netloc:
                        res.rejected += 1
                        seen.add(link)
                        continue
                    target = pdf_url
                    content = fetcher.get(pdf_url)
                else:
                    # 无 pdf_pattern → 保存详情页 HTML
                    content = detail.encode("utf-8")
                    target = link
                title = _extract_title(site, detail) or Path(urlparse(link).path).stem or name
        except Exception as e:  # noqa: BLE001
            res.errors.append(f"{link}: {e}")
            continue

        # —— 4) 产物闸门 ——
        ext = ".pdf" if (target.lower().endswith(".pdf") or (content or b"")[:5] == b"%PDF-") else ".html"
        if ext == ".pdf" and not (content or b"").rstrip().endswith(b"%%EOF"):
            res.rejected += 1
            seen.add(link)
            continue

        date_prefix = datetime.now().strftime("%y%m%d")
        fname = safe_name(f"{date_prefix}_{title}{ext}")
        path = out_dir / fname
        if path.exists():
            if path.stat().st_size == len(content or b""):
                seen.add(link)
                res.skipped_seen += 1
                continue
            # ★★ 同名不同内容 = 标题撞车（典型：h1[0] 是站点外壳，所有详情页同名）
            #    → 若直接覆盖，N 个链接只会落 1 个文件（实测 Fed 3 保存 → 1 文件）
            #    正解是配 title_from:"title"；这里加 hash 兜底，保证「不静默丢数据」
            h = hashlib.md5(link.encode("utf-8")).hexdigest()[:6]
            path = out_dir / safe_name(f"{date_prefix}_{title}_{h}{ext}")
            res.errors.append(f"标题撞车，已加 hash 兜底: {title} ← {link}")
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(content or b"")
        tmp.replace(path)
        seen.add(link)                       # ★ 只在成功后记账
        res.saved += 1

    return res


def _extract_title(site: dict, html: str) -> str | None:
    source = site.get("title_from", "h1")
    if source == "title":
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    else:
        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    if not m:
        return None
    t = re.sub(r"<[^>]+>", " ", m.group(1))
    t = re.sub(r"\s+", " ", t).strip()
    prefix = site.get("title_strip_prefix")
    if prefix and t.startswith(prefix):
        t = t[len(prefix):].strip(" _-")
    for skip in site.get("title_skip", []):
        if skip and skip in t:
            t = t.replace(skip, " ").strip()
    return t or None


# ---------------------------------------------------------------- 台账
def load_seen(path: Path) -> set[str]:
    if path.exists():
        try:
            return set(json.loads(path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            return set()
    return set()


def save_seen(path: Path, seen: set[str]) -> None:
    """原子写（★ 真实系统里这一步必须加文件锁，否则多进程互相覆盖）。"""
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=0), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- 子命令
def cmd_doctor(args) -> int:
    """离线验 pattern：对每个站抓列表页，数 link_pattern 命中数。0 命中报警。"""
    sites = json.loads(Path(args.config).read_text(encoding="utf-8"))
    bad = 0
    for site in sites:
        name = site.get("name", "?")
        if site.get("direct_pdf"):
            print(f"[OK ] {name}: direct_pdf（跳过 pattern 检查）")
            continue
        try:
            f = Fetcher(site, timeout=args.timeout, proxy=args.proxy)
            html = f.get_text(site["list_url"])
            hits = extract_links(site, html, site.get("base_url") or site["list_url"])
            if hits:
                print(f"[OK ] {name}: 命中 {len(hits)} 条 | 例: {hits[0][:90]}")
            else:
                bad += 1
                print(f"[!!!] {name}: ★ 0 命中 —— pattern 写错了（不是站点错）")
        except Exception as e:  # noqa: BLE001
            bad += 1
            print(f"[ERR] {name}: {e}")
    print(f"\n体检完成：{len(sites)} 站，{bad} 站需处理")
    return 1 if bad else 0


def cmd_crawl(args) -> int:
    sites = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if args.only:
        sites = [s for s in sites if args.only in s.get("name", "")]
        if not sites:
            print(f"★ --only '{args.only}' 没匹配到任何站（子串匹配，且只能一个）")
            return 2
    root = Path(args.root)
    seen_path = Path(args.seen)
    seen = load_seen(seen_path)

    total = CrawlResult()
    for site in sites:
        t0 = time.time()
        try:
            r = crawl_site(site, root, seen, limit=args.limit, proxy=args.proxy,
                           timeout=args.timeout, on_progress=print)
        except Exception as e:  # noqa: BLE001
            print(f"[ERR] {site.get('name')}: {e}")
            continue
        total.saved += r.saved
        total.skipped_seen += r.skipped_seen
        total.rejected += r.rejected
        total.errors += r.errors
        dt = time.time() - t0
        print(f"[{site.get('name')}] 保存 {r.saved} | 跳过(seen) {r.skipped_seen} | "
              f"拦下 {r.rejected} | 错误 {len(r.errors)} | {dt:.1f}s")
        save_seen(seen_path, seen)     # ★ 每站落一次，中断也不丢进度

    print(f"\n合计：保存 {total.saved} | 跳过 {total.skipped_seen} | 拦下 {total.rejected} "
          f"| 错误 {len(total.errors)}")
    if total.errors:
        print("前 5 条错误：")
        for e in total.errors[:5]:
            print("  -", e)
    return 0


def cmd_status(args) -> int:
    root = Path(args.root)
    seen = load_seen(Path(args.seen))
    files = list(root.rglob("*.pdf")) + list(root.rglob("*.html"))
    pdfs = [p for p in files if p.suffix == ".pdf"]
    complete = sum(1 for p in pdfs if is_complete_pdf(p))
    print(f"产物目录 : {root}")
    print(f"文件总数 : {len(files)}（PDF {len(pdfs)} / HTML {len(files) - len(pdfs)}）")
    print(f"PDF 完整 : {complete}/{len(pdfs)}"
          + ("" if complete == len(pdfs) else "  ← ★ 有截断件，跑 audit_artifacts.py"))
    print(f"seen 台账: {len(seen)} 条")
    dirs = [d for d in root.glob("*/*") if d.is_dir()]
    low = [d for d in dirs if len(list(d.glob("*"))) < 20]
    print(f"站点目录 : {len(dirs)}（其中 {len(low)} 个 < 20 文件 → 未真打通）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="配置驱动的多站点研报采集引擎（参考实现）")
    ap.add_argument("--config", default="sites.example.json")
    ap.add_argument("--root", default="../reports")
    ap.add_argument("--seen", default="../seen_links.json")
    ap.add_argument("--proxy", default=None, help="如 http://127.0.0.1:10808")
    ap.add_argument("--timeout", type=int, default=30)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("crawl", help="抓取")
    p.add_argument("--only", default=None, help="★ 子串匹配，且只能一个")
    p.add_argument("--limit", type=int, default=None, help="每站最多保存几个（试跑用）")
    p.set_defaults(func=cmd_crawl)

    sub.add_parser("doctor", help="离线验 pattern 命中数").set_defaults(func=cmd_doctor)
    sub.add_parser("status", help="看产物/台账状态").set_defaults(func=cmd_status)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
