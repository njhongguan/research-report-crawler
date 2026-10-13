---
name: research-report-crawler
description: 从零搭一套「全球研究机构报告自动采集 → 可检索语料库 → AI 中文研判 → 定时邮件推送 → 云端归档 → 年度差异分析」系统的完整工程能力包。**本技能是总纲**：把「抓报告」这件事从「会写 requests」升级为「能长期无人值守运行、且产物可信」的生产系统。覆盖六大子系统：① 配置驱动的多站采集引擎（`sites_config.json` 一站一条，支持 6 种抓取形态）② 反爬处置手册（9 类拦截的识别与对策 + 「概率性拦截 vs 硬封」判据 + 本地节点/云端海外 IP 双场景互补）③ 产物真伪闸门（4 类静默污染：截断件 / 错误页入库 / seen 未写重复重抓 / 通用 PDF 污染）④ 索引与看板（抓取≠上屏：解耦 AI 补跑的秒级出板）⑤ 云端协同与定时调度（本机不开机也能跑；超时是被忽略的杀手）⑥ 归档与年度差异分析（流式中转即推即删 + 同一系列跨年份对比）。当用户说「抓报告 / 采集研报 / 建研报库 / 监控这些机构的新报告 / 把这些网站的报告抓下来 / 报告语料库 / 研报抓取系统 / 定时抓取推送 / 抓不到报告 / 抓下来的是错误页 / 报告库怎么做 / 年报对比」时使用。**与相邻技能的边界**：单源接入细节走 `research-corpus-onboarding`；候选源能否抓走 `source-reachability-triage`；SPA 站找官方 API 走 `json-api-site-onboarding`；产物是不是真内容走 `crawl-artifact-authenticity-audit`；CF 403 走 `cloudflare-bypass-diagnosis`；批量入库幂等走 `idempotent-batch-ingest`；断点续跑加并发走 `resumable-job-concurrency`；AI 批量产物质检走 `ai-batch-output-guard`；中文语料检索走 `cjk-corpus-search-pipeline`；HTML→PDF 渲染走 `html-to-pdf-report-pipeline`；邮件送达走 `smtp-delivery-diagnosis`。本技能负责把它们**编排成一台能长期跑的机器**。触发词：抓报告、研报抓取、采集系统、报告语料库、多站点采集、sites_config、定时抓取、自动推送、反爬、Cloudflare 抓不到、Akamai 403、产物是错误页、截断 PDF、抓不全、零产物站、节点池、云端协同、归档、Google Drive、年度报告对比、年报差异、research report crawler、corpus pipeline、data collection system。
agent_created: true
---

# 研报采集系统 · 总纲

> **一句话**：把「从 N 个官网自动抓研报 → 存成可检索语料库 → AI 中文研判 → 定时推送 → 云端归档 → 年度差异分析」
> 这套系统，压缩成一个**可移植、可运行、可无人值守**的能力包。
> 别的 AI 读完这个技能，就能在自己的机器上重建它 —— 不是「知道原理」，而是**跑得起来**。

---

## 零、先看这张图

