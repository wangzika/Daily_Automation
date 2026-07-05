# 每日 GNSS/融合/SLAM 论文公众号助手

这个项目会每天抓取 arXiv 上与 GNSS 欺骗检测、多模态/多传感器融合、SLAM/里程计相关的论文，按主题相关性和新鲜度排序，生成适合微信公众号的中文推荐文章。

如果配置了微信公众号接口凭证，它还能自动把文章创建为公众号草稿；开启发布模式后，会继续调用发布接口。

## 快速运行

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -m daily_gnss_slam_digest --publish-mode none
```

生成结果会写到 `outputs/`：

- `YYYY-MM-DD-gnss-slam-digest.md`
- `YYYY-MM-DD-gnss-slam-digest.html`
- `YYYY-MM-DD-gnss-slam-digest.json`

## 选题质量优化

推荐器现在不只看关键词和时间，还会做标题级去重，并把质量信号纳入排序：

- 引用信号：开启 Semantic Scholar 增强后，会读取 `citationCount`、`influentialCitationCount`。
- venue 信号：从 arXiv `comment`、`journal_ref` 和 Semantic Scholar venue 中识别 ICRA、IROS、RSS、RA-L、T-RO、ION GNSS、PLANS 等。
- 开源/复现信号：识别 GitHub/GitLab/Code Ocean 链接，以及 `code`、`benchmark`、`dataset`、`real-world` 等摘要线索。
- 工程信号：真实实验、数据集、benchmark 会加权；纯 survey/review 会轻微降权。

`.env` 可配置：

```bash
SEMANTIC_SCHOLAR_ENRICH=on
QUALITY_ENRICH_LIMIT=30
SEMANTIC_SCHOLAR_DELAY_SECONDS=1.0
SEMANTIC_SCHOLAR_API_KEY=
```

没有 Semantic Scholar API key 也可以运行；如果接口限流或不可用，脚本会跳过外部增强，继续按本地质量信号出稿。

## arXiv 限流兜底

日报现在默认做三层保护：

- arXiv 查询会写入 `ARXIV_CACHE_DIR`，同一天同主题重复测试会优先读缓存。
- 遇到 arXiv `429` 或超时，会按更长间隔退避；如果有旧缓存，会用旧缓存继续生成。
- arXiv 仍不可用时，会按 `PAPER_FALLBACK_SOURCES` 切到备用源，默认顺序是 `semantic-scholar,openalex,crossref,existing-json`。

推荐配置：

```bash
DIGEST_PER_TOPIC=10
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

`semantic-scholar`、`openalex`、`crossref` 会依次搜索公开学术索引补论文；`existing-json` 会用当天已有 JSON 重新按主题过滤排版。这样 arXiv 临时限流时，公众号草稿仍能生成。`OPENALEX_MAILTO` 和 `CROSSREF_MAILTO` 可填你的邮箱，方便进入这些 API 的 polite pool。

## 微信公众号配置

复制环境变量模板：

```bash
cp .env.example .env
```

填写：

- `WECHAT_APP_ID`: 公众号 AppID。
- `WECHAT_APP_SECRET`: 公众号 AppSecret。
- `WECHAT_DAILY_THEME_COVER`: 默认 `1`，每日推荐草稿会把当天主题图上传为图文封面。
- `WECHAT_THUMB_MEDIA_ID`: 固定封面素材 `media_id`；当关闭每日主题封面，或主题封面上传失败时作为回退封面。
- `WECHAT_AUTHOR`: 文章作者名，默认 `波波机器人`。
- `WECHAT_PUBLISH_MODE`: `none`、`draft` 或 `publish`。

运行时加载 `.env`：

```bash
set -a
. ./.env
set +a
python -m daily_gnss_slam_digest --publish-mode draft
```

`draft` 会创建草稿但不正式发布；`publish` 会先创建草稿，再提交发布。建议第一次先用 `draft`。

## 邮件提醒

创建公众号草稿成功后，可以自动给自己发邮件提醒。把 SMTP 配置写入 `.env`：

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

QQ 邮箱的 `SMTP_PASSWORD` 是邮箱授权码，不是网页登录密码。单独运行草稿脚本时会在草稿创建成功后发送邮件；单篇论文解读会把本次生成的多篇草稿合并成一封汇总邮件。如果 `publish` 模式提交正式发布失败，草稿保留，也会再发一封失败提醒。

邮件里会附上公众号后台草稿箱入口。这个入口可以通过 `WECHAT_BACKEND_URL` 覆盖；微信网页后台的具体草稿编辑页依赖登录态 token，脚本不会保存网页登录态。

## 创建封面并上传素材

先生成或准备一张底图，然后制作公众号封面：

```bash
python scripts/make_wechat_cover.py --input path/to/background.png --output outputs/wechat-cover-gnss-slam.jpg
```

上传封面图为微信公众号永久图片素材，并自动写入 `.env` 的 `WECHAT_THUMB_MEDIA_ID`：

```bash
PYTHONPATH=src python scripts/upload_cover_to_wechat.py outputs/wechat-cover-gnss-slam.jpg
```

