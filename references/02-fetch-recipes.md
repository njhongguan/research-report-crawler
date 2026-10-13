# 02 · 抓取形态与配置模板

引擎只支持「两层」结构，但有 6 种落地形态。**先选对形态，再写 pattern。**

| # | 形态 | 触发键 | 适用 | 一句话判据 |
|---|---|---|---|---|
| 1 | **列表页 → 详情页** | `list_url` + `link_pattern` + `pdf_pattern` | 最常用 | 列表页有文章链接，PDF 在详情页 |
| 2 | **列表页 → PDF 直链** | `list_url` + `link_pattern`（含 `.pdf`） | 列表直接给 PDF | 列表页 href 就是 `.pdf` |
| 3 | **sitemap → 详情页** | `list_url`=sitemap + `link_pattern`=`<loc>` | 无分页的老站 | 站大、无列表页、有 sitemap |
| 4 | **RSS / Atom** | `use_rss:true` + `list_url`=feed | 只给最近条目 | ★ 只给 10~50 条，**拿不到半年** |
| 5 | **直接是 PDF** | `direct_pdf:true` | 单一固定 PDF | `list_url` 本身就是 PDF |
| 6 | **JSON / XML 源** | `use_text:true` | WP REST API 等 | 返回的是 JSON 不是 HTML |

★★★ **能力边界**：只支持「HTML 列表 → HTML 详情」两层。
**不支持「JSON 列表 → JSON 详情」**（如 EIB、IMF-eLibrary 这类）→ 必须写**专用脚本**，
专用脚本**复用引擎函数，不改引擎**（例：`_eib_crawl.py`）。

---

## 形态 1 · 列表页 → 详情页（最常用）

```jsonc
{
  "name": "机构名",
  "category": "大类",
  "base_url": "https://www.example.org",
  "list_url": "https://www.example.org/research/",
  "link_pattern": "href=\"(/research/[a-z0-9-]{20,}/)\"",
  "pdf_pattern": "href=\"([^\"]+\\.pdf)\"",
  "pdf_only": true,
  "pdf_same_host_only": true
}
```

**要点**：
- `base_url` **必须与 `link_pattern` 同源** —— 它负责把相对链接拼成绝对链接。拼错主机名 → 全站 404。
- `link_pattern` 里只留 **1 个捕获组**（就是链接本身）。
- 收紧到**站点内容路径**（`/research/`、`/publications/`），否则栏目页/导航页会混进来。

## 形态 2 · 列表页 → PDF 直链

```jsonc
{
  "list_url": "https://www.example.org/reports/",
  "link_pattern": "href=\"([^\"]+\\.pdf)\"",
  "direct_pdf": false
}
```
★ 若列表页同时有 `.pdf` 和文章链接，用**排除法**只留 PDF：`href=\"((?![^"]*#)[^"]+\\.pdf)\"`。

## 形态 3 · sitemap → 详情页

```jsonc
{
  "list_url": "https://www.example.org/sitemap.xml",
  "link_pattern": "<loc>(https://www\\.example\\.org/publications/[^<]+)</loc>",
  "use_text": true,          // ★★★ XML sitemap 走节点必须 true，否则 Chrome 渲染树视图 → <loc> 0 命中
  "pdf_pattern": "href=\"([^\"]+\\.pdf)\""
}
```

**要点**：
- ★★★ **`use_text:true` 是硬要求**。走浏览器渲染 XML 会拿到「树视图」，`<loc>` 一个都匹配不到。
- ★★★ **`link_pattern` 必须捕获完整路径**（含 `/publications/`）。只捕 slug → `urljoin` 缺段 → 软 404。
- ★★★ **`lastmod` 不可信**（实测 99.8% 被刷成近期）→ **不做日期过滤**，靠 `seen` 去重即可。
- sitemap 地址不一定是 `.xml`：实测某站是 `/sitemap/`（`.xml` 反而 404）。

## 形态 4 · RSS / Atom

```jsonc
{
  "list_url": "https://www.example.org/feed/",
  "use_rss": true,
  "link_pattern": "<link>(https://[^<]+)</link>"
}
```