```
                    ┌─────────────────────────────────────────────┐
                    │   sites_config.json   （一站一条，唯一真源）  │
                    │   URL · 正则 · 反爬参数 · 口径标签            │
                    └──────────────────┬──────────────────────────┘
                                       │
     ┌─────────────────────────────────┼─────────────────────────────────┐
     │                                 ▼                                 │
     │   ┌───────────────────────────────────────────────────────────┐   │
     │   │            采集引擎  crawler.py / main.py                  │   │
     │   │  列表页 ──正则──▶ 详情页 ──正则──▶ PDF/HTML               │   │
     │   │  6 种形态：列表→详情 / 列表→PDF直链 / sitemap / RSS /      │   │
     │   │            direct_pdf / JSON(use_text)                    │   │
     │   │  通道：直连 │ curl_cffi(TLS指纹) │ 节点池(xray+真Chrome)   │   │
     │   └───────┬───────────────────────────────┬───────────────────┘   │
     │           │                               │                       │
     │   ┌───────▼────────┐              ┌───────▼────────┐              │
     │   │  seen_links    │              │  reports/      │              │
     │   │  去重台账(URL) │              │  <大类>/<站名>/ │              │
     │   └────────────────┘              │  <日期>_<标题>  │              │
     │                                   └───────┬────────┘              │
     │   ═══════════ 产物真伪闸门 ═══════════     │                       │
     │   is_complete_pdf(%%EOF) · is_error_page · │                       │
     │   MD5 互异 · _scan_blocked_artifacts      │                       │
     │                                           │                       │
     │   ┌───────────────────────────────────────▼───────────────────┐   │
     │   │  索引 & 研判层                                             │   │
     │   │  scan_all_reports → reports_data.json → 看板 HTML          │   │
     │   │  AI 池（免费多通道）→ ai_briefings.json（抓取落）           │   │
     │   │                    daily_summaries.json（看板读）           │   │
     │   └───────────────────────┬───────────────────────────────────┘   │
     │                           │                                       │
     │   ┌───────────────────────▼──────────┐  ┌──────────────────────┐  │
     │   │  推送   邮件（SMTP 水位去重）     │  │  年度差异 annual_diff │  │
     │   └──────────────────────────────────┘  └──────────────────────┘  │
     │                                                                   │
     └───────────────┬───────────────────────────────┬───────────────────┘
                     │                               │
          ┌──────────▼──────────┐         ┌──────────▼──────────┐
          │  本地（中国·节点通道）│  互补   │ 云端（海外 IP·直连） │
          │  过 Cloudflare       │ ◀────▶ │ 过 Akamai/地域限制   │
          │  seen 双向合并        │         │  cron + systemd      │
          └──────────┬──────────┘         └──────────┬──────────┘
                     │                               │
                     └───────────┬───────────────────┘
                                 ▼
                    ┌────────────────────────────┐
                    │  归档：Google Drive 流式中转 │
                    │  即推即删 · 断点续传 · 熔断  │
                    └────────────────────────────┘
```

**读图要点**：这台机器的每个环节都可能**静默失败**（不报错、没产物、看起来在干活）。
本技能的全部价值，就是把这些静默失败点**变成可见的判据**。

---

## 一、核心原则（三句话）

> **1. 「能抓」不等于「抓对」。** 最危险的失败不是没数据，是坏数据混进来 —— 一个截断 PDF、一张错误页，
> 会被计入产物、进索引、送 AI，然后以「数据」的身份流通下去。
>
> **2. 「有产物」不等于「打通了」。** 一个站只有 1 个文件，可能是「每年就发一份」，也可能是「入口早变了」。
> 判据是 **< 20 个文件就不算真打通**。
>
> **3. 失败原因的分类比失败数量重要得多。** 同一个「抓不到」，可能是瞬时抖动 / 入口过期 / 反爬 / SPA 空壳 ——
> 四种原因，处置**互相排斥**。分不清就动手，等于瞎猜。

---

## 二、全生命周期（五阶段）

| 阶段 | 做什么 | 关键产物 | 详细 |
|---|---|---|---|
| **① 选源** | 一批候选站里筛出「能抓 + 值得抓」的 | 分级源清单 | `source-reachability-triage` |
| **② 接入** | 一站一条写配置，跑通 0→有产物 | `sites_config.json` 条目 | `references/02-fetch-recipes.md` |
| **③ 长跑** | 无人值守定时抓，失败能自愈 | 磁盘产物 + `seen_links.json` | `references/03`、`references/07` |
| **④ 验收** | 证明产物是真内容，不是错误页 | 审计报告 | `references/04-artifact-integrity.md` |
| **⑤ 消费** | 索引 / 看板 / AI 简报 / 邮件 / 归档 / 年报对比 | HTML + JSON | `references/06`、`08`、`09` |

★ **顺序不能跳**：先有 ④ 的闸门，再谈 ⑤ 的消费。否则你是在给坏数据做精美的看板。

---

## 三、五分钟跑起来（最小可运行）

技能包自带一套**零依赖可跑的参考实现**（只用标准库 + 可选 playwright）：

