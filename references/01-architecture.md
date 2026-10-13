# 01 · 系统架构与配置规范

## 一、设计哲学

**一台「配置驱动」的多站采集机**，而不是 N 个一次性爬虫脚本。

为什么：研报源会长期存在、结构会变、反爬会升级。**一次性脚本的维护成本随站数线性增长**，
配置驱动的系统把「变的部分」压进数据（JSON），代码只负责执行。

三条不可让步的设计约束：

| 约束 | 理由 |
|---|---|
| **一站一条配置** | 改一个站不动代码；新增站只是加一条 JSON |
| **产物落盘即真相** | 所有统计以**磁盘文件**为准，不看日志（日志会撒谎） |
| **所有状态可断点续跑** | 长任务必然被打断（跨轮回收 / 超时 / 崩溃）→ 每个单元独立落盘 |

## 二、目录规范

```
project/
├── crawler.py / main.py          # 采集引擎（CLI 多子命令）
├── sites_config.json             # ★ 唯一真源：一站一条
├── seen_links.json               # 去重台账（纯 URL 列表）
├── reports/                      # 产物根目录
│   └── <大类>/<站名>/<YYMMDD>_<标题>.pdf|html
├── reports/
│   ├── reports_data.json         # 索引（看板读这个）
│   ├── ai_briefings.json         # AI 简报（抓取时落）
│   ├── daily_summaries.json      # AI 简报（看板读）★ 与上面字段名/分隔符都不同
│   ├── 研报索引.html             # 可检索索引页
│   └── 每日研报汇总.html          # 看板
├── _quarantine_<日期>/            # 隔离区（只进不出，绝不 rm）
└── _skill_out/                    # 技能包构建产物
```

**产物命名铁律**：`<YYMMDD>_<标题>.pdf`。

- **日期前缀**是唯一的「按站起始日」回溯手段（文件系统 mtime 不可靠）。
- ★★★ **ID 绝不能进文件名第二段**：`scan_all_reports()` 会把 `_` 转成空格，
  `AP1234567` / `CAICT` / `JAZZY` 这类 ID 进标题会**污染索引标题**。ID 放 metadata，不放文件名。

## 三、配置 schema（`sites_config.json`）

```jsonc
[
  {
    "name": "Fed-美联储",              // 站名（也是 reports/<大类>/<站名>/ 的目录名）
    "category": "宏观经济",             // 大类目录
    "list_url": "https://www.federalreserve.gov/feeds/press_all.xml",

    // —— 抓取形态（见 02-fetch-recipes.md）——
    "use_rss": true,
    "link_pattern": "<link>(https://[^<]+)</link>",

    // —— 通道与反爬 ——
    "via_node": false,                 // true=先节点 / false=从不 / 缺省=auto(直连被拦才回退)
    "use_cffi": false,                 // curl_cffi 浏览器 TLS 指纹（过 CF TLS 层）
    "use_js": false,                   // 需要真浏览器渲染（SPA）
    "js_wait_ms": 3000,
    "no_proxy": false,                 // 强制直连（治「走代理反而被拦」）
    "node_retries": 8,                 // ★ Akamai 型 ≤20

    // —— 详情页取 PDF ——
    "pdf_pattern": "href=\"([^\"]+\\.pdf)\"",
    "pdf_only": true,                  // 只要 PDF，不要 HTML
    "pdf_same_host_only": true,        // PDF 必须同主机（防页脚通用 PDF 污染）
    "use_aria2": false,                // 大文件多连接下载

    // —— 标题清洗 ——
    "title_from": "title",             // h1[0] 是站点外壳时改从 <title> 取
    "title_strip_prefix": "站点名_",     // 剥掉 JS 壳页标题前缀（防撞名）
    "title_skip": ["Skip to main"],

    // —— 多页列表 ——
    "list_urls": [".../page/1", ".../page/2"],   // 多页枚举，合并后统一跑 pattern
    "list_url": ".../page/1",          // ★ list_urls 站**必须同时保留 list_url**（引擎硬用，缺则崩）

    // —— 链接改写 ——
    "link_rewrite": ["<regex>", "<replacement>"],  // 详情链接 → PDF 直链

    // —— 口径 ——
    "_coverage_grade": "公开Insights·非卖方GIR研报"
  }
]
```

### ★★★ 写配置前必做

```bash
grep '"键名"' crawler.py     # 0 次命中 = 这个键无效（引擎根本不读它）
```

配置里的键如果引擎不读，你写上去**不会有任何报错**，只会静默不生效。

### `via_node` 的语义（重要）

| 值 | 行为 | 何时用 |
|---|---|---|
| `true` | **先**走节点通道 | 已知被 CF/Akamai 拦死 |
| `false` | **从不**走节点 | 直连就通的站；**这类站可并行**（不碰节点端口） |
| 缺省 | `auto`：直连被拦才回退节点 | 默认；但**每站会多一次超时等待** |

★ `false` 的站不占用节点端口（20600-20605），因此**只有它们能并行**。
带节点的站**必须串行** —— 两个进程会抢同一份节点配置。

## 四、引擎 CLI（参考实现的命令面）

```bash
python crawler.py all              # 全流程：同步 → 抓取 → AI 分析 → 看板 → 邮件
python crawler.py crawl            # 只抓取
python crawler.py crawl --only "Fed"   # 只跑一个站（★ 子串匹配，且只能一个）
python crawler.py retry            # 重跑失败队列
python crawler.py report           # 生成看板（★ 慢：会逐条补 AI 摘要）
python crawler.py sync             # 与云端双向同步
python crawler.py email            # 发邮件
python crawler.py status           # 系统状态
python crawler.py doctor           # 配置体检（pattern 命中数，0 命中报警）
```

## 五、并发模型

| 场景 | 能否并行 | 原因 |
|---|---|---|
| `via_node:false` 的站之间 | ✅ 可以 | 不碰节点端口 |
| 带节点的站之间 | ❌ 禁止 | 抢 `cf_fetch_config_20600.json` |
| 两个 `crawl` 进程 | ❌ 禁止 | `save_seen()` **无文件锁** → 互相覆盖 `seen_links.json` |
| `build_index.py` 与 `crawl` | ✅ 可以 | 一个只读缓存，一个写另一个库 |
| 两个 AI 补跑进程 | ❌ 禁止 | `save_cache()` 无锁 → 覆盖 `daily_summaries.json`（不可恢复） |

★★★ **一条命令里的长跑任务在本环境跨轮会被回收**（turn 结束即杀子进程）→
通宵任务必须交**系统定时任务**（cron / systemd timer），不能靠 `nohup &`。

## 六、失败的自愈设计

| 失败 | 自愈机制 |
|---|---|
| 单站卡死拖死全量 | **逐站限时**：`timeout 150 python crawler.py crawl --only "<完整站名>"` |
| 长任务被中断 | 每个单元独立落盘 + `.done` 标记 → 重跑只补未完成 |
| 进程被杀留孤儿 | 启动前扫端口 20600-20605，清理孤儿节点进程 |
| 抓了一半崩溃 | `seen` 只在**成功后**写；未写完的不记账 → 下轮重抓（幂等） |
| 云端 404 页被拉回本地 | `sync pull` 后重跑一次隔离脚本（隔离是本地动作，pull 会让它复活） |

★ 单站限时是**必须**的：实测 JPMorgan 单站抓了 **2h47min**，把整个全量任务拖死。
