# 每日 GNSS/SLAM 公众号自动化说明

本文档说明当前项目已经实现的功能、每日定时发送的实现方式，以及后续如何修改运行时间和运行模式。

## 1. 当前已经实现的功能

项目围绕 GNSS 欺骗/干扰检测、多模态融合、SLAM/里程计三类方向，自动完成从论文检索、选题推荐、文章生成、微信公众号草稿创建、邮件提醒到 GitHub 归档的一整套流程。

主要功能如下：

1. 每日论文检索  
   从 arXiv 检索 GNSS spoofing/jamming detection、多模态融合、SLAM/odometry 相关论文。

2. 文章选题排序  
   对候选论文做去重和质量排序，综合考虑主题相关性、发布时间、引用线索、会议/期刊线索、代码开源线索等因素。

3. 每日推荐公众号文章  
   生成每日论文推荐文章，输出 Markdown、HTML、JSON，并可上传正文图片、创建微信公众号草稿。

4. 单篇论文解读文章  
   自动下载论文 PDF，提取论文中的关键图，生成更详细的论文解读文章，并创建微信公众号草稿。

5. 论文图作为封面  
   单篇论文解读会优先从 PDF 中选择 framework、architecture、pipeline、system 等流程图或框架图，作为公众号草稿封面和正文主图。

6. 周报热点汇总  
   每周自动生成热点方向汇总，包含方向趋势、高频关键词、有代码/复现线索和本周值得追的论文。

7. 邮件提醒  
   每日总控默认只发送最后一封总结邮件，避免每篇文章分别发邮件。邮件中包含公众号后台草稿箱入口、GitHub commit、运行步骤和最近日志。

8. GitHub 自动归档  
   每天生成的最终文章、正文图、配置代码会自动 commit 并 push 到 GitHub。`.env`、日志、论文 PDF 和中间缓存不会提交。

9. macOS 每日定时执行  
   通过 macOS `launchd` 安装系统级定时任务，每天自动调用总控脚本。

## 2. 核心脚本说明

| 脚本 | 作用 |
| --- | --- |
| `scripts/daily_automation.sh` | 每日自动化总控入口 |
| `scripts/install_daily_launchd.sh` | 安装或更新 macOS 每日定时任务 |
| `scripts/publish_now.sh` | 生成每日推荐文章，并按模式创建公众号草稿或提交发布 |
| `scripts/generate_deepdives.sh` | 生成单篇论文解读文章，并按模式创建公众号草稿或提交发布 |
| `scripts/generate_weekly_summary.sh` | 生成每周热点方向汇总 |
| `scripts/upload_cover_to_wechat.py` | 上传公众号封面素材，并写入 `.env` |
| `scripts/make_wechat_cover.py` | 制作公众号封面图 |

## 3. 每日自动化是怎么运行的

每日自动化入口是：

```bash
./scripts/daily_automation.sh
```

这个脚本会按顺序执行：

1. 读取 `.env` 配置。
2. 设置当天日期、输出目录、日志文件。
3. 加运行锁，避免多个定时任务同时执行。
4. 检查 PDF 图文提取依赖是否存在。
5. 生成每日推荐文章并创建公众号草稿。
6. 基于每日推荐列表生成单篇论文解读草稿。
7. 如果当天是配置的周报日，生成周报热点汇总。
8. 把生成结果提交并推送到 GitHub。
9. 发送一封自动化总结邮件。

当前默认模式是：

```bash
AUTOMATION_WECHAT_MODE=draft
AUTOMATION_DEEPDIVE_MODE=draft
```

也就是说，脚本会自动创建公众号草稿，但不会直接正式发布。

## 4. 每日定时是怎么实现的

项目使用 macOS 自带的 `launchd` 做每日定时任务，不需要 Python 程序常驻后台。

安装命令是：

```bash
./scripts/install_daily_launchd.sh 20:45
```

它会生成或更新这个文件：

```text
~/Library/LaunchAgents/com.codex.daily-gnss-slam-digest.plist
```

这个 plist 中的核心配置是：

```xml
<key>StartCalendarInterval</key>
<dict>
  <key>Hour</key>
  <integer>20</integer>
  <key>Minute</key>
  <integer>45</integer>
</dict>
```

到每天 `20:45` 时，macOS 会自动执行：

```bash
/Users/wangzhibo/Documents/Codex/2026-07-03/wo/scripts/daily_automation.sh
```

当前项目默认时间是每天晚上 `20:45`。

## 5. 周报什么时候生成和提醒

周报没有单独的定时器，它挂在每日自动化总控里。

当前配置是：

```bash
AUTOMATION_TIME=20:45
WEEKLY_SUMMARY_ENABLED=1
WEEKLY_SUMMARY_DAY=5
WEEKLY_SUMMARY_DAYS=7
```

含义是：

- 每天晚上 `20:45` 运行一次总控脚本。
- 如果当天是 `WEEKLY_SUMMARY_DAY` 指定的星期，就额外生成周报。
- `WEEKLY_SUMMARY_DAY=5` 表示周五。
- `WEEKLY_SUMMARY_DAYS=7` 表示汇总最近 7 天的日报候选论文。

所以当前周报会在每周五晚上 `20:45` 这次自动化中生成，并在最后那封“每日 GNSS/SLAM 自动化总结邮件”里体现运行结果。周报文件会写入：

```text
outputs/weekly/
```

`WEEKLY_SUMMARY_DAY` 使用 ISO 星期数字：

| 数值 | 星期 |
| --- | --- |
| `1` | 周一 |
| `2` | 周二 |
| `3` | 周三 |
| `4` | 周四 |
| `5` | 周五 |
| `6` | 周六 |
| `7` | 周日 |

