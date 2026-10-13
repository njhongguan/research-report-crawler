#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""annual_diff.py — 年度系列差异分析（同一份报告跨年份对比）。

三件事：① 发现「多年份系列」 ② 对比（map-reduce） ③ 两种出口
  · --pack / --pack-top N  只导出素材包，**不调 AI**（给用户自己的 AI 用）★ 推荐
  · --index                生成看板 HTML
  · 默认                    用自带 AI 池直接出报告（此处留出接入点）

用法：
  python annual_diff.py --root ../reports --list-series
  python annual_diff.py --root ../reports --index
  python annual_diff.py --root ../reports --pack-top 10
  python annual_diff.py --root ../reports --dir "reports/科技产业/StateOfAI-人工智能现状报告" --pack
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

NAME_RE = re.compile(r"^(\d{6})_(.+?)\.(pdf|html?)$", re.I)
YEAR_RE = re.compile(r"(19|20)\d{2}")
# ★ 尾部 hash 必须【含数字】才算 hash —— 否则会吃掉 report-to-**nations** 这类正常尾词
HASH_RE = re.compile(r"[-_](?=[a-z0-9]*\d)[a-f0-9]{6,16}$", re.I)
# 语言 / 清晰度标记
LANG_RE = re.compile(r"[_-](lowres|low_res|highres|hires|spanish|portuguese|french|"
                     r"german|chinese|japanese|korean|es|pt|fr|de|zh)\b", re.I)
STOPWORDS = {"the", "a", "an"}

# 已知改名幅度大的系列（别名表）
TITLE_ALIAS = {
    "dr": "v-dem-democracy-report",
}


def normalize_title(title: str) -> str:
    """标题归一化：去日期前缀 → 去年份 → 去语言标记 → 去尾部 hash → 小写。

    ★ 两个必须的修正（都踩过）：
      1. 尾部 hash 必须含数字，否则 `report-to-nations` 会被误吃
      2. `the` 作停用词，让 `report-to-the-nations` 与 `report-to-nations` 并组
    """
    t = title.strip()
    t = re.sub(r"^\d{6}[_-]", "", t)          # 抓取日期前缀
    t = YEAR_RE.sub(" ", t)                    # 年份
    t = LANG_RE.sub(" ", t)                    # 语言/清晰度
    t = HASH_RE.sub("", t)                     # 尾部 hash（必须含数字）
    t = re.sub(r"[_\s]+", "-", t.lower()).strip("-")
    t = re.sub(r"-{2,}", "-", t)
    words = [w for w in t.split("-") if w and w not in STOPWORDS]
    t = "-".join(words)
    return TITLE_ALIAS.get(t, t)


def extract_year(title: str) -> str | None:
    m = YEAR_RE.findall(title)
    years = re.findall(r"(?:19|20)\d{2}", title)
    return years[-1] if years else None


def discover_series(root: Path, min_years: int = 2, min_files: int = 2) -> dict:
    """从文件名自动认出「同一份报告的多个年份」。"""
    series = defaultdict(lambda: {"years": defaultdict(list), "site": ""})
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in (".pdf", ".html", ".htm"):
            continue
        m = NAME_RE.match(p.name)
        title = m.group(2) if m else p.stem
        year = extract_year(title)
        if not year:
            continue                      # ★ 识别不到年份 → 跳过（不误判）
        key = normalize_title(title)
        if not key:
            continue
        rel = p.relative_to(root)
        parts = rel.parts
        site = "/".join(parts[:2]) if len(parts) > 2 else (parts[0] if parts else "")
        series[key]["years"][year].append(str(p))
        series[key]["site"] = site

    out = {}
    for key, info in series.items():
        years = sorted(info["years"])
        n_files = sum(len(v) for v in info["years"].values())
        if len(years) >= min_years and n_files >= min_files:
            out[key] = {"years": {y: info["years"][y] for y in years},
                        "site": info["site"], "n_files": n_files}
    return dict(sorted(out.items(), key=lambda kv: -len(kv[1]["years"])))


# ---------------------------------------------------------------- PDF 取文
def pdf_text(path: Path, max_chars: int = 20000) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:  # noqa: BLE001
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except Exception:  # noqa: BLE001
            return ""
    try:
        reader = PdfReader(str(path))
        buf = []
        for page in reader.pages[:40]:
            buf.append(page.extract_text() or "")
            if sum(len(x) for x in buf) > max_chars:
                break
        return "\n".join(buf)[:max_chars]
    except Exception:  # noqa: BLE001
        return ""


def html_text(path: Path, max_chars: int = 20000) -> str:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    # ★ 先剥 AI 简报卡片（会撑长正文、破坏判据）
    raw = re.sub(r"<!--\s*AI BRIEFING CARD START.*?AI BRIEFING CARD END\s*-->", "", raw,
                 flags=re.I | re.S)
    raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text)
    return text[:max_chars]


def read_report(path: str) -> str:
    p = Path(path)
    return pdf_text(p) if p.suffix.lower() == ".pdf" else html_text(p)