```bash
cd scripts

# 1. 看一眼配置长什么样
cat sites.example.json

# 2. 体检：每个站的 pattern 能不能命中列表页（0 命中会报警）
python doctor.py sites.example.json

# 3. 抓一个站（先只抓 1 个，验证通道）
python crawler.py --config sites.example.json --only "Fed" --limit 3

# 4. 全量抓（幂等：抓过的 URL 记在 seen_links.json，不再抓）
python crawler.py --config sites.example.json

# 5. 产物真伪审计（批量抓完必跑）
python audit_artifacts.py --root ../reports

# 6. 生成可检索索引 + 看板（秒级，不等 AI）
python build_index.py --root ../reports --out ../reports/研报索引.html

# 7. 年度系列差异（先导出素材包，不烧 AI）
python annual_diff.py --root ../reports --pack-top 10
```

**依赖**：`pip install curl_cffi playwright beautifulsoup4 pypdf`（`playwright install chromium`）。
不装也能跑 —— 脚本会降级到 `urllib` 直连，只是过不了 Cloudflare。

---

## 四、目录导航

| 文件 | 什么时候读 |
|---|---|
| `references/01-architecture.md` | 要理解整体设计、配置 schema、目录规范 |
| `references/02-fetch-recipes.md` | 要写一个站的配置（6 种形态 + 全部辅助键） |
| `references/03-anti-crawl-playbook.md` | 抓不到 / 403 / 空壳 —— **最常翻的一篇** |
| `references/04-artifact-integrity.md` | 验收产物、怀疑抓到假东西 |
| `references/05-source-onboarding.md` | 新加站、pattern 写不对、撞名/重复 |
| `references/06-index-briefing.md` | 抓完上不了看板 / 摘要不显示 |
| `references/07-scheduling-cloud.md` | 要无人值守、本机不开机也要跑 |
| `references/08-archiving-sync.md` | 要归档到网盘、本地云端合并 |
| `references/09-annual-diff.md` | 要做「同一份报告跨年份对比」 |
| `scripts/*` | 直接跑；也是给别的 AI 抄的骨架 |

---

## 五、★★★ 铁律速查（最高价值 20 条）

> 这些是**踩过的坑**，不是常识。每条都附了判据。

### 反爬与通道

1. **概率性 vs 硬封**：同一 URL 反复请求结果随机 = 概率性 → 重试可解；
   每次都在**同一位置**失败 = 真封。小页（6KB / 473B / 2KB）= 硬封。
2. **「重试越多死得越快」**：Akamai 按**速率**封 IP 段。`node_retries` ≤ 20 且**不连续跑**。
   判断已触发：原本能过 → 现在所有节点都返回同一个固定小体积拒绝页。
3. **本地与云端是互补，不是二选一**：本地节点通道过 Cloudflare，云端海外 IP 过 Akamai/地域限制。
   单靠一边，必有一批站**静默 0 产出而不报错**。
4. **「有内容 + 0 命中」= 改 pattern；「无内容」= 改通道。** 这是最高频的分诊。
5. **节点白名单按站扫、不可跨站复用**。针对 A 站扫出的 65 个节点，换到 B 站可能 **0/36 通过**。
6. **零产物站三分诊**（处置完全相反）：① 节点池对该站无效（不建议盲投时间）
   ② 入口 URL 已变（**改配置就能救，优先做**）③ 站点侧 5xx/连接失败（等站点恢复）。
7. **CF 三档判据**：403 但 `curl_cffi` 通 → `use_cffi:true` 直连省节点；
   cffi 也 403 → 硬 CF，只能上节点；直连 `000` → 先测代理。
8. **「走代理反而被拦」真实存在** → `no_proxy:true`（实测：代理拿 5.5KB 挑战页，直连拿 308KB 真页）。
9. **同机构不同子域反爬完全不同** → 换子域是零成本破局（`www.imf.org` 403 / `elibrary.imf.org` 通）。

### 产物正确性

