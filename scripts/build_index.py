#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_index.py — 秒级重建索引与看板（解耦 AI 补跑）。

★★★ 为什么要单独一个脚本：
    主引擎的 run_report() 顺序是「扫描 → 加载缓存 → 【逐条调 AI 补摘要】 → 翻译 → 出 HTML」。
    第 ③ 步约 1 条/分钟 → 2,832 条要 ≈47 小时才出看板。
    本脚本只做 ①②④⑤，跳过 ③ → 1~2 秒出板。

用法：
  python build_index.py --root ../reports --out ../reports/研报索引.html
  python build_index.py --root ../reports --data ../reports/reports_data.json
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

# 产物名：<YYMMDD>_<标题>.ext
NAME_RE = re.compile(r"^(\d{6})_(.+?)\.(pdf|html?)$", re.I)


def scan_all_reports(root: Path) -> list[dict]:
    """扫描磁盘产物。★ 这是真相来源；索引 JSON 可能滞后。"""
    out = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in (".pdf", ".html", ".htm"):
            continue
        m = NAME_RE.match(p.name)
        date, title = (m.group(1), m.group(2)) if m else ("", p.stem)
        rel = p.relative_to(root)
        parts = rel.parts
        category = parts[0] if len(parts) > 2 else "未分类"
        site = parts[1] if len(parts) > 2 else (parts[0] if len(parts) > 1 else "未分类")
        out.append({
            "title": title,
            "date": date,
            "category": category,
            "site": site,
            "path": str(rel).replace("\\", "/"),
            "ext": p.suffix.lower().lstrip("."),
            "size": p.stat().st_size,
            "mtime": p.stat().st_mtime,
        })
    out.sort(key=lambda x: (x["date"], x["mtime"]), reverse=True)
    return out


def render_index_html(reports: list[dict], title: str = "研报索引") -> str:
    rows = "\n".join(
        f'<tr><td>{r["date"]}</td><td>{_esc(r["category"])}</td>'
        f'<td>{_esc(r["site"])}</td><td><a href="{_esc(r["path"])}">{_esc(r["title"])}</a></td>'
        f'<td>{r["ext"]}</td><td>{r["size"] // 1024} KB</td></tr>'
        for r in reports
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<style>
 body{{font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
      margin:0;padding:24px;background:#fff;color:#1a1a1a}}
 h1{{font-size:20px;margin:0 0 4px}} .meta{{color:#666;margin-bottom:16px}}
 input{{width:100%;max-width:420px;padding:8px 12px;font-size:14px;
      border:1px solid #ddd;border-radius:6px;margin-bottom:12px}}
 table{{border-collapse:collapse;width:100%;font-size:13px}}
 th,td{{border-bottom:1px solid #eee;padding:6px 8px;text-align:left}}
 th{{position:sticky;top:0;background:#fafafa;font-weight:600}}
 tr:hover{{background:#f7f9fc}} a{{color:#0b63ce;text-decoration:none}}
 a:hover{{text-decoration:underline}}
</style></head><body>
<h1>{_esc(title)}</h1>
<div class="meta">共 {len(reports)} 条 · 生成于 {datetime.now():%Y-%m-%d %H:%M}</div>
<input id="q" placeholder="搜索标题 / 站点 / 大类…" oninput="f()">
<table id="t"><thead><tr><th>日期</th><th>大类</th><th>站点</th>
<th>标题</th><th>类型</th><th>大小</th></tr></thead><tbody>
{rows}
</tbody></table>
<script>
function f(){{var q=document.getElementById('q').value.toLowerCase();
var rs=document.querySelectorAll('#t tbody tr');
for(var i=0;i<rs.length;i++){{rs[i].style.display=rs[i].innerText.toLowerCase().indexOf(q)>=0?'':'none';}}}}
</script></body></html>"""


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def main() -> int:
    ap = argparse.ArgumentParser(description="秒级重建索引（跳过 AI 补跑）")
    ap.add_argument("--root", default="../reports")
    ap.add_argument("--out", default=None, help="索引 HTML 输出路径")
    ap.add_argument("--data", default=None, help="reports_data.json 输出路径")
    ap.add_argument("--backup", action="store_true", default=True,
                    help="覆盖 JSON 前备份（默认开）")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"目录不存在: {root}")
        return 2

    reports = scan_all_reports(root)
    print(f"scan_all_reports(): {len(reports)} 条")

    # 索引滞后判据
    data_path = Path(args.data) if args.data else root / "reports_data.json"
    if data_path.exists():
        try:
            old = json.loads(data_path.read_text(encoding="utf-8"))
            n_old = len(old) if isinstance(old, list) else len(old.get("reports", []))
            if n_old and len(reports) > n_old * 1.05:
                print(f"★ 索引滞后：旧 {n_old} vs 磁盘 {len(reports)} → 重建")
        except Exception:  # noqa: BLE001
            pass
        if args.backup:
            bak = data_path.with_suffix(data_path.suffix + f".bak{datetime.now():%Y%m%d_%H%M%S}")
            bak.write_bytes(data_path.read_bytes())
            print(f"已备份 → {bak.name}")

    tmp = data_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(reports, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(data_path)
    print(f"已写 {data_path}")

    out = Path(args.out) if args.out else root / "研报索引.html"
    out.write_text(render_index_html(reports), encoding="utf-8")
    print(f"已写 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