# ---------------------------------------------------------------- 出口
PACK_HEADER = """# 年度系列对比素材包：{key}

> **给 AI 的指令（请照此执行）**
>
> 你面前是同一份系列报告在不同年份的正文摘录。请做**跨年度差异分析**，输出四类结论：
>
> 1. **逐年新增** —— 今年新出现、去年没有的议题
> 2. **反转** —— 与上一年**结论相反**的判断（最有价值，务必单列）
> 3. **长期主线** —— 每年都强调的（信仰级判断）
> 4. **数字趋势** —— 关键指标的年际变化（保留原始口径，不要二次换算）
>
> **硬约束**：**不得凭空推断**，每条结论都要能追溯到下面某一年正文中的原句。
> 无法从材料中得出的，明确写「材料未覆盖」，不要猜。

- 系列键：`{key}`
- 覆盖年份：{years}
- 站点：{site}
- 生成时间：{ts}

---
"""


def export_pack(key: str, info: dict, outdir: Path, per_year: int = 1) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    years = sorted(info["years"])
    lines = [PACK_HEADER.format(key=key, years=", ".join(years),
                                site=info["site"], ts=f"{datetime.now():%Y-%m-%d %H:%M}")]
    sub = outdir / f"{_slug(key)}_素材"
    sub.mkdir(parents=True, exist_ok=True)
    for y in years:
        paths = sorted(info["years"][y])[:per_year]
        for path in paths:
            text = read_report(path)
            (sub / f"{y}_{Path(path).stem[:80]}.txt").write_text(text, encoding="utf-8")
            lines.append(f"\n## {y} 年\n\n来源：`{path}`\n\n```\n{text[:6000]}\n```\n")
    out = outdir / f"{key}_对比素材包.md"
    out.write_text("".join(lines), encoding="utf-8")
    return out


def _slug(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", s)[:80]


def render_board(series: dict, outdir: Path) -> Path:
    rows = "\n".join(
        f'<tr><td>{i+1}</td><td>{_esc(k)}</td><td>{", ".join(sorted(v["years"]))}</td>'
        f'<td>{len(v["years"])}</td><td>{v["n_files"]}</td><td>{_esc(v["site"])}</td></tr>'
        for i, (k, v) in enumerate(series.items())
    )
    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>年度报告差异分析 · 看板</title>
<style>body{{font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
margin:0;padding:24px}}h1{{font-size:20px}}table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{border-bottom:1px solid #eee;padding:6px 8px;text-align:left}}
th{{background:#fafafa}}tr:hover{{background:#f7f9fc}}</style></head><body>
<h1>年度报告差异分析 · 看板</h1>
<p>全库识别出 <b>{len(series)}</b> 个「多年份发布」系列 · {datetime.now():%Y-%m-%d %H:%M}</p>
<table><thead><tr><th>#</th><th>系列键</th><th>覆盖年份</th><th>年数</th><th>文件数</th>
<th>站点</th></tr></thead><tbody>
{rows}
</tbody></table></body></html>"""
    out = outdir / "年度报告差异分析_看板.html"
    out.write_text(html, encoding="utf-8")
    return out


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main() -> int:
    ap = argparse.ArgumentParser(description="年度系列差异分析")
    ap.add_argument("--root", default="../reports")
    ap.add_argument("--out", default="../_annual_diff_out")
    ap.add_argument("--list-series", action="store_true")
    ap.add_argument("--index", action="store_true", help="生成看板 HTML")
    ap.add_argument("--dir", default=None, help="只处理这个站点目录")
    ap.add_argument("--title", default=None, help="配合 --dir，只分析该系列键")
    ap.add_argument("--pack", action="store_true", help="★ 只导出素材包，不调 AI")
    ap.add_argument("--pack-top", type=int, default=0, help="批量导出前 N 个系列")
    ap.add_argument("--per-year", type=int, default=1)
    ap.add_argument("--min-years", type=int, default=2)
    ap.add_argument("--min-files", type=int, default=2)
    args = ap.parse_args()

    root = Path(args.root) / args.dir if args.dir else Path(args.root)
    outdir = Path(args.out)
    series = discover_series(root, args.min_years, args.min_files)

    if args.list_series:
        for i, (k, v) in enumerate(series.items(), 1):
            print(f"{i:3d}. [{len(v['years'])} 年] {k}  ({', '.join(sorted(v['years']))})")
        print(f"\n共 {len(series)} 个系列")
        return 0

    if args.index:
        p = render_board(series, outdir)
        print(f"看板 → {p}（{len(series)} 个系列）")
        return 0

    targets = list(series.items())
    if args.title:
        targets = [(k, v) for k, v in targets if k == args.title]
    elif args.pack_top:
        targets = targets[:args.pack_top]

    if args.pack or args.pack_top:
        if not targets:
            print("没找到可导出的系列（检查 --dir / --title）")
            return 1
        for k, v in targets:
            p = export_pack(k, v, outdir, args.per_year)
            print(f"素材包 → {p}")
        print("\n★ 不消耗 AI 池。把素材包整个丢给任意 AI 即可。")
        return 0

    # 默认出口：用自带 AI 池（此处仅打印接入点，避免误烧额度）
    print(f"识别到 {len(series)} 个系列。要出 AI 报告请接入你自己的 AI 池；")
    print("推荐先用 --pack 导出素材包交给外部 AI。")
    print("可分析系列（前 10）：")
    for k, v in targets[:10]:
        print(f"  - {k}  ({', '.join(sorted(v['years']))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
