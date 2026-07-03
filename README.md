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

## 微信公众号配置

复制环境变量模板：

```bash
cp .env.example .env
```

填写：

- `WECHAT_APP_ID`: 公众号 AppID。
- `WECHAT_APP_SECRET`: 公众号 AppSecret。
- `WECHAT_THUMB_MEDIA_ID`: 图文封面素材 `media_id`，微信草稿接口必填。
- `WECHAT_AUTHOR`: 文章作者名，默认 `GNSS Paper Bot`。
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

QQ 邮箱的 `SMTP_PASSWORD` 是邮箱授权码，不是网页登录密码。脚本会在草稿创建成功后发送邮件；如果 `publish` 模式提交正式发布失败，草稿保留，也会再发一封失败提醒。

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

生成微信公众号草稿：

```bash
./scripts/generate_deepdives.sh draft
```

确认草稿后也可以提交发布：

```bash
./scripts/generate_deepdives.sh publish
```

如果 `publish` 返回 `48001 api unauthorized`，说明公众号当前没有调用“发布能力/freepublish”接口的权限；脚本会保留已创建的草稿。此时可以在公众号后台手动发布草稿，或在账号具备发布接口权限后再使用 `publish`。

## 每日自动化和 GitHub 提交

总控脚本会按顺序执行：生成每日推荐、创建公众号草稿、生成单篇论文解读草稿、提交并推送到 GitHub、发送总结邮件。

```bash
./scripts/daily_automation.sh
```

`.env` 中可以配置：

```bash
AUTOMATION_TIME=08:30
AUTOMATION_WECHAT_MODE=draft
AUTOMATION_DEEPDIVE_MODE=draft
GITHUB_REPO_SSH=git@github.com:your-name/your-repo.git
GITHUB_BRANCH=main
GIT_AUTHOR_NAME=GNSS Paper Bot
GIT_AUTHOR_EMAIL=your@email.com
```

如果当前目录还不是 git 仓库，脚本会在 `GITHUB_REPO_SSH` 存在时自动 `git init`、添加 `origin` 并推送。`.env`、日志、论文 PDF 和中间缓存不会提交；最终文章、正文图和配置代码会提交。

在 macOS 上安装每日定时任务：

```bash
./scripts/install_daily_launchd.sh 08:30
```

手动触发一次已安装的定时任务：

```bash
launchctl kickstart -k gui/$(id -u)/com.codex.daily-gnss-slam-digest
```

## 查询主题

默认覆盖三组主题：

- GNSS spoofing/jamming detection: 欺骗、干扰、PNT 完整性、异常检测。
- Multimodal fusion: LiDAR/visual/inertial/GNSS、多传感器融合、紧耦合估计。
- SLAM and odometry: SLAM、VIO/LIO/LIVO、回环、建图、定位。

可在命令行调整窗口和推荐数量：

```bash
python -m daily_gnss_slam_digest --days-back 120 --limit 6 --publish-mode none
```

## 注意事项

- arXiv API 会实时抓取论文元数据，网络不可用时会失败并保留清晰错误信息。
- 微信公众号 API 通常要求后台配置 IP 白名单；如果 token 获取失败，先检查公众号后台设置。
- 不要把 `.env`、AppSecret、access token 提交到仓库。
