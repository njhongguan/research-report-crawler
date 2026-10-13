# research-report-crawler · 研报采集系统总纲

> 把「从 N 个官网自动抓研报 → 存成可检索语料库 → AI 中文研判 → 定时推送 → 云端归档 → 年度差异分析」
> 这套系统，压缩成一个**可移植、可运行、可无人值守**的能力包。

这是一个 **Agent Skill**（技能包），也是一个可以直接 `git clone` 下来跑的**参考实现**。
别的 AI 读完 `SKILL.md`，就能在自己的机器上重建这台机器 —— 不是「知道原理」，而是**跑得起来**。

---

## 它解决什么问题

做研报语料库，真正的难点**不是「怎么下载一个 PDF」**，而是：

| 难点 | 表象 | 本技能给的判据 |
|---|---|---|
| **坏数据混进来** | 文件都在、索引也有、AI 也生成了简报 | 尾部有没有 `%%EOF` / 标题是不是 HTTP 状态行 / 多篇 MD5 是否互异 |
| **抓不到但不知道卡在哪** | 全是「403」「0 产出」 | 概率性拦截 vs 硬封 / 零产物站三分诊 / 「有内容+0命中=改 pattern」 |
| **看起来在跑，其实没干活** | 日志正常、进程在转 | 验收看**产物**不看日志；`seen` 有没有真的写进去 |
| **抓完上不了看板** | 磁盘 11,633 条，看板只有 2,107 条 | 索引滞后判据 + 秒级重建 |
| **无人值守就死** | 连续 7 天全败，日志是 `EPIPE` | 真凶是 `TimeoutStartSec`；看 `systemctl status` 不看日志尾部 |
| **磁盘装不下** | 云端只剩 4.8G，语料 15G | 分批中转 + 即推即删 + 磁盘熔断 |

---

## 快速开始

```bash
git clone <this-repo> && cd research-report-crawler/scripts

# 1. 看配置长什么样（5 个站的 6 种抓取形态示例）
cat sites.example.json

# 2. 体检：每个站的 pattern 能不能命中列表页（0 命中会报警）
python doctor.py sites.example.json

# 3. 抓一个站（先验证通道）
python crawler.py --config sites.example.json --only "Fed" --limit 3

# 4. 产物真伪审计（★ 批量抓完必跑）
python audit_artifacts.py --root ../reports --check-md5

# 5. 秒级重建可检索索引（不等 AI 补跑）
python build_index.py --root ../reports --out ../reports/研报索引.html

# 6. 年度系列差异：只导素材包，不烧 AI
python annual_diff.py --root ../reports --pack-top 10
```

**依赖**（都可选，缺失自动降级到标准库）：

```bash
pip install curl_cffi beautifulsoup4 pypdf playwright && playwright install chromium
```

---

## 目录结构

```
├── SKILL.md                      # ★ 主入口：架构图 / 五阶段 / 铁律速查 20 条
├── references/
│   ├── 01-architecture.md        # 系统架构 · 配置 schema · 目录规范 · 并发模型
│   ├── 02-fetch-recipes.md       # 6 种抓取形态配置模板 + 全部辅助键 + pattern 五个坑
│   ├── 03-anti-crawl-playbook.md # ★ 9 类反爬处置表 · 概率性vs硬封 · 双场景互补 · 零产物三分诊
│   ├── 04-artifact-integrity.md  # ★ 4 类静默污染 · 截断/错误页/重复/通用PDF 的判据
│   ├── 05-source-onboarding.md   # 新站接入 12 条铁律 · 投行口径问题 · 入队检查清单
│   ├── 06-index-briefing.md      # 索引滞后 · 解耦 AI 补跑 · 两份简报库的陷阱
│   ├── 07-scheduling-cloud.md    # 定时调度 · 超时杀手 · 云端协同 · SSH 稳定性
│   ├── 08-archiving-sync.md      # 流式中转归档 · 即推即删 · 并发与内存安全线
│   └── 09-annual-diff.md         # 年度系列识别 · map-reduce · 缓存必须绑内容
└── scripts/
    ├── crawler.py                # 配置驱动采集引擎（可跑）· crawl/doctor/status
    ├── sites.example.json        # 配置样例（6 种形态）
    ├── doctor.py                 # 配置体检（离线验 pattern 命中）
    ├── audit_artifacts.py        # 产物真伪审计 + 隔离（move，不删除）
    ├── build_index.py            # 秒级重建索引/看板
    └── annual_diff.py            # 年度系列差异（--pack / --index / --list-series）
```

