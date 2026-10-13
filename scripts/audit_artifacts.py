#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_artifacts.py — 产物真伪审计（4 类静默污染）。

★★★ 批量抓完必跑。这是「最大口径错误」的唯一防线：
    坏数据不报错、进索引、送 AI → 虚高覆盖率。

检查项：
  ① 截断件        —— PDF 尾部没有 %%EOF
  ② 错误页入库    —— <title> 是 HTTP 状态行（含软 404「404error：站点名」）
  ③ 通用 PDF 污染 —— 多篇产物 MD5 相同（假壳页）
  ④ 空文件 / 过小 —— 明显不是内容

用法：
  python audit_artifacts.py --root ../reports
  python audit_artifacts.py --root ../reports --check-md5
  python audit_artifacts.py --root ../reports --quarantine   # 移到 _quarantine_<日期>/
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from crawler import is_complete_pdf, is_error_page  # noqa: E402

MIN_PDF_BYTES = 1024


def md5_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def audit(root: Path, check_md5: bool) -> dict:
    issues = {"truncated": [], "error_page": [], "empty": [], "dup_md5": []}
    files = sorted(p for p in root.rglob("*") if p.suffix.lower() in (".pdf", ".html", ".htm"))
    md5_map = defaultdict(list)

    for p in files:
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size == 0:
            issues["empty"].append(str(p))
            continue
        if p.suffix.lower() == ".pdf":
            if size < MIN_PDF_BYTES or not is_complete_pdf(p):
                issues["truncated"].append(str(p))
            if check_md5:
                md5_map[md5_of(p)].append(str(p))
        else:
            try:
                head = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            kind = is_error_page(head)
            if kind:
                issues["error_page"].append(f"{p}  [{kind}]")

    if check_md5:
        for h, paths in md5_map.items():
            if len(paths) > 1:
                issues["dup_md5"].append({"md5": h, "count": len(paths), "paths": paths})

    return issues


def quarantine(root: Path, issues: dict) -> Path:
    """★ 一律 shutil.move 到隔离区，绝不 rm。"""
    qdir = root.parent / f"_quarantine_audit_{datetime.now():%Y%m%d_%H%M%S}"
    qdir.mkdir(parents=True, exist_ok=True)
    manifest = []
    targets = list(issues["truncated"]) + list(issues["empty"])
    targets += [x.split("  [")[0] for x in issues["error_page"]]
    for t in targets:
        src = Path(t)
        if not src.exists():
            continue
        rel = src.relative_to(root) if root in src.parents else Path(src.name)
        dst = qdir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        manifest.append({"src": str(src), "dst": str(dst)})
    (qdir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return qdir


def main() -> int:
    ap = argparse.ArgumentParser(description="产物真伪审计")
    ap.add_argument("--root", default="../reports")
    ap.add_argument("--check-md5", action="store_true", help="同时查重复 MD5（通用 PDF 污染）")
    ap.add_argument("--quarantine", action="store_true", help="把命中项移到隔离区（move，不删除）")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"目录不存在: {root}")
        return 2

    issues = audit(root, args.check_md5)
    total = (len(issues["truncated"]) + len(issues["error_page"])
             + len(issues["empty"]) + len(issues["dup_md5"]))

    print("=" * 56)
    print("① 截断件（尾部无 %%EOF）:", len(issues["truncated"]))
    for x in issues["truncated"][:5]:
        print("   -", x)
    print("② 错误页入库:", len(issues["error_page"]))
    for x in issues["error_page"][:5]:
        print("   -", x)
    print("④ 空文件:", len(issues["empty"]))
    if args.check_md5:
        print("③ 重复 MD5 组（通用 PDF 污染）:", len(issues["dup_md5"]))
        for g in issues["dup_md5"][:5]:
            print(f"   - {g['count']} 个文件同 MD5: {g['paths'][0]}")
    print("=" * 56)
    print(f"合计问题 {total} 项")

    if args.quarantine and total:
        qdir = quarantine(root, issues)
        print(f"★ 已隔离到 {qdir}（move，未删除）；清单见 manifest.json")
        print("★ 别忘了把这些 URL 从 seen 放出，否则永远重抓不到。")
    elif total:
        print("★ 加 --quarantine 执行隔离（move，不删除）。")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
