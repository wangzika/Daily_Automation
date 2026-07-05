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

5. 论文图作为封面和章节图组  
   单篇论文解读会优先从 PDF 中选择 framework、architecture、pipeline、system 等流程图或框架图作为公众号草稿封面；正文图片会按 Introduction、Method、Experiments 分章节组图，并过滤纯黑、纯白或低信息量抽图。

6. 周报热点汇总  
   每周自动生成热点方向汇总，包含方向趋势、高频关键词、有代码/复现线索和本周值得追的论文。

7. 邮件提醒  
   每日总控默认只发送最后一封总结邮件，避免每篇文章分别发邮件。邮件中只保留公众号后台草稿箱入口、GitHub commit、运行步骤和日志路径，失败时才附少量日志摘录。

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
| `scripts/process_email_commands.sh` | 手动读取邮箱里的论文生成指令 |
| `scripts/install_email_command_launchd.sh` | 安装定时读取邮箱指令的 launchd 任务 |
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
./scripts/install_daily_launchd.sh 09:00
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
  <integer>9</integer>
  <key>Minute</key>
  <integer>0</integer>
</dict>
```

到每天 `09:00` 时，macOS 会自动执行：

```bash
<项目目录>/scripts/daily_automation.sh
```

当前项目默认时间是每天 `09:00`。

## 4.1 arXiv 限流和备用源

自动化会优先使用 arXiv API。为了减少 `429 Too Many Requests`，日报生成现在会：

1. 把原始 arXiv API 响应缓存到 `ARXIV_CACHE_DIR`。
2. 同一主题在 `ARXIV_CACHE_TTL_HOURS` 内重复执行时直接读缓存。
3. arXiv 超时或返回 429 时按更长间隔退避。
4. 如果线上请求失败但本地有旧缓存，先用旧缓存继续生成。
5. 如果 arXiv 完全不可用，按 `PAPER_FALLBACK_SOURCES` 使用备用源。

推荐配置：

```bash
DIGEST_PER_TOPIC=10
ARXIV_RETRIES=3
ARXIV_RETRY_DELAY_SECONDS=10.0
ARXIV_MIN_DELAY_SECONDS=3.5
ARXIV_CACHE_DIR=outputs/cache/arxiv
ARXIV_CACHE_TTL_HOURS=26
PAPER_FALLBACK_SOURCES=semantic-scholar,openalex,crossref,existing-json
SEMANTIC_SCHOLAR_SEARCH_LIMIT=25
OPENALEX_SEARCH_LIMIT=25
OPENALEX_DELAY_SECONDS=1.0
OPENALEX_MAILTO=
CROSSREF_SEARCH_LIMIT=25
CROSSREF_DELAY_SECONDS=1.0
CROSSREF_MAILTO=
```

备用源含义：

- `semantic-scholar`：arXiv 不可用时，用 Semantic Scholar Graph API 搜索同主题论文。
- `openalex`：Semantic Scholar 不可用或没有强匹配时，用 OpenAlex Works API 搜索。
- `crossref`：继续没有结果时，用 Crossref Works API 补充 DOI/期刊会议元数据。
- `existing-json`：如果外部接口都不可用，用当天已有日报 JSON 重新按当前主题过滤并排版。
- `off`：关闭备用源，arXiv 失败就直接失败。

`OPENALEX_MAILTO` 和 `CROSSREF_MAILTO` 可以填通知邮箱，公开 API 会更容易把请求归入礼貌访问池。

## 5. 周报什么时候生成和提醒

周报没有单独的定时器，它挂在每日自动化总控里。

当前配置是：

```bash
AUTOMATION_TIME=09:00
AUTOMATION_PYTHON=/Users/wangzhibo/miniconda3/bin/python
WEEKLY_SUMMARY_ENABLED=1
WEEKLY_SUMMARY_DAY=7
WEEKLY_SUMMARY_DAYS=7
```

含义是：

- 每天 `09:00` 运行一次总控脚本。
- `AUTOMATION_PYTHON` 指定 launchd 使用的 Python，避免系统 Python 缺少 Pillow 等依赖。
- 如果当天是 `WEEKLY_SUMMARY_DAY` 指定的星期，就额外生成周报。
- `WEEKLY_SUMMARY_DAY=7` 表示周日。
- `WEEKLY_SUMMARY_DAYS=7` 表示汇总最近 7 天的日报候选论文。

所以当前周报会在每周日 `09:00` 这次自动化中生成，并在最后那封“每日 GNSS/SLAM 自动化总结邮件”里体现运行结果。周报文件会写入：

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

如果想改成周五生成周报：

```bash
WEEKLY_SUMMARY_DAY=5
```

如果想关闭周报：

```bash
WEEKLY_SUMMARY_ENABLED=0
```

## 6. 每日论文主题轮换

默认开启：

```bash
TOPIC_ROTATION_ENABLED=on
```

没有邮件关键词时，日报不再每天固定检索同一组三大主题，而是按 ISO 星期轮换 7 个导航定位热点方向：

| 星期 | 轮换主题 | 主要检索线索 |
| --- | --- | --- |
| 周一 | 具身导航与机器人基础模型 | embodied navigation、VLM/VLA navigation、object navigation、navigation foundation model |
| 周二 | 3DGS/NeRF 神经场 SLAM | 3D Gaussian Splatting、NeRF SLAM、neural implicit SLAM、dense visual SLAM |
| 周三 | 开放词汇语义地图与语言导航 | open-vocabulary mapping、semantic mapping、language-guided navigation、scene graph |
| 周四 | 地点识别与长期定位 | visual/LiDAR place recognition、loop closure、long-term localization、re-localization |
| 周五 | 多机器人协同 SLAM 与分布式建图 | multi-robot SLAM、collaborative SLAM、distributed mapping、cooperative localization |
| 周六 | 韧性 PNT 与 GNSS 抗欺骗抗干扰 | resilient PNT、GNSS spoofing/jamming、OSNMA、LEO PNT、GNSS denied |
| 周日 | 退化场景多模态融合与鲁棒里程计 | LiDAR-inertial、visual-inertial、factor graph fusion、degeneracy-aware odometry |

执行优先级：

1. 邮件指令或命令行传入 `关键词` 时，优先使用这些关键词。
2. 没有自定义关键词且 `TOPIC_ROTATION_ENABLED=on` 时，使用当天轮换主题。
3. 如果当天主题没有强匹配论文，自动退回七日热点主题池做补位检索。
4. 如果设置 `TOPIC_ROTATION_ENABLED=off`，回到旧的 GNSS / 融合 / SLAM 综合检索。

手动测试某一天的轮换主题：

```bash
python -m daily_gnss_slam_digest --issue-date 2026-07-04 --publish-mode none
```

关闭轮换：

```bash
TOPIC_ROTATION_ENABLED=off
```

## 7. 如何修改每日运行时间

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

## 8. 如何手动运行

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

如果当天推荐列表还不存在，`generate_deepdives.sh` 会先自动生成当天 `gnss-slam-digest.json`，再继续生成论文解读；如果显式设置了 `DIGEST_JSON`，则会要求这个文件必须存在。

论文解读配图还可以指定第二个参数：

| 模式 | 用法 | 说明 |
| --- | --- | --- |
| `paper` | `./scripts/generate_deepdives.sh draft paper` | 只提取论文 PDF 原图，并按 Introduction、Method、Experiments 生成章节图组 |
| `ai` | `./scripts/generate_deepdives.sh draft ai` | 用 `GEMINI_API_KEY` 生成 16:9 概念图，再搭配论文章节图组 |
| `both` | `./scripts/generate_deepdives.sh draft both` | 同一篇论文生成原图版和 AI 版两份草稿，便于在公众号后台对比 |

注意：`both` 是对比模式，会让每篇论文生成两份草稿。例如 `DEEPDIVE_LIMIT=3` 时，最终会进入草稿箱 6 篇。

正文文案默认 `DEEPDIVE_TEXT_POLISH_MODE=api`，会优先调用 Gemini 做润色；如果 API 不可用、额度不足或没有配置 Key，会自动回退到传统本地文案。草稿邮件会标明“解读模式”和“配图模式”，例如“AI 润色（Gemini）”或“传统模板”。实验/结果类图片默认 `DEEPDIVE_EXPERIMENT_COMPOSITE=1`，会合成为一张组合图再做整体解释。

如果要让每日自动化默认生成两个版本，把 `.env` 改成：

```env
DEEPDIVE_IMAGE_MODE=both
GEMINI_API_KEY=你的 Gemini Key
```

只生成本周热点汇总：

```bash
./scripts/generate_weekly_summary.sh
```

## 9. 运行模式说明

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

## 10. 邮件提醒逻辑

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

通知邮件默认会在末尾附上几组“论文指令”快捷模板，包括只生成总结、总结加解读、只解读一篇和生成周报。想关闭这块内容，可以在 `.env` 中设置：

```bash
EMAIL_NOTIFY_INCLUDE_QUICK_COMMANDS=0
```

## 11. 邮件指令控制

除了每日定时任务，也可以通过邮件临时指定关键词，让系统按当前方案生成一组定制论文推荐和论文解读。

### 11.1 开启邮件指令

`.env` 中配置：

```bash
EMAIL_COMMAND_ENABLED=1
EMAIL_COMMAND_IMAP_HOST=imap.qq.com
EMAIL_COMMAND_IMAP_PORT=993
EMAIL_COMMAND_USERNAME=your@email.com
EMAIL_COMMAND_PASSWORD=your_imap_authorization_code
EMAIL_COMMAND_ALLOWED_SENDERS=your@email.com
EMAIL_COMMAND_SUBJECT_KEYWORD=论文指令
EMAIL_COMMAND_DEFAULT_MODE=draft
EMAIL_COMMAND_DEFAULT_TASKS=digest,deepdive
EMAIL_COMMAND_POLL_INTERVAL=300
EMAIL_COMMAND_GIT_PUSH=1
```

QQ 邮箱通常使用授权码，不是网页登录密码。如果 `EMAIL_COMMAND_USERNAME` / `EMAIL_COMMAND_PASSWORD` 没有单独设置，脚本会尝试复用 `SMTP_USERNAME` / `SMTP_PASSWORD`。

安装“每 5 分钟检查一次邮箱”的定时器：

```bash
./scripts/install_email_command_launchd.sh 300
```

手动检查一次邮箱指令：

```bash
./scripts/process_email_commands.sh
```

### 11.2 邮件怎么写

邮件必须满足两个条件：

- 发件人在 `EMAIL_COMMAND_ALLOWED_SENDERS` 里。
- 邮件主题包含 `EMAIL_COMMAND_SUBJECT_KEYWORD`，默认是 `论文指令`。

推荐邮件格式：

```text
主题：论文指令：GNSS 干扰与鲁棒定位