---

## 参考实现的验证记录

`scripts/` 里的代码**都实跑过**（2026-10-13，真实网络）：

| 验证项 | 结果 |
|---|---|
| 5 个脚本语法编译 | ✅ 全部通过 |
| `status` 扫描夹具 | ✅ 正确识别「9 文件 / PDF 6-7 完整 / 有截断件」 |
| `audit_artifacts` 夹具 | ✅ 截断件 1 + 软404 错误页 1 + 重复 MD5 1 组，**全部命中** |
| `audit_artifacts --quarantine` | ✅ 移到 `_quarantine_audit_*/`，产出 manifest，**未删除** |
| `build_index` 夹具 | ✅ 9 条入索引，JSON + 可搜 HTML |
| `annual_diff --list-series` | ✅ 正确把 `2023/2024/2025_lowres/2026_7f3a91` 归为**同一系列** |
| **真实抓取 Fed RSS** | ✅ 列表页命中 20 条 → 落 **3 篇真实 PDF**（189KB / 10.2MB / 436KB）→ 审计 **0 问题** |

**验证中当场踩到的两个坑（已写进技能，并已在代码里兜底）**：

1. **Fed 的 RSS 链接包在 CDATA 里**（`<link><![CDATA[url]]></link>`）→
   朴素的 `<link>(url)</link>` pattern **0 命中**。→ 必须容忍 CDATA，并排除频道自身的 link。
2. **Fed 详情页的 `<h1>` 是站点外壳名**（所有页面同名）→ 第一次跑「保存 3，实际只落 1 个文件」。
   → 正解是配 `title_from: "title"`；引擎里也加了 **hash 兜底**，保证「不静默丢数据」。

---

## 核心原则

> **1. 「能抓」不等于「抓对」。** 最危险的失败不是没数据，是坏数据混进来。
>
> **2. 「有产物」不等于「打通了」。** < 20 个文件就不算真打通。
>
> **3. 失败原因的分类比失败数量重要得多。** 同一个「抓不到」，
> 可能是瞬时抖动 / 入口过期 / 反爬 / SPA 空壳 —— 四种原因，处置**互相排斥**。

---

## 与相邻技能的关系

本技能是**总纲**，负责编排；细节由专门技能承担：

```
research-report-crawler  ← 总纲 / 编排 / 骨架
├─ source-reachability-triage          选源：这批站能不能抓
├─ research-corpus-onboarding          接入：单源配置→长跑→验收
├─ json-api-site-onboarding            SPA 站找官方 API
├─ cloudflare-bypass-diagnosis         CF 403 专项
├─ crawl-artifact-authenticity-audit   产物真伪专项
├─ idempotent-batch-ingest             批量入库幂等
├─ resumable-job-concurrency           断点续跑 + 并发
├─ ai-batch-output-guard               AI 批量产物质检
├─ cjk-corpus-search-pipeline          中文语料检索
├─ html-to-pdf-report-pipeline         HTML→PDF 渲染
└─ smtp-delivery-diagnosis             邮件送达诊断
```

---

## 口径纪律

1. **实测支撑 + 原始数字**，凡「打不通」必附证据。
2. **口径错误比没数据更危险** —— 宁可标「未知」，不要猜一个数字填上。
3. **付费通道不用**；只抓公开内容，抓到「登录壳」要标注。
4. **名字叫「研究报告」≠ 抓到研报** —— 投行公开 Insights ≠ 卖方 GIR 研报（后者在登录门户后）。
5. **隔离/清理一律 `shutil.move` 到 `_quarantine_*/`**，绝不 `rm`。

---

## License

MIT
