# 05 · 新站接入铁律

> 目标：**一站一条配置，从 0 到有产物**。这一篇是「写配置时的检查表」。

---

## 一、接入流程（7 步）

```
1. 探测可达性        → 直连/代理/节点三通道各测一次，记录【响应体大小】
2. 找入口            → 官方 API > RSS/Atom > 静态 JSON > sitemap.xml > HTML 列表页
3. 离线验 pattern    → re.findall 数命中 + 打印前 3 条（0 命中 = pattern 错）
4. 写配置            → 见 02-fetch-recipes.md 的 6 种形态
5. 单站试跑          → --only "<站名>" --limit 3
6. 产物真伪审计      → audit_artifacts.py（4 类静默污染）
7. 入队              → 全量跑 + 逐站限时
```

★ **第 3 步不能跳**。它花 30 秒，能省 2 小时。

---

## 二、★★★ 十二条铁律（全部踩过）

### 1. `title_strip_prefix` —— 防撞名
JS 壳页的 `<title>` = `站点名_slug` → 截断到 80 字符后**全是站名** → 所有详情页撞名。
> 实证：某站 784 个链接最终只落 **19 个文件**。

### 2. XML sitemap 走节点必须 `use_text: true`
否则 Chrome 渲染成「树视图」，`<loc>` **0 命中**。

### 3. 「走代理被拦、直连反而通」→ `no_proxy:true`
代理不是默认更好的通道，是**要验证的变量**。

### 4. pattern 必须容忍相对与绝对 href
`href="/path"` 与 `href="https://host/path"` 都要能匹配。

### 5. `href="  /path"` 空白陷阱
属性值前有空格 → 锚定引号的 pattern **必然 0 命中**
→ **pattern 不锚定引号，直接匹配 URL 形态**。

### 6. `/wp-content/uploads/YYYY/MM/` 污染日期段
日期 pattern 别假设路径里第一段数字就是年份。

### 7. CF 三档判据（先试 cffi 再占节点通道）
| 情况 | 判据 | 处置 |
|---|---|---|
| 403 但 `cffi_get` 通 | — | `use_cffi:true`（省节点） |
| 连 cffi 也 403 | — | 硬 CF，只能节点 |
| 直连 `000` | — | 测代理 |

### 8. 子域绕主域反爬
`news.fnal.gov` / `newscenter.lbl.gov` 直连通，主域硬 CF。
**同机构不同子域反爬完全不同** → 换子域是零成本破局。

### 9. RSS 是全站 feed ≠ 新闻 feed
**必须打印前 3 条的 `link` + `title` 看内容**。
> 实证：某站 `/rss.xml` 是全站 feed，链接为 `/node/<id>`、内容是栏目页。

### 10. `list_urls` 站必须同时保留 `list_url`
引擎在多处**硬用 `list_url`**（如 `main.py:1820/1891`）→ 缺了直接 `KeyError` 崩。
**现有 17 个 `list_urls` 站全都保留了 `list_url`**。

### 11. 必须串行（两进程覆盖不可恢复）
同一台机器上两个采集进程会抢节点配置 + 覆盖 `seen_links.json`。

### 12. 合规红线
**不抓**：涉及政治敏感、需要绕过登录/付费墙的内容。
**付费通道不用**。投行的公开 Insights 可以抓，但要打 `_coverage_grade` 标签。

---

## 三、★ gov.uk 类组织 Atom feed 的坑

```
/ government / organisations / <org>.atom        ✅ 可用
/ government / organisations / <org>.atom?page=2 ❌ 无效（分页参数无效）
```
其 xlsx/ods 不能抓（白名单只认 pdf/html）。

---

## 四、投行/咨询类的**口径**问题（不是技术问题）

> **名字叫「研究报告」≠ 抓到研报。**

| 机构门户 | 实测可达性 | 结论 |
|---|---|---|
| GS Marquee | `200`（**488 字节**登录壳） | ❌ 需签约客户 |
| MS Matrix | `000`（连不上） | ❌ 内部网络 |
| JPM Markets | `200`（**1,576 字节**登录壳） | ❌ 需机构账号 |
| Citi Velocity | `200`（研报区 **401**） | ❌ 需机构账号 |
| UBS Neo | `200`（**1,267 字节**登录壳） | ❌ 需机构账号 |

→ **卖方 GIR 研报在物理/合规上就不在公开网上**，这不是抓取能力问题。

**正确做法**：抓它们的**公开 Insights / 观点栏目**，并统一打标签：
```jsonc
"_coverage_grade": "公开Insights·非卖方GIR研报"
```

**同时要收紧 pattern**：某投行原命中 302 条，其中 282 条是**企业营销页**
（`real-estate` / `banking` / `payments` / `treasury` 全是产品栏目）；
真正的研究只有 `global-research` + `markets-and-economy` → 新 pattern 只留这两类，命中 70 条。

**教训**：`link_pattern` 的负向断言要匹配**实际文本** ——
写 `(?!research/)` 带尾斜杠，但 sitemap 里是 `research</loc>`（**无尾斜杠**）→ 断言失效，
栏目页混进产物。改成 `(?!research)</loc>` 才正确。

---

## 五、sitemap 探测顺序（「sitemap 不可用」≠「站点不可用」）

```
robots.txt  →  sitemap（地址可能不是 .xml，可能是 /sitemap/）
            →  页面 JS 里的 API 配置（★ 很多站把 API 地址写在前端代码里）
            →  专用脚本
```

★ 若 sitemap 能列出 URL 但没有日期字段 → **不要做日期过滤**，
靠 `seen` 去重（首次全量、之后增量）。

---

## 六、文件命名铁律（复习）

| 规则 | 原因 |
|---|---|
| 产物名 = `<YYMMDD>_<标题>.pdf` | 日期前缀是唯一「按站起始日」回溯手段 |
| **ID 不进文件名第二段** | `scan_all_reports()` 把 `_`→空格 → **污染索引标题** |
| 空标题跳过 + `seen.discard()` | 否则产生占位垃圾 |
| 标题含非法字符要 `safe_name()` | Windows 文件名限制 |

---

## 七、新站入队前的最小检查清单

- [ ] 探测记录：直连/代理/节点三通道的**响应体大小**
- [ ] 离线 `re.findall` 命中数 > 0，且前 3 条是**内容页不是导航页**
- [ ] `base_url` 与 `link_pattern` **同源**
- [ ] pattern 里没有裸的 `?` `+` `|`（或已用 `(?:...)` 包裹）
- [ ] `grep '"键名"' crawler.py` 确认每个键都被引擎读取
- [ ] 单站试跑 ≥ 3 个产物
- [ ] 抽查 2 篇产物 **MD5 互异**（防通用 PDF 污染）
- [ ] 跑一次 `audit_artifacts.py`，0 命中