★★★ **RSS 只给最近 10~50 条**。要半年以上的存量，**必须换 sitemap**。
★★★ **「RSS 格式合法 + 条目数 > 0」≠ feed 能用**：实测某站 `/rss.xml` 是**全站 feed**，
链接是 `/node/<id>`、内容是栏目页。**必须实抓打印前 3 条的 `link` + `title` 看内容**。

## 形态 5 · 直接是 PDF

```jsonc
{ "list_url": "https://www.example.org/annual-report.pdf", "direct_pdf": true }
```

## 形态 6 · JSON / XML 源

```jsonc
{
  "list_url": "https://www.example.org/wp-json/wp/v2/posts?per_page=50",
  "use_text": true,
  "link_pattern": "\"link\":\"(https://[^\"]+)\""
}
```
★ JSON 里的 `\/` 转义要处理；分页要**按返回条数推进**而不是按 `limit` 猜
（实测 `limit=50` 只回 23 条，按 50 推会**跳 27 篇**）。

---

## 辅助键速查

| 键 | 作用 | 典型场景 |
|---|---|---|
| `base_url` | 拼相对链接 | ★ 必须与 `link_pattern` 同源 |
| `use_js` + `js_wait_ms` | 真浏览器渲染 | SPA 站 |
| `via_node` | 通道选择 | `true`/`false`/缺省 auto |
| `use_cffi` | curl_cffi TLS 指纹 | CF TLS 层 |
| `no_proxy` | 强制直连 | 「走代理反而被拦」 |
| `title_from:"title"` | 改从 `<title>` 取标题 | `h1[0]` 是站点外壳 |
| `title_strip_prefix` | 剥标题前缀 | JS 壳页标题 = `站点名_slug` |
| `title_skip` | 跳过词 | 站点级 `<h1>` 噪声 |
| `link_rewrite` | 链接改写 | 详情链接 → PDF 直链（NBER 用） |
| `list_urls` | 多页枚举 | 分页列表；★ **必须同时保留 `list_url`** |
| `pdf_only` | 只要 PDF | 默认 |
| `pdf_same_host_only` | PDF 限同主机 | 防页脚通用 PDF 污染 |
| `use_aria2` | 多连接下载 | 大文件（★ `no_proxy` 对 aria2 原无效，需 `--all-proxy=` 空值） |
| `node_retries` | 节点重试次数 | ★ Akamai 型 ≤20 |

---

## ★★★ pattern 写法的五个坑

1. **`link_pattern` 是正则**（`re.search`），里面的 `?` `+` `|` 会被当**量词/分支**。
   要么用 `(?:...)` 分组，要么不用这些字符。
   > 实证：旧 pattern `/research/` 里没转义，其实把 `h` 变成了「可重复」→ 量词膨胀必然匹配错误。
2. **必须容忍相对与绝对 href**：`href="(/path)"` 与 `href="(https://host/path)"` 都要能匹配。
   别锚定引号太死。
3. **`href="  /path"` 空白陷阱**：属性值前面有空格 → 锚定引号的 pattern **必然 0 命中**。
   → **pattern 不锚定引号，直接匹配 URL 形态**。
4. **负向断言要匹配实际文本**：sitemap 里是 `research</loc>`（**无尾斜杠**），
   写 `(?!research/)` 会**静默失效**。改成 `(?!research)</loc>`。
5. **`/wp-content/uploads/YYYY/MM/` 污染日期段**：日期 pattern 别假设路径里第一段数字就是年份。

### ★★★ 写完必跑离线校验（30 秒，省 2 小时）

```python
import re, urllib.request
html = urllib.request.urlopen(LIST_URL, timeout=30).read().decode("utf-8", "ignore")
hits = re.findall(LINK_PATTERN, html)
print("命中:", len(hits))
for h in hits[:3]:
    print("  ", h)
```
- **命中 0** → pattern 错（不是站点错）。
- **命中很多但都是导航/栏目页** → 收紧路径。
- 这一步叫「离线模拟闸门」，**任何新配置上线前都要过**。