上传成功后，`WECHAT_PUBLISH_MODE=draft` 即可创建公众号草稿。

## 每日自动执行

本仓库带有 `scripts/run_daily.sh`，适合放进系统 cron、launchd，或由 Codex 自动化任务每天调用。

```bash
./scripts/run_daily.sh
```

## 一键发布

创建草稿：

```bash
./scripts/publish_now.sh draft
```

确认草稿无误后提交发布：

```bash
./scripts/publish_now.sh publish
```

发布流程会自动生成正文配图、上传微信正文图片、创建草稿；`publish` 模式会继续提交发布。

## 生成单篇论文解读

从当天推荐列表里选前 3 篇，下载 PDF，直接抽取论文原图，生成单篇解读文章：

```bash
./scripts/generate_deepdives.sh none
```

如果当天的 `outputs/YYYY-MM-DD-gnss-slam-digest.json` 还不存在，脚本会先用 `publish-mode=none` 自动生成当天推荐列表，再继续生成论文解读。

生成微信公众号草稿：

```bash
./scripts/generate_deepdives.sh draft
```

论文解读会按论文自身的结构展开：Introduction 讲背景和问题，Method 讲方法与系统设计，Experiments 讲实验设置和结果，Discussion 讲结论、边界与复现。`DEEPDIVE_PAPER_COVER=1` 时，会优先从论文 PDF 里挑 framework / architecture / pipeline / system 等流程图或框架图作为公众号草稿封面；正文图片会按 Introduction / Method / Experiments 分章节组图，而不是把所有图片堆到同一个图片区块里。

如果想同时对比两种配图方式，可以运行：

```bash
./scripts/generate_deepdives.sh none both
```

其中 `paper` 版本只使用论文原图，并按 `DEEPDIVE_FIGURE_KEYWORDS` 里的关键词优先匹配流程图、框架图、系统图；`ai` 版本会用 `GEMINI_API_KEY` 生成 16:9 概念图，再保留论文分章节图组辅助解读。默认模式由 `.env` 里的 `DEEPDIVE_IMAGE_MODE=paper|ai|both` 控制。默认 `DEEPDIVE_LIMIT=5`，会覆盖每日推荐里的 5 篇论文；注意：`both` 是对比模式，会让每篇论文生成两份草稿，例如 `DEEPDIVE_LIMIT=5` 时会生成 10 篇草稿。

正文文案默认优先用 Gemini 做轻量润色，API 不可用、额度不足或未配置 Key 时会自动回退到传统本地文案；邮件通知里会标明“解读模式：AI 润色（Gemini）”或“传统模板”。图片会先用 `pdfimages` 抽取内嵌图片，再用 `pdftoppm + pdftotext -bbox` 按图注位置从渲染页面裁剪矢量流程图、架构图和结构图；随后过滤纯黑、纯白、低信息量抽图和无图注小图标，再按介绍、方法、实验三类合成为章节图组，避免一张张图机械铺开。

两个抽图参数可以在 `.env` 里调：

```bash
DEEPDIVE_RENDER_FIGURE_PAGES=12
DEEPDIVE_RENDER_FIGURE_DPI=200
DEEPDIVE_DOWNLOAD_RETRIES=3
```

页数越大，越容易抓到后文图，但本地渲染会更慢；DPI 越高，裁剪图越清晰，也会增加运行时间。

确认草稿后也可以提交发布：

```bash
./scripts/generate_deepdives.sh publish
```

如果 `publish` 返回 `48001 api unauthorized`，说明公众号当前没有调用“发布能力/freepublish”接口的权限；脚本会保留已创建的草稿。此时可以在公众号后台手动发布草稿，或在账号具备发布接口权限后再使用 `publish`。

## 每日自动化和 GitHub 提交

总控脚本会按顺序执行：生成每日推荐、创建公众号草稿、生成单篇论文解读草稿、按周生成热点汇总、提交并推送到 GitHub、发送总结邮件。

完整的自动化说明见 [docs/automation-guide.md](docs/automation-guide.md)。

```bash
./scripts/daily_automation.sh
```

脚本带有运行锁，避免定时任务重叠执行；定时总控默认只发送最后一封总结邮件，邮件只保留成功/失败、步骤耗时、公众号草稿箱、GitHub commit 和日志路径，失败时才附少量日志摘录。通知邮件末尾会附上可直接复制的“论文指令”快捷模板；如果觉得邮件太长，可把 `EMAIL_NOTIFY_INCLUDE_QUICK_COMMANDS=0`。

`.env` 中可以配置：

