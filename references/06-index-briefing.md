# 06 · 索引与看板（抓取 ≠ 上屏）

> 抓完了，文件都在磁盘上，但看板不显示 —— 这不是抓取问题，是**索引层**的问题。

---

## 一、★★★ 索引会静默滞后

**实测**：`scan_all_reports()` 能扫出 **11,633** 条，但 `reports_data.json` 里只有 **2,107** 条。

**判据**：
```python
if len(json.load(open("reports/reports_data.json"))) << scan_all_reports().__len__():
    print("索引滞后，需要重建")
```

**处置**：抓完**必须**重建索引。用**秒级**脚本（只读缓存、跳过慢速 AI 补跑，约 5 秒），
而不是等 `main.py report`（那个要几小时）。

**重建前先备份**（索引 JSON 被覆盖不可恢复）。

---

## 二、★★★ `run_report()` 的结构缺陷（必须知道）

引擎的 `run_report()` 顺序是：

```
① 扫描全部报告
② 加载缓存
③ ★ 逐条调 AI 补摘要     ← 慢：约 1 条/分钟
④ 批量翻译标题
⑤ ★ 生成 HTML 看板        ← 要等 ③ 全部跑完才执行
```

**后果**：2,832 条缺摘要 → 按 1 条/分钟要 **≈47 小时** 才出看板。

**解法：解耦** —— 写一个只读缓存、跳过 ③ 的「秒出看板」脚本：

```python
# build_index.py 的核心：只做 ①②④⑤，跳过 AI 补跑
reports = scan_all_reports(root)          # ①
cache   = load_cache("daily_summaries.json")  # ②
# ③ 跳过（AI 补跑交给后台的 _ai_backfill.py）
html    = render_dashboard(reports, cache)   # ⑤
```

→ **1.3 秒**出看板。AI 摘要由后台进程慢慢补，互不阻塞。

**（更彻底的做法）**：给 `run_report()` 加 `--no-ai` / `--fast` 开关，
或把第 ③ 步挪到第 ⑤ 步之后。

---

## 三、★★★ 两份简报存储（字段名与 key 分隔符都不同）

这是最容易踩的坑：**抓取落的库**和**看板读的库**不是同一个。

| | 抓取落 | 看板读 |
|---|---|---|
| 文件 | `reports/ai_briefings.json` | `reports/daily_summaries.json` |
| 字段 | `title` / `summary` / `highlights` | `title_zh` / `summary_zh` / `highlights_zh` |
| key 分隔符 | `` ` ``（反引号） | `/`（斜杠） |
| 写入 | **带锁原子写** | **无锁** |

**后果**：**抓取完不会自动上屏摘要** —— 只有 `main.py report` 的回填能把两者打通（~1 条/分钟）。

**处置**：用**合并脚本**（默认 dry-run / `--apply`；只补空不覆盖；写前备份）：

```bash
python _merge_briefings_into_cache.py            # dry-run，看会改多少
python _merge_briefings_into_cache.py --apply    # 实测把覆盖率 63% → 93.2%，不重跑 AI
```

★ **key 分隔符不同**是最隐蔽的：直接按 key 合并会**全部 miss**，覆盖率不升反降。

---

## 四、★★★ 索引不截断

索引有个**唯一的截断点**：`MAX_INDEX_REPORTS`。

```python
MAX_INDEX_REPORTS = 0     # ★ 0 = 不截断
```

历史上是 `reports[:5000]` → 「磁盘 7,603 文件」但看板只显示 5,000，
**两个数字都对**，别当成丢数据。

要全量展示 → 把这个常量设为 `0`。

---

## 五、看板/索引的三层产物

| 产物 | 内容 | 大小 |
|---|---|---|
| `reports/每日研报汇总.html` | 看板外壳 | ~19KB（数据在外部 JS） |
| `reports/reports_data.js` | 看板数据 | 数 MB |
| `reports/研报索引.html` | **可检索**索引页（可搜题目） | 十数 MB |

★ 索引页是「全量可搜」，看板是「最新 N 条 + AI 摘要」，**两者用途不同**。

---

## 六、AI 池设计（零成本）

多通道免费池，**按 key 熔断**：

```
Groq → ModelScope → OpenRouter → AgnesAI → NVIDIA → 智谱 → CF → ... → 商汤
```

| 机制 | 说明 |
|---|---|
| 熔断粒度 | **按 key**（不是按通道），失败 → 该 key 冷却 300s |
| 全池日限 | 某些通道全池 50 次/天（按北京 08:00 重置） |
| 失败判据 | ★ 先看 `finish_reason` —— `max_tokens` 太小 = **结构性失败**，不是网络问题 |
| 幂等 | 结果缓存到 JSON；重跑只补未完成的（**缓存必须绑内容指纹**，见 09） |

★ **AI 简报只存在 JSON 里**（PDF 不注入摘要）→ **覆盖不可恢复** → 合并/写入必须：
① 带锁；② 只补空不覆盖；③ 写前备份。

---

## 七、邮件推送

| 机制 | 说明 |
|---|---|
| 水位 | `reports/.last_email_sent.json` 记录上次发送位置 → 只发增量 |
| 内容 | 看板摘要 + 新报告清单 |
| 送达诊断 | 见 `smtp-delivery-diagnosis` 技能 |

---

## 八、诊断清单（「抓完了但看板没变」）

1. `len(reports_data.json)` vs `scan_all_reports()` → 索引滞后？→ 重建
2. 重建后标题在、摘要空 → 两份简报库没打通？→ 合并脚本
3. 数量对但显示不全 → `MAX_INDEX_REPORTS` 截断？
4. 全都对但页面没更新 → 浏览器缓存 / 数据在外部 `.js`（要一起部署）