如果想改成周日晚上生成周报：

```bash
WEEKLY_SUMMARY_DAY=7
```

如果想关闭周报：

```bash
WEEKLY_SUMMARY_ENABLED=0
```

## 6. 如何修改每日运行时间

时间格式是 `HH:MM`，例如 `21:30`、`08:15`、`23:45`。

推荐做法：

1. 修改 `.env`：

```bash
AUTOMATION_TIME=21:30
```

2. 重新安装定时任务：

```bash
./scripts/install_daily_launchd.sh
```

如果只是想立刻改系统定时任务，也可以直接运行：

```bash
./scripts/install_daily_launchd.sh 21:30
```

注意：只改 `.env` 不会自动刷新已经安装好的 `launchd` 定时器。改完时间后，必须重新运行一次 `scripts/install_daily_launchd.sh`。

## 7. 如何手动运行

手动跑完整每日自动化：

```bash
./scripts/daily_automation.sh
```

手动触发已经安装好的 launchd 定时任务：

```bash
launchctl kickstart -k gui/$(id -u)/com.codex.daily-gnss-slam-digest
```

只生成每日推荐公众号草稿：

```bash
./scripts/publish_now.sh draft
```

只生成单篇论文解读草稿：

```bash
./scripts/generate_deepdives.sh draft
```

只生成本周热点汇总：

```bash
./scripts/generate_weekly_summary.sh
```

## 8. 运行模式说明

`AUTOMATION_WECHAT_MODE` 和 `AUTOMATION_DEEPDIVE_MODE` 支持三个值：

| 模式 | 含义 |
| --- | --- |
| `none` | 只生成本地文章，不创建公众号草稿 |
| `draft` | 创建公众号草稿，不正式发布 |
| `publish` | 先创建草稿，再尝试提交正式发布 |

当前建议保持：

```bash
AUTOMATION_WECHAT_MODE=draft
AUTOMATION_DEEPDIVE_MODE=draft
```

因为微信公众号正式发布接口 `freepublish` 需要账号具备对应权限。如果没有权限，`publish` 可能返回 `48001 api unauthorized`。这种情况下草稿仍会保留，可以到公众号后台手动发布。

## 9. 邮件提醒逻辑

邮件配置在 `.env` 中：

```bash
EMAIL_NOTIFY_ENABLED=1
EMAIL_NOTIFY_TO=your@email.com
SMTP_HOST=smtp.qq.com
SMTP_PORT=587
SMTP_USERNAME=your@email.com
SMTP_PASSWORD=your_smtp_authorization_code
SMTP_FROM=your@email.com
SMTP_USE_TLS=1
SMTP_USE_SSL=0
```

每日总控脚本会自动设置：

```bash
EMAIL_NOTIFY_SUPPRESS_STEP_MESSAGES=1
```

这样做的效果是：

- 定时总控运行时，只发最后一封自动化总结邮件。
- 手动单独运行 `generate_deepdives.sh draft` 时，会把多篇论文草稿合并成一封汇总邮件。
- 如果想调试每个子步骤的邮件提醒，可以在 `.env` 中显式设置：

```bash
EMAIL_NOTIFY_SUPPRESS_STEP_MESSAGES=0
```

## 10. 输出文件和日志

每日推荐文章输出在：

```text
outputs/
```

单篇论文解读输出在：

```text
outputs/deepdives/
```

每周热点汇总输出在：

```text
outputs/weekly/
```

自动化日志输出在：

```text
outputs/logs/
```

launchd 的标准输出和错误日志分别是：

```text
outputs/logs/launchd.out.log
outputs/logs/launchd.err.log
```

## 11. 常见问题

### 11.1 改了 `.env` 时间，为什么没有按新时间跑？

因为 `.env` 只是项目配置，系统定时任务已经被写入 `~/Library/LaunchAgents/`。改完 `.env` 后，需要重新运行：

```bash
./scripts/install_daily_launchd.sh
```

### 11.2 微信接口报 IP 白名单错误怎么办？

微信公众号 API 要求当前公网 IP 在公众号后台的 IP 白名单中。报错类似：

```text
invalid ip xxx.xxx.xxx.xxx, not in whitelist
```

解决方式是在公众号后台的“安全中心 / IP 白名单”里加入当前脚本运行机器的公网 IP。

### 11.3 为什么没有直接正式发布？

当前默认是 `draft` 模式，只创建草稿，不正式发布。这样更安全，可以先人工检查排版、封面和图片。

如果要尝试提交正式发布，可以把模式改成：

```bash
AUTOMATION_WECHAT_MODE=publish
AUTOMATION_DEEPDIVE_MODE=publish
```

但前提是公众号账号具备 `freepublish` 接口权限。

### 11.4 怎么确认定时任务已经安装？

重新运行安装脚本后，如果看到类似输出，说明已经安装：

```text
Installed launchd job: com.codex.daily-gnss-slam-digest
Schedule: daily at 20:45
```

也可以手动触发一次：

```bash
launchctl kickstart -k gui/$(id -u)/com.codex.daily-gnss-slam-digest
```

### 11.5 GitHub 没有提交怎么办？

检查以下配置：

```bash
GITHUB_REPO_URL=git@github.com:your-name/your-repo.git
GITHUB_BRANCH=master
GIT_AUTHOR_NAME="GNSS Paper Bot"
GIT_AUTHOR_EMAIL=your@email.com
```

如果当天没有生成新内容，脚本会显示没有文件需要提交，这是正常情况。