```bash
AUTOMATION_TIME=09:00
AUTOMATION_PYTHON=
AUTOMATION_WECHAT_MODE=draft
AUTOMATION_DEEPDIVE_MODE=draft
AUTOMATION_LOG_TAIL_LINES=60
EMAIL_NOTIFY_INCLUDE_QUICK_COMMANDS=1
WEEKLY_SUMMARY_ENABLED=1
WEEKLY_SUMMARY_DAY=7
WEEKLY_SUMMARY_DAYS=7
OUTPUT_CLEAN_ENABLED=1
DEEPDIVE_CLEAN_BEFORE_RUN=1
OUTPUT_DAILY_RETENTION_DAYS=8
OUTPUT_EMAIL_RETENTION_DAYS=3
OUTPUT_EMAIL_KEEP_LATEST=3
OUTPUT_WEEKLY_RETENTION_DAYS=70
OUTPUT_LOG_RETENTION_DAYS=14
TOPIC_ROTATION_ENABLED=on
GITHUB_REPO_URL=git@github.com:your-name/your-repo.git
GITHUB_BRANCH=master
GIT_AUTHOR_NAME="GNSS Paper Bot"
GIT_AUTHOR_EMAIL=your@email.com
```

`AUTOMATION_WECHAT_MODE` 和 `AUTOMATION_DEEPDIVE_MODE` 支持 `none`、`draft`、`publish`。如果 launchd 使用的系统 Python 缺少依赖，可以把 `AUTOMATION_PYTHON` 设置为可用解释器，例如 `/Users/wangzhibo/miniconda3/bin/python`。总控脚本会自动设置 `EMAIL_NOTIFY_SUPPRESS_STEP_MESSAGES=1`，只保留最后一封总结邮件；如果想调试子步骤邮件，可以在 `.env` 里显式设为 `0`。每次自动化开始会清理 `outputs` 里的测试目录、过期日报、旧邮件指令产物和旧日志；每次生成论文解读前会清空本次解读输出目录，避免混入上一轮旧文章。需要临时保留全部输出时，把 `OUTPUT_CLEAN_ENABLED=0`。如果当前目录还不是 git 仓库，脚本会在 `GITHUB_REPO_URL` 存在时自动 `git init`、添加 `origin` 并推送。`.env`、日志、论文 PDF 和中间缓存不会提交；最终文章、正文图和配置代码会提交。

也可以开启邮件指令控制：发一封主题包含 `论文指令` 的邮件，在正文写 `关键词`、`任务`、`模式`，脚本会按指定关键词生成推荐、论文解读或周报。邮件扫描会同时检查未读邮件和最近几天的已读邮件，并用本地指纹文件避免重复执行。

常用邮件指令：

```text
主题：论文指令：GNSS 干扰与鲁棒定位

关键词：GNSS jamming, spoofing detection, robust localization
任务：digest, deepdive
模式：draft
数量：5
解读数量：2
检索天数：180
```

只生成推荐总结、不生成单篇论文解读：

```text
主题：论文指令：只生成总结

关键词：GNSS spoofing detection, C/N0, AGC
任务：总结
模式：draft
数量：5
```

本地测试邮箱指令：

```bash
./scripts/process_email_commands.sh --dry-run
```

如果要手动重放一封最近已读的旧指令：

```bash
./scripts/process_email_commands.sh --dry-run --force-recent
./scripts/process_email_commands.sh --force-recent
```

配置、完整字段和排查方法见 [docs/automation-guide.md](docs/automation-guide.md)。

单独生成本周热点汇总：

```bash
./scripts/generate_weekly_summary.sh
```

周报会写入 `outputs/weekly/`，内容包括热点方向、机器人领域热点雷达、高频关键词、有代码/复现线索、venue/引用线索和本周最值得追的论文。

在 macOS 上安装每日定时任务：

```bash
./scripts/install_daily_launchd.sh 09:00
```

手动触发一次已安装的定时任务：

```bash
launchctl kickstart -k gui/$(id -u)/com.codex.daily-gnss-slam-digest
```

## 查询主题

默认开启 `TOPIC_ROTATION_ENABLED=on`，没有邮件关键词时按星期轮换 7 个导航定位热点主题：

| 星期 | 主题 |
| --- | --- |
| 周一 | 具身导航与机器人基础模型 |
| 周二 | 3DGS/NeRF 神经场 SLAM |
| 周三 | 开放词汇语义地图与语言导航 |
| 周四 | 地点识别与长期定位 |
| 周五 | 多机器人协同 SLAM 与分布式建图 |
| 周六 | 韧性 PNT 与 GNSS 抗欺骗抗干扰 |
| 周日 | 退化场景多模态融合与鲁棒里程计 |

如果当天轮换主题没有强匹配论文，脚本会自动退回到七日热点主题池做补位检索，避免日报空跑。邮件指令里的 `关键词` 优先级最高；只要你通过邮件指定关键词，就不会使用当天轮换主题。

如果想回到旧的综合检索：

```bash
TOPIC_ROTATION_ENABLED=off
```

可在命令行调整窗口和推荐数量：

```bash
python -m daily_gnss_slam_digest --days-back 120 --limit 6 --publish-mode none
```

## 注意事项

- arXiv API 会实时抓取论文元数据，网络不可用时会失败并保留清晰错误信息。
- 微信公众号 API 通常要求后台配置 IP 白名单；如果 token 获取失败，先检查公众号后台设置。
- 不要把 `.env`、AppSecret、access token 提交到仓库。