10. **「存盘但是拦截页」= 最大口径错误**。批量抓完**必跑** `audit_artifacts.py`。
11. **截断判据**：文件有 `%PDF-` 头、大小正常 ≠ 完整 → 尾部 2048 字节**必须找到 `%%EOF`**。
12. **错误页的 `<title>` 是「非空」的**（`400 Bad Request`）→ 会被当正常产物。
    含**软 404** 形态：`404error：站点名`（无空格 + 全角冒号，标准正则漏判）。
13. **通用 PDF 污染**：「PDF 优先」会命中详情页**页脚的全站通用 PDF**（隐私政策、校园地图…）
    → N 个产物**字节全同**。判据：**多篇产物 MD5 是否互异**。
14. **`h1[0]` 常是站点外壳** → 所有详情页同名 → 只落 1 个文件 → 用 `<title>` 取标题。

### 配置与 pattern

15. **`link_pattern` 是正则**：里面的 `?` `+` `|` 会被当量词/分支。要么用 `(?:...)`，要么不用这些字符。
    **写完必须拿真实 HTML 离线 `re.findall` 验证**。
16. **`base_url` 必须与 `link_pattern` 同源**，否则拼出错误主机名（踩过 2 次）。
17. **负向断言要匹配实际文本**：sitemap 里是 `research</loc>`（无尾斜杠），
    写 `(?!research/)` 会**静默失效** → 栏目页混进产物。
18. **`lastmod` 不可信**（实测 99.8% 被批量刷成近期）→ 只用 API 日期或文件名 `YYMMDD`；
    **URL 里的数字 ≠ 日期**（可能是内容 ID）。

### 运维

19. **索引会静默滞后**：`scan_all_reports()` 扫出 11,633 条，`reports_data.json` 只有 2,107。
    判据：`len(reports_data.json)` ≪ 扫描条数 → **抓完必须重建索引**（`build_index.py`，秒级）。
20. **超时是被忽略的杀手**：服务被超时 SIGTERM 杀死，会**伪装成 `EPIPE`**（子进程管道断裂）
    → 极具误导性，别去查 playwright。**判断服务真实健康看 `systemctl status`，别看日志尾部。**

---

## 六、本技能与「碎片技能」的关系

这台机器的每个**难点**，都已经独立成技能。本技能**不重复**它们的细节，只负责：

- 告诉你在**什么阶段**该调用哪个技能；
- 提供**把它们串起来**的编排视角（配置 → 长跑 → 验收 → 消费 → 归档）；
- 提供**可直接运行**的骨架代码，让你不必从零写。

```
research-report-crawler  ← 你在这里（总纲 / 编排 / 骨架）
├─ source-reachability-triage      选源：这批站能不能抓
├─ research-corpus-onboarding      接入：单源配置→长跑→验收
├─ json-api-site-onboarding        SPA 站找官方 API
├─ cloudflare-bypass-diagnosis     CF 403 专项
├─ crawl-artifact-authenticity-audit  产物真伪专项
├─ idempotent-batch-ingest         批量入库幂等
├─ resumable-job-concurrency       断点续跑 + 并发
├─ ai-batch-output-guard           AI 批量产物质检
├─ cjk-corpus-search-pipeline      中文语料检索
├─ html-to-pdf-report-pipeline     HTML→PDF 渲染
└─ smtp-delivery-diagnosis         邮件送达诊断
```

---

## 七、口径纪律（写给用这个技能的 AI）

1. **实测支撑 + 原始数字**。凡「打不通」必附证据（响应体大小 / 状态码 / 命中数）。
2. **证伪手段写清楚**。说「已修好」要给出「怎么证明修好了」。
3. **口径错误比没数据更危险**。宁可标「未知」，不要猜一个数字填上。
4. **付费通道不用**。只抓公开内容；抓到「登录壳」要明确标注，别当成研报。
5. **来源可信度与研究对象地区分开**。一份美国机构写的中国报告，是「美国视角的中国研究」，不是「中国官方数据」。
6. **名字叫「研究报告」≠ 抓到研报**。投行的公开 Insights 栏目 ≠ 卖方 GIR 研报（后者在登录门户后，物理上拿不到）。
   已抓到的要打 `_coverage_grade` 标签。
7. **隔离/清理一律 `shutil.move` 到 `_quarantine_*/`**，绝不 `rm`。