关键词：GNSS jamming, spoofing detection, robust localization
任务：digest, deepdive
模式：draft
数量：5
解读数量：3
检索天数：180
```

字段说明：

| 字段 | 作用 |
| --- | --- |
| `关键词` | 指定 arXiv 检索关键词，逗号或分号分隔 |
| `任务` | `digest` 生成推荐；`deepdive` 生成论文解读；`weekly` 生成周报 |
| `模式` | `none`、`draft`、`publish`，默认 `draft` |
| `数量` | 推荐文章收录论文数量 |
| `解读数量` | 单篇论文解读数量 |
| `检索天数` | arXiv 检索结果的时间窗口 |

脚本会把邮件指令的输出放到：

```text
outputs/email_commands/<运行时间>/
```

并在执行完成后发一封总结邮件，列出关键词、执行步骤、输出目录和结果码。

如果只想生成“论文推荐/总结”，不要生成单篇论文解读，可以这样写：

```text
主题：论文指令：只生成总结

关键词：GNSS spoofing detection, C/N0, AGC
任务：总结
模式：draft
数量：5
```

也可以保留任务字段不变，但把解读数量设为 0：

```text
关键词：GNSS spoofing detection, C/N0, AGC
任务：digest, deepdive
解读数量：0
```

### 11.3 支持的任务写法

`任务` 可以用英文或中文：

| 写法 | 等价任务 |
| --- | --- |
| `digest`、`daily`、`summary`、`日报`、`推荐`、`总结`、`论文总结`、`只生成总结` | 生成关键词推荐文章 |
| `deepdive`、`paper`、`解读`、`论文解读` | 生成单篇论文解读 |
| `weekly`、`week`、`周报` | 生成周报 |

如果只写 `任务：deepdive`，系统会自动先跑 `digest`，因为论文解读需要先有推荐列表 JSON。

### 11.4 邮件扫描范围

邮件指令脚本不再只看未读邮件。它会同时检查：

- 未读邮件；
- 最近 `EMAIL_COMMAND_RECENT_DAYS` 天内的邮件，默认 7 天；
- 最新 `EMAIL_COMMAND_MAX_MESSAGES` 封候选邮件，默认 100 封。

脚本会把已经执行过的邮件指令指纹写入：

```text
outputs/email_commands/processed_commands.json
```

这样即使你打开过邮件、邮件变成已读，最近的新指令也不会被漏掉；同一封邮件也不会每 5 分钟重复执行。

如果你明确想重放一封最近的已读旧指令，可以手动加 `--force-recent`：

```bash
./scripts/process_email_commands.sh --dry-run --force-recent
./scripts/process_email_commands.sh --force-recent
```

第一条只预览，第二条才会真正生成。定时任务不要加这个参数，否则旧指令可能被重复执行。

### 11.5 `Processed email commands: 0` 怎么看？

手动执行：

```bash
./scripts/process_email_commands.sh --dry-run
```

脚本会打印类似信息：

```text
Scanned candidate messages: 62 (unread: 43, recent: 43)
Matched command emails: 1; skipped already processed: 0; skipped old read: 1
Processed email commands: 0
```

含义如下：

| 输出项 | 含义 |
| --- | --- |
| `Scanned candidate messages` | 本次实际检查了多少封候选邮件 |
| `unread` | 当前未读邮件数量 |
| `recent` | 最近 `EMAIL_COMMAND_RECENT_DAYS` 天内的邮件数量 |
| `Matched command emails` | 发件人、主题和正文格式都匹配的邮件指令数量 |
| `skipped already processed` | 已经执行过，因本地指纹记录被跳过 |
| `skipped old read` | 已读旧指令，时间早于最近一次执行输出，默认防重复跳过 |

如果 `Matched command emails` 是 0，通常是主题没有包含 `论文指令`、发件人不在白名单、正文没有写 `关键词`，或者邮件太旧超过了 `EMAIL_COMMAND_RECENT_DAYS`。

如果 `skipped old read` 是 1，说明脚本找到了那封指令，但它已经被读过，而且比最近一次输出更早。此时如果你确认要重放，用：

```bash
./scripts/process_email_commands.sh --dry-run --force-recent
./scripts/process_email_commands.sh --force-recent
```

如果 `skipped already processed` 是 1，说明这封邮件已经正式执行过。要重新执行，建议重新发一封新邮件，而不是改本地状态文件。

## 12. 输出文件和日志

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

邮件指令日志输出在：

```text
outputs/logs/email-commands.out.log
outputs/logs/email-commands.err.log
```

### 自动清理策略

每日总控 `scripts/daily_automation.sh` 会在正式生成前运行：

```bash
./scripts/cleanup_outputs.sh
```

单篇论文解读 `scripts/generate_deepdives.sh` 也会在生成前清空本次解读输出目录，默认是：

```text
outputs/deepdives/
```

默认清理规则：

| 类型 | 默认行为 |
| --- | --- |
| 测试/检查目录 | 删除 `outputs/deepdives-*-check`、`outputs/deepdives-*-test` 等临时目录 |
| 论文解读目录 | 每次生成前清空目标目录，避免旧文章混入新草稿 |
| 每日推荐文件 | 保留最近 8 天 |
| 邮件指令产物 | 保留最近 3 次运行，同时最多保留 3 天 |
| 周报文件 | 保留 70 天 |
| 日志文件 | 保留 14 天 |
| arXiv 缓存 | 默认不删除，避免频繁请求导致限流 |

可以在 `.env` 里调整：

```bash
OUTPUT_CLEAN_ENABLED=1
DEEPDIVE_CLEAN_BEFORE_RUN=1
OUTPUT_DAILY_RETENTION_DAYS=8
OUTPUT_EMAIL_RETENTION_DAYS=3
OUTPUT_EMAIL_KEEP_LATEST=3
OUTPUT_WEEKLY_RETENTION_DAYS=70
OUTPUT_LOG_RETENTION_DAYS=14
```

如果只是想预览会删什么，不真正删除：

```bash
./scripts/cleanup_outputs.sh --dry-run
```

如果临时想保留所有历史输出：

```bash
OUTPUT_CLEAN_ENABLED=0 ./scripts/daily_automation.sh
```

## 13. 常见问题

### 13.1 改了 `.env` 时间，为什么没有按新时间跑？

因为 `.env` 只是项目配置，系统定时任务已经被写入 `~/Library/LaunchAgents/`。改完 `.env` 后，需要重新运行：

```bash
./scripts/install_daily_launchd.sh
```

### 13.2 微信接口报 IP 白名单错误怎么办？

微信公众号 API 要求当前公网 IP 在公众号后台的 IP 白名单中。报错类似：

```text
invalid ip xxx.xxx.xxx.xxx, not in whitelist
```

解决方式是在公众号后台的“安全中心 / IP 白名单”里加入当前脚本运行机器的公网 IP。

### 13.3 launchd 报 Operation not permitted 怎么办？

如果日志里出现：

```text
Operation not permitted
```

常见原因是项目放在 `~/Documents`、`~/Desktop` 等受 macOS 隐私保护的目录里。推荐把项目放到不受 Documents 权限影响的位置，例如：

```text
/Users/wangzhibo/Projects/Daily_Automation
```

迁移后需要在新目录重新安装定时任务：

```bash
./scripts/install_daily_launchd.sh HH:MM
```

### 13.4 为什么没有直接正式发布？

当前默认是 `draft` 模式，只创建草稿，不正式发布。这样更安全，可以先人工检查排版、封面和图片。

如果要尝试提交正式发布，可以把模式改成：

```bash
AUTOMATION_WECHAT_MODE=publish
AUTOMATION_DEEPDIVE_MODE=publish
```

但前提是公众号账号具备 `freepublish` 接口权限。

### 13.5 怎么确认定时任务已经安装？

重新运行安装脚本后，如果看到类似输出，说明已经安装：

```text
Installed launchd job: com.codex.daily-gnss-slam-digest
Schedule: daily at 09:00
```

也可以手动触发一次：

```bash
launchctl kickstart -k gui/$(id -u)/com.codex.daily-gnss-slam-digest
```

### 13.6 GitHub 没有提交怎么办？

检查以下配置：

```bash
GITHUB_REPO_URL=git@github.com:your-name/your-repo.git
GITHUB_BRANCH=master
GIT_AUTHOR_NAME="GNSS Paper Bot"
GIT_AUTHOR_EMAIL=your@email.com
```

如果当天没有生成新内容，脚本会显示没有文件需要提交，这是正常情况。
