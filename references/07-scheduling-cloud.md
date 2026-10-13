# 07 · 定时调度与云端协同（无人值守）

> 目标：**本机不开机，云端也能自己抓。**
> 这一篇的核心是「让长任务在无人看管时活下来」。

---

## 一、为什么必须上云端

| 约束 | 后果 |
|---|---|
| **长跑任务跨轮被回收** | 交互式会话里，turn 结束会终止所有子进程 → `nohup ... &` 也活不过下一轮 |
| **本机计划任务被禁** | `schtasks.exe` 在安全策略黑名单里 → 只能用 PowerShell `Get-ScheduledTask` **查**，不能建 |
| **地域限制** | 本地 IP 过不了部分站（加拿大统计局等）→ 必须海外 IP |

→ **结论**：无人值守抓取**交给云端 cron + systemd timer**，本地只负责「过 CF 的站」和「人肉调试」。

---

## 二、★★★ 超时是被忽略的杀手（最贵的一课）

**现象**：日报服务**连续 7 天全败**，日志尾部全是 `EPIPE`（子进程管道断裂）。

**误判方向**：以为是 playwright / 浏览器的问题 → 查了半天没有结果。

**真相**：`TimeoutStartSec=3600`（1 小时）→ 服务 08:00 启动、**09:00 被 SIGTERM 杀死** →
子进程管道断裂 → **表现为 `EPIPE`**。

```ini
# 修好之前
TimeoutStartSec=3600      # 1h → 抓取没跑完就被杀

# 修好之后
TimeoutStartSec=14400     # 4h
```

★★★ **判断服务真实健康看 `systemctl status`，别看日志尾部。**
日志里的 `EPIPE` / 连接中断，很可能是**被杀死的副作用**，不是根因。

**另一条**：`weekly` 任务原定 10:00，与 `daily` 窗口重叠 → 抢内存。
挪到 **14:00** 后正常。

---

## 三、云端任务编排（错峰是刚需）

| 时间 | 任务 | 说明 |
|---|---|---|
| 00:01 | clean | 清理临时文件 |
| 00:05 | disk_guard | 磁盘水位守护 |
| **01:00（周三/六）** | **crawl（timeout 5h）** | 主力全量抓取 |
| **08:00（每天）** | **daily（4h cap）** | 增量抓取 + 日报 |
| 09:00 / 09:05 | 辅助任务 | — |
| 10:00（周三/六） | email | 邮件推送 |
| 14:00（周三/六） | weekly（`all`） | 周报 |
| **22:00–24:00** | **空档** | ★ 留给补跑 / 大站专项 |

★ **错峰的原因**：云端内存小（1.8G）→ 两个带浏览器的任务重叠会 **OOM**。

### systemd timer vs cron

| | cron | systemd timer |
|---|---|---|
| 用途 | 简单周期任务 | 需要超时控制 / 依赖 / 日志归集 |
| 超时 | 无（要自己 `timeout`） | ★ `TimeoutStartSec`（**必须设够**） |
| 判断健康 | 看日志（会撒谎） | ★ `systemctl status`（真相） |

★ **两个 venv 别混**：cron 用的和 systemd 用的可能是**不同的虚拟环境**（依赖不同）。
混用 → 某个任务报「找不到模块」，而另一个任务正常 → 极难定位。

---

## 四、★★★ 本地 ↔ 云端协同

| | 本地（中国） | 云端（海外） |
|---|---|---|
| 强项 | 过 Cloudflare | 过 Akamai / 地域限制 |
| 命令 | `python crawler.py crawl` | `FORCE_HEADLESS=1 venv/bin/python crawler.py crawl` |

### 协同三条铁律

1. **`seen_links.json` 双向合并，绝不按大小覆盖。**
   索引类 JSON（简报 / 摘要 / link_map）**必须按 key 合并**。
   > 事故：一次「按大小覆盖」冲掉 **~800 条 AI 简报** —— 简报只存在 JSON 里，
   > PDF 不注入摘要，**不可恢复**。
2. **两个采集进程必须串行**（同一台机器）—— 不同机器各跑没问题。
3. **`sites_config.json` 两边分别改** —— 两边站数可能不同（本地 185 / 云端 107）
   → **严禁整文件覆盖**。

### `sync pull` 的两个陷阱

| 陷阱 | 说明 |
|---|---|
| **把云端 404 页拉回本地** | 隔离是**本地动作** → pull 会让它**复活** → pull 后重跑一次隔离 |
| **用云端截断版覆盖索引** | 判据：`len(data)` ≪ `scan_all_reports()` → 重跑重建脚本恢复 |

---

## 五、云端环境清单（模板）

| 项 | 值 |
|---|---|
| 服务器 | 海外 VPS（如阿里云韩国），`root` + SSH key |
| 工作目录 | `/root/<项目>` |
| Python | 独立 venv（含 curl_cffi / playwright / chromium） |
| xray | `/usr/local/bin/xray`（过 CF 用） |
| 白名单 | `alive_nodes.json` |
| **必需环境变量** | ★★ **`FORCE_HEADLESS=1`**（云端无 X server，headed 浏览器必崩 `Missing X server or $DISPLAY`） |
| 资源 | 磁盘 / 内存要**持续监控**（见下） |

### 云端三条硬约束

1. **无 X server** → `FORCE_HEADLESS=1`。
   （实测：无头/有头**通过率完全一致**，无副作用。）
2. **资源不足会伪装成「站点不通」** → `Page.goto: Page crashed` 是**内存不足**，不是站点问题。
   判据：换内存大的机器复跑。**内存 < 600M 时不要跑带浏览器的站**。
3. **磁盘紧张** → 不能 push 全量产物（见 08 归档篇的「即推即删」）。

### ★★★ 大文件国际站走云端抓

**实测**：某站 4 个 30~46MB 的 PDF ——
本地直连 **0.1 MB/s** + 代理 TLS 断；**云端直连 7 MB/s**。

→ 大文件走云端，抓完用 **tar 管道**拉回（137MB / 18s，比逐文件 scp 快得多）。

```bash
ssh $HOST "cd /root/proj && tar cf - reports/大站" | tar xf - -C ./
```

---

## 六、SSH 稳定性（踩过的坑）

| 坑 | 现象 | 修复 |
|---|---|---|
| **stdin 管道死锁** | 批次卡死 | 改「临时文件 + scp」，不要 `ssh host "cat > file" < local` |
| **stderr PIPE 阻塞** | `rc=255` | stderr 落文件 + `-o LogLevel=ERROR`（否则 WARNING 撑满 PIPE） |
| **命令被 sshd 截断** | `syntax error: unexpected end of file` | ★ **分块**：目录多时每 60 个目录一次 ssh（否则命令长达数万字符） |
| **路径转换** | 路径被本地 shell 改写 | `MSYS_NO_PATHCONV=1`（Git Bash 环境） |

---

## 七、无人值守的健康检查

```bash
# 1. 服务真实状态（★ 别看日志尾部）
systemctl status report-daily.service
systemctl list-timers

# 2. 磁盘水位
df -h /

# 3. 产物是否在增长（★ 以磁盘产物为准）
find /root/proj/reports -newermt "-1 day" -type f | wc -l
```

★ **验收标准**：不看日志说「跑过了」，看**过去 24h 有没有新产物落盘**。
