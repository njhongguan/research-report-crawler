#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doctor.py — 配置体检的独立入口（离线验 pattern 命中数）。

等价于 `python crawler.py --config <cfg> doctor`，单独成文件便于流水线调用。
★ 0 命中 = pattern 写错了，不是站点错。这是最高频的分诊结论。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from crawler import cmd_doctor  # noqa: E402


class _Args:
    def __init__(self, config):
        self.config = config
        self.timeout = 30
        self.proxy = None


if __name__ == "__main__":
    cfg = sys.argv[1] if len(sys.argv) > 1 else "sites.example.json"
    sys.exit(cmd_doctor(_Args(cfg)))
