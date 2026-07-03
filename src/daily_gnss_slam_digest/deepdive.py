from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

from .notify import describe_notification_result, notify_draft_created, notify_publish_issue
from .wechat import WeChatConfig, WeChatPublisher, WeChatPublisherError


@dataclass(frozen=True)
class DeepDiveFigure:
    path: Path
    caption: str


@dataclass(frozen=True)
class PaperReading:
    abstract: str
    introduction: str
    method: str
    experiments: str
    conclusion: str
    captions: tuple[str, ...]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    papers = json.loads(args.input_json.read_text(encoding="utf-8"))[: args.limit]
    if not papers:
        print("No papers found.", file=sys.stderr)
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    draft_ids: list[str] = []
    cover_media_ids: list[str] = []
    publish_results: list[dict[str, Any]] = []
    publish_failed = False
    publish_blocked_reason: str | None = None

    publisher: WeChatPublisher | None = None
    access_token: str | None = None
    if args.publish_mode != "none":
        try:
            publisher = WeChatPublisher(WeChatConfig.from_env())
            access_token = publisher.get_access_token()
        except WeChatPublisherError as exc:
            print(f"WeChat setup failed: {exc}", file=sys.stderr)
            return 3

    for index, paper in enumerate(papers, start=1):
        slug = _slugify(paper.get("arxiv_id") or paper["title"])
        paper_dir = args.output_dir / f"{index:02d}-{slug}"
        paper_dir.mkdir(parents=True, exist_ok=True)

        pdf_path = paper_dir / "paper.pdf"
        _download(paper["pdf_url"], pdf_path)

        captions = _extract_figure_captions(pdf_path)
        reading = _build_reading(pdf_path, captions)
        figures = _extract_figures(pdf_path, paper_dir, captions, max_figures=args.figures)
        if not figures:
            figures = _render_fallback_figures(pdf_path, paper_dir, max_figures=args.figures)
        cover_figure = _select_cover_figure(figures)
        figures = _move_cover_first(figures, cover_figure)

        local_image_map = {f"figure_{i}": figure.path.name for i, figure in enumerate(figures, start=1)}
        markdown = build_deepdive_markdown(paper, reading, figures, local_image_map)
        html_text = build_deepdive_html(paper, reading, figures, local_image_map)

        md_path = paper_dir / "article.md"
        html_path = paper_dir / "article.html"
        md_path.write_text(markdown, encoding="utf-8")
        html_path.write_text(html_text, encoding="utf-8")
        created.append(html_path)
        print(f"Wrote deep dive: {html_path}")

        if publisher and access_token:
            cover_media_id = None
            if cover_figure and os.getenv("DEEPDIVE_PAPER_COVER", "1").lower() not in {"0", "false", "no", "off"}:
                try:
                    cover_result = publisher.upload_permanent_image(access_token, cover_figure.path)
                    cover_media_id = str(cover_result.get("media_id") or "")
                    if cover_media_id:
                        cover_media_ids.append(cover_media_id)
                        print(f"Uploaded paper cover media_id: {cover_media_id}")
                except WeChatPublisherError as exc:
                    print(f"Paper cover upload failed, using default cover: {exc}", file=sys.stderr)
            image_urls = {
                f"figure_{i}": publisher.upload_article_image(access_token, figure.path)
                for i, figure in enumerate(figures, start=1)
            }
            wechat_html = build_deepdive_html(paper, reading, figures, image_urls)
            title = _wechat_title(paper)
            media_id = publisher.add_draft(
                access_token=access_token,
                title=title,
                content_html=wechat_html,
                digest=_digest(paper),
                content_source_url=paper.get("url"),
                thumb_media_id=cover_media_id,
            )
            draft_ids.append(media_id)
            print(f"Created WeChat deep-dive draft media_id: {media_id}")
            extra_lines = ()
            if args.publish_mode == "publish" and publish_blocked_reason:
                extra_lines = (f"正式发布已跳过：{publish_blocked_reason}",)
            print(
                describe_notification_result(
                    notify_draft_created(
                        article_type="单篇论文解读",
                        title=title,
                        media_id=media_id,
                        publish_mode=args.publish_mode,
                        local_paths=(html_path, md_path),
                        source_url=paper.get("url"),
                        extra_lines=extra_lines,
                    )
                )
            )
            if args.publish_mode == "publish":
                if publish_blocked_reason:
                    publish_results.append(
                        {
                            "media_id": media_id,
                            "status": "draft_created_publish_skipped",
                            "reason": publish_blocked_reason,
                        }
                    )
                    print(f"Skipped publish submit for draft {media_id}: {publish_blocked_reason}", file=sys.stderr)
                else:
                    try:
                        result = publisher.submit_publish(access_token, media_id)
                        publish_results.append({"media_id": media_id, "status": "submitted", "result": result})
                        print(f"Submitted WeChat publish request: {result}")
                    except WeChatPublisherError as exc:
                        publish_failed = True
                        reason = str(exc)
                        publish_results.append(
                            {
                                "media_id": media_id,
                                "status": "draft_created_publish_failed",
                                "reason": reason,
                            }
                        )
                        print(f"WeChat publish submit failed after draft creation: {reason}", file=sys.stderr)
                        print(
                            describe_notification_result(
                                notify_publish_issue(
                                    article_type="单篇论文解读",
                                    title=title,
                                    media_id=media_id,
                                    reason=reason,
                                )
                            )
                        )
                        if _is_publish_unauthorized(reason):
                            publish_blocked_reason = (
                                "freepublish API unauthorized (errcode 48001); "
                                "draft was kept and later articles will be saved as drafts"
                            )
                            print(publish_blocked_reason, file=sys.stderr)

    manifest = args.output_dir / f"{date.today().isoformat()}-deepdives.json"
    manifest.write_text(
        json.dumps(
            {
                "articles": [str(path) for path in created],
                "draft_media_ids": draft_ids,
                "cover_media_ids": cover_media_ids,
                "publish_results": publish_results,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote manifest: {manifest}")
    if publish_failed:
        return 4
    return 0


def build_deepdive_markdown(
    paper: dict[str, Any],
    reading: PaperReading,
    figures: list[DeepDiveFigure],
    image_map: dict[str, str],
) -> str:
    title = f"论文解读｜{paper['title']}"
    lines = [
        f"# {title}",
        "",
        f"- 作者：{_commentary_author()}",
        f"- 论文作者：{_authors(paper)}",
        f"- 日期：{paper.get('published', '')[:10]}",
        f"- 原文：{paper.get('url', '')}",
        "",
        "## 一句话读懂",
        "",
        _one_sentence(paper, reading),
        "",
        "## 原文线索",
        "",
        *_markdown_bullets(_source_clues(paper, reading)),
        "",
        "## 故事版导读",
        "",
        _story_intro(paper, reading),
        "",
        "## 按章节讲论文",
        "",
        *_chapter_markdown(_chapter_walkthrough(paper, reading)),
        "",
        "## 1. 背景与痛点",
        "",
        *_markdown_bullets(_problem_context(paper, reading)),
        "",
        "## 2. 研究问题",
        "",
        *_markdown_bullets(_research_questions(paper, reading)),
        "",
        "## 3. 方法拆解",
        "",
        *_markdown_bullets(_method_points(paper, reading)),
        "",
        "## 4. 论文图解",
        "",
    ]
    for i, figure in enumerate(figures, start=1):
        key = f"figure_{i}"
        lines.extend(
            [
                f"![{figure.caption}]({image_map.get(key, figure.path.name)})",
                "",
                f"图 {i}：{figure.caption}",
                "",
                _figure_reading(paper, reading, figure, i),
                "",
            ]
        )

    lines.extend(
        [
            "## 5. 实验和指标怎么看",
            "",
            *_markdown_bullets(_experiment_points(paper, reading)),
            "",
            "## 6. 贡献与局限",
            "",
            *_markdown_bullets(_contribution_and_limits(paper, reading)),
            "",
            "## 7. 工程启发与复现清单",
            "",
            *_markdown_bullets(_engineering_points(paper, reading)),
            "",
            "## 读完之后可以追问",
            "",
            *_markdown_bullets(_followup_questions(paper)),
            "",
            "> 图像来自论文 PDF，仅用于论文解读和学术讨论，正式转载前建议核对论文许可和作者要求。",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def build_deepdive_html(
    paper: dict[str, Any],
    reading: PaperReading,
    figures: list[DeepDiveFigure],
    image_map: dict[str, str],
) -> str:
    title = f"论文解读｜{paper['title']}"
    parts = [
        '<section style="max-width:677px;margin:0 auto;color:#24343a;font-family:-apple-system,BlinkMacSystemFont,Helvetica Neue,Arial,sans-serif;">',
        f'<h1 style="margin:0 0 14px;color:#10272f;font-size:24px;line-height:1.38;font-weight:800;">{html.escape(title)}</h1>',
        '<section style="margin:0 0 18px;padding:15px 16px;background:#f5fbfa;border-left:4px solid #25d8b8;color:#33484f;font-size:14px;line-height:1.9;">',
        f"作者：{html.escape(_commentary_author())}<br/>",
        f"论文作者：{html.escape(_authors(paper))}<br/>",
        f"日期：{html.escape(str(paper.get('published', ''))[:10])}<br/>",
        f'原文：<a href="{html.escape(paper.get("url", ""))}" style="color:#0b9984;text-decoration:none;">{html.escape(paper.get("url", ""))}</a>',
        "</section>",
        _section_title("一句话读懂"),
        _paragraph(_one_sentence(paper, reading)),
        _section_title("原文线索"),
        _numbered_cards(_source_clues(paper, reading)),
        _section_title("故事版导读"),
        _paragraph(_story_intro(paper, reading)),
        _section_title("按章节讲论文"),
        _chapter_cards(_chapter_walkthrough(paper, reading)),
        _section_title("1. 背景与痛点"),
        _numbered_cards(_problem_context(paper, reading)),
        _section_title("2. 研究问题"),
        _numbered_cards(_research_questions(paper, reading)),
        _section_title("3. 方法拆解"),
        _numbered_cards(_method_points(paper, reading)),
        _section_title("4. 论文图解"),
    ]

    for i, figure in enumerate(figures, start=1):
        key = f"figure_{i}"
        src = image_map.get(key, figure.path.name)
        parts.extend(
            [
                '<section style="margin:0 0 22px;padding:14px;border:1px solid #e1eeee;border-radius:10px;background:#ffffff;">',
                f'<img src="{html.escape(src)}" alt="{html.escape(figure.caption)}" style="display:block;width:100%;height:auto;border-radius:6px;"/>',
                f'<p style="margin:10px 0 8px;color:#0b9984;font-size:13px;font-weight:700;">图 {i} · {html.escape(figure.caption)}</p>',
                f'<p style="margin:0;color:#43565d;font-size:14px;line-height:1.85;">{html.escape(_figure_reading(paper, reading, figure, i))}</p>',
                "</section>",
            ]
        )

    parts.extend(
        [
            _section_title("5. 实验和指标怎么看"),
            _numbered_cards(_experiment_points(paper, reading)),
            _section_title("6. 贡献与局限"),
            _numbered_cards(_contribution_and_limits(paper, reading)),
            _section_title("7. 工程启发与复现清单"),
            _numbered_cards(_engineering_points(paper, reading)),
            _section_title("读完之后可以追问"),
            _numbered_cards(_followup_questions(paper)),
            '<p style="margin:22px 0 0;color:#8a9da3;font-size:12px;line-height:1.8;">图像来自论文 PDF，仅用于论文解读和学术讨论，正式转载前建议核对论文许可和作者要求。</p>',
            "</section>",
        ]
    )
    return "".join(parts)


def _download(url: str, output: Path) -> None:
    if output.exists() and output.stat().st_size > 0:
        return
    request = urllib.request.Request(url, headers={"User-Agent": "daily-gnss-slam-digest/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        output.write_bytes(response.read())


def _extract_figure_captions(pdf_path: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    captions: list[str] = []
    pattern = re.compile(r"^\s*((?:Fig(?:ure)?\.?)\s*\d+[.:]?\s+.+)$", re.IGNORECASE)
    for line in result.stdout.splitlines():
        match = pattern.match(line.strip())
        if match:
            caption = " ".join(match.group(1).split())
            if caption not in captions:
                captions.append(caption[:180])
    return captions


def _build_reading(pdf_path: Path, captions: list[str]) -> PaperReading:
    text = _extract_pdf_text(pdf_path)
    abstract = _extract_section(text, ("abstract",), ("keywords", "index terms", "1 introduction", "i. introduction", "introduction"))
    if not abstract:
        abstract = _extract_section(text, ("introduction",), ("related work", "method", "methodology", "approach", "preliminaries", "interference signal", "system overview", "materials"))
    introduction = _extract_section(
        text,
        ("introduction",),
        ("related work", "background", "preliminaries", "method", "methodology", "approach", "system overview", "proposed method"),
        max_chars=1800,
    )
    method = _extract_section(
        text,
        ("method", "methodology", "approach", "proposed method", "system overview", "framework", "algorithm", "materials and methods", "interference signal"),
        ("experiment", "experiments", "evaluation", "results", "implementation", "discussion", "conclusion"),
        max_chars=2200,
    )
    experiments = _extract_section(
        text,
        ("experiment", "experiments", "experimental setup", "evaluation", "results", "performance evaluation", "implementation"),
        ("discussion", "conclusion", "conclusions", "references", "acknowledgment", "acknowledgements"),
        max_chars=2200,
    )
    return PaperReading(
        abstract=abstract,
        introduction=introduction,
        method=method,
        experiments=experiments,
        conclusion=_extract_section(text, ("conclusion", "conclusions", "discussion"), ("references", "acknowledgment", "acknowledgements"), max_chars=1600),
        captions=tuple(captions),
    )


def _extract_pdf_text(pdf_path: Path) -> str:
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout


def _extract_section(text: str, starts: tuple[str, ...], ends: tuple[str, ...], max_chars: int = 1200) -> str:
    if not text:
        return ""
    lowered = text.lower()
    start_pos = -1
    for marker in starts:
        match = re.search(rf"(^|\n)\s*(?:[ivx]+\.|\d+(?:\.\d+)*\.?)?\s*{re.escape(marker)}\b[:.\s-]*", lowered)
        if match:
            start_pos = match.end()
            break
    if start_pos < 0:
        return ""

    end_pos = len(text)
    search_region = lowered[start_pos:]
    for marker in ends:
        match = re.search(rf"\n\s*(?:[ivx]+\.|\d+(?:\.\d+)*\.?)?\s*{re.escape(marker)}\b[:.\s-]*", search_region)
        if match:
            end_pos = start_pos + match.start()
            break
    section = text[start_pos:end_pos]
    return _clean_text(section)[:max_chars]


def _extract_figures(pdf_path: Path, output_dir: Path, captions: list[str], max_figures: int) -> list[DeepDiveFigure]:
    raw_dir = output_dir / "raw_images"
    raw_dir.mkdir(parents=True, exist_ok=True)
    prefix = raw_dir / "img"
    try:
        subprocess.run(["pdfimages", "-j", str(pdf_path), str(prefix)], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return []

    candidates: list[tuple[int, Path, Image.Image]] = []
    for path in sorted(raw_dir.iterdir()):
        if path.suffix.lower() not in {".jpg", ".jpeg", ".ppm", ".png"}:
            continue
        try:
            image = Image.open(path).convert("RGB")
        except OSError:
            continue
        image = _trim_white(image)
        width, height = image.size
        area = width * height
        if width < 420 or height < 170 or area < 110_000:
            continue
        if _ink_ratio(image) < 0.015:
            continue
        score = area
        if 1.1 <= width / max(height, 1) <= 4.8:
            score += 80_000
        candidates.append((score, path, image))

    candidates.sort(key=lambda item: item[0], reverse=True)
    selected: list[DeepDiveFigure] = []
    for i, (_score, _path, image) in enumerate(candidates[:max_figures], start=1):
        out = output_dir / f"figure-{i}.jpg"
        image.save(out, format="JPEG", quality=92, optimize=True, progressive=True)
        selected.append(DeepDiveFigure(out, _caption_for(captions, i)))
    return selected


def _render_fallback_figures(pdf_path: Path, output_dir: Path, max_figures: int) -> list[DeepDiveFigure]:
    render_dir = output_dir / "rendered_pages"
    render_dir.mkdir(parents=True, exist_ok=True)
    prefix = render_dir / "page"
    env = os.environ.copy()
    env.setdefault("XDG_CACHE_HOME", str((output_dir / ".cache").resolve()))
    try:
        subprocess.run(["pdftoppm", "-r", "160", "-f", "1", "-l", str(max_figures), "-png", str(pdf_path), str(prefix)], check=True, capture_output=True, text=True, env=env)
    except (OSError, subprocess.CalledProcessError):
        return []
    figures: list[DeepDiveFigure] = []
    for i, path in enumerate(sorted(render_dir.glob("*.png"))[:max_figures], start=1):
        image = Image.open(path).convert("RGB")
        image.thumbnail((1200, 900))
        out = output_dir / f"figure-{i}.jpg"
        image.save(out, format="JPEG", quality=90, optimize=True, progressive=True)
        figures.append(DeepDiveFigure(out, f"论文 PDF 第 {i} 页截图"))
    return figures


def _trim_white(image: Image.Image) -> Image.Image:
    background = Image.new(image.mode, image.size, (255, 255, 255))
    diff = ImageChops.difference(image, background)
    bbox = diff.getbbox()
    if not bbox:
        return image
    left, top, right, bottom = bbox
    pad = 12
    left = max(left - pad, 0)
    top = max(top - pad, 0)
    right = min(right + pad, image.width)
    bottom = min(bottom + pad, image.height)
    return image.crop((left, top, right, bottom))


def _ink_ratio(image: Image.Image) -> float:
    sample = image.resize((max(1, image.width // 8), max(1, image.height // 8)))
    pixels = sample.getdata()
    ink = sum(1 for r, g, b in pixels if min(r, g, b) < 245)
    return ink / max(len(pixels), 1)


def _caption_for(captions: list[str], index: int) -> str:
    if 0 <= index - 1 < len(captions):
        return captions[index - 1]
    return f"论文原图 {index}（从 PDF 直接提取）"


def _select_cover_figure(figures: list[DeepDiveFigure]) -> DeepDiveFigure | None:
    if not figures:
        return None
    return max(figures, key=_cover_score)


def _move_cover_first(figures: list[DeepDiveFigure], cover: DeepDiveFigure | None) -> list[DeepDiveFigure]:
    if not cover:
        return figures
    return [cover, *(figure for figure in figures if figure.path != cover.path)]


def _cover_score(figure: DeepDiveFigure) -> float:
    caption = figure.caption.lower()
    score = 0.0
    for term in (
        "framework",
        "architecture",
        "pipeline",
        "overview",
        "system",
        "workflow",
        "flow",
        "method",
        "network",
        "diagram",
        "overview",
        "proposed",
        "框架",
        "流程",
        "结构",
        "系统",
    ):
        if term in caption:
            score += 20.0
    try:
        with Image.open(figure.path) as image:
            width, height = image.size
    except OSError:
        return score
    ratio = width / max(height, 1)
    area = width * height
    if 1.2 <= ratio <= 2.8:
        score += 8.0
    if 500_000 <= area <= 2_800_000:
        score += 4.0
    return score


def _one_sentence(paper: dict[str, Any], reading: PaperReading | None = None) -> str:
    terms = set(paper.get("matched_terms", []))
    if {"spoofing", "jamming", "interference"} & terms:
        return "这篇论文的核心是把 GNSS 干扰/欺骗从“信号异常”转成可观测、可检测、可比较的接收机状态变化，并比较 AGC、C/N0 等接收机内部观测量在检测任务中的价值。"
    if {"fusion", "multi-sensor", "multimodal"} & terms:
        return "这篇论文的核心是回答多传感器融合系统在 GNSS 受限、传感器退化或场景变化时，如何用可配置的观测组合维持稳定定位和一致建图。"
    if {"slam", "odometry", "mapping"} & terms:
        return "这篇论文的核心是把局部几何、匹配约束或地图表达做得更可靠，从而改进 SLAM/里程计在复杂几何、稀疏点云或退化场景下的状态估计。"
    return "这篇论文适合从问题定义、观测设计、约束建模和工程可迁移性四个角度快速阅读。"


def _story_intro(paper: dict[str, Any], reading: PaperReading) -> str:
    terms = set(paper.get("matched_terms", []))
    title = paper["title"]
    if {"spoofing", "jamming", "interference"} & terms:
        return (
            f"可以把《{title}》想成一个“定位系统值班员”的故事：系统平时相信 GNSS，"
            "但一旦有人开始干扰或欺骗，最终经纬度跳变往往已经是后果。作者想做的是把告警提前，"
            "从接收机内部的 AGC、C/N0、检测量这些细小变化里，判断信号环境是不是开始不对劲。"
            f"{_section_hint(reading.abstract, '摘要')}"
        )
    if {"fusion", "multi-sensor", "multimodal"} & terms:
        return (
            f"《{title}》讲的是一个多传感器团队协作的故事：LiDAR、相机、IMU、GNSS 各自都有长处，"
            "也都会在某些场景里掉链子。论文关心的不是把传感器堆得越多越好，而是当某个传感器失效、"
            "某段场景退化或 GNSS 不可靠时，系统还能不能用同一套逻辑继续定位和建图。"
            f"{_section_hint(reading.abstract, '摘要')}"
        )
    return (
        f"《{title}》可以当成一个“机器人怎样不迷路”的故事：前端看到的是稀疏、嘈杂、动态的世界，"
        "后端却需要输出连续、可信的轨迹和地图。作者的切入点通常是让几何表示、匹配约束或地图更新更稳，"
        "减少一个局部错误一路放大成全局漂移。"
        f"{_section_hint(reading.abstract, '摘要')}"
    )


def _chapter_walkthrough(paper: dict[str, Any], reading: PaperReading) -> list[tuple[str, str]]:
    terms = set(paper.get("matched_terms", []))
    if {"spoofing", "jamming", "interference"} & terms:
        fallback_method = (
            "方法章通常先搭建可控的 GNSS 干扰/欺骗场景，再把接收机输出的 AGC、C/N0 或检测器响应拉到同一时间轴上。"
            "通俗地说，它不是直接问“位置有没有错”，而是先问“接收机是不是已经开始用力自救”。"
        )
        fallback_exp = (
            "实验章的重点是把干扰区间和观测曲线对齐：弱干扰时谁先响应，强干扰时谁稳定触发，正常波动时谁更不容易误报。"
            "这决定了它能不能进入真实完整性监测链路。"
        )
    elif {"fusion", "multi-sensor", "multimodal"} & terms:
        fallback_method = (
            "方法章通常在讲传感器如何分工：IMU 给短时运动先验，LiDAR/视觉给几何约束，GNSS 给全局约束。"
            "真正的看点是这些约束如何进入滤波器、因子图或后端优化，以及系统如何给不可靠观测降权。"
        )
        fallback_exp = (
            "实验章要重点看传感器缺失、GNSS denied、几何退化和跨场景测试。只在所有传感器都正常时表现好，"
            "还不能说明系统能上真实平台。"
        )
    else:
        fallback_method = (
            "方法章通常解释作者怎样重新组织局部几何、匹配关系或地图表达。通俗地说，"
            "它是在告诉 SLAM 系统哪些点更可信、哪些约束更该相信，以及怎样避免错误匹配拖垮整条轨迹。"
        )
        fallback_exp = (
            "实验章需要把轨迹误差、地图质量、消融实验和失败案例一起看。平均误差下降当然重要，"
            "但更关键的是退化场景里是否更稳。"
        )

    return [
        (
            "摘要：先把故事讲成一句话",
            _section_narrative(
                reading.abstract,
                "摘要通常先交代问题、方法和结论。读这篇时，可以先抓三个词：它面对什么定位风险，用什么观测或模型解决，最后用什么实验说明有效。",
            ),
        ),
        (
            "引言：为什么这个问题非做不可",
            _section_narrative(
                reading.introduction,
                "引言部分是在搭舞台：真实系统里 GNSS 会被遮挡、欺骗或干扰，传感器会退化，SLAM 会漂移。作者要说服读者，这不是一个漂亮数据集上的小修小补，而是部署时迟早会撞上的问题。",
            ),
        ),
        (
            "方法：作者真正搭了哪台机器",
            _section_narrative(reading.method, fallback_method),
        ),
        (
            "实验：证据链是否站得住",
            _section_narrative(reading.experiments, fallback_exp),
        ),
        (
            "结论：论文留下了什么边界",
            _section_narrative(
                reading.conclusion,
                "结论部分要反过来看：作者承认了哪些边界，哪些场景还没覆盖，哪些模块以后还要加强。工程读者最该带走的不是一个分数，而是它能迁移到自己系统里的哪一层。",
            ),
        ),
    ]


def _chapter_markdown(chapters: list[tuple[str, str]]) -> list[str]:
    lines: list[str] = []
    for index, (title, body) in enumerate(chapters, start=1):
        lines.extend([f"### {index}. {title}", "", body, ""])
    return lines


def _chapter_cards(chapters: list[tuple[str, str]]) -> str:
    cards = []
    for index, (title, body) in enumerate(chapters, start=1):
        cards.append(
            '<section style="margin:0 0 12px;padding:14px 15px;background:#f7fbfb;'
            'border:1px solid #e0eeee;border-radius:8px;">'
            f'<p style="margin:0 0 8px;color:#0b9984;font-size:14px;font-weight:800;">{index}. {html.escape(title)}</p>'
            f'<p style="margin:0;color:#40545c;font-size:14px;line-height:1.9;">{html.escape(body)}</p>'
            "</section>"
        )
    return "".join(cards)


def _section_narrative(section_text: str, fallback: str) -> str:
    if not section_text:
        return fallback
    keywords = _keyword_hits(
        section_text,
        (
            "GNSS",
            "GPS",
            "AGC",
            "CNO",
            "LiDAR",
            "visual",
            "camera",
            "inertial",
            "IMU",
            "SLAM",
            "odometry",
            "mapping",
            "detection",
            "jamming",
            "spoofing",
            "fusion",
            "robust",
            "dataset",
            "benchmark",
            "experiment",
        ),
    )
    keyword_text = f"文中这一段反复出现的线索是 {', '.join(keywords[:6])}。" if keywords else ""
    return (
        f"{fallback}"
        f"{keyword_text}"
        "把它翻成工程语言，就是先确认输入观测是否可信，再看这些观测如何变成约束、告警或地图更新，最后看实验有没有覆盖真实失败模式。"
    )


def _section_hint(section_text: str, label: str) -> str:
    keywords = _keyword_hits(section_text, ("GNSS", "AGC", "CNO", "LiDAR", "visual", "inertial", "SLAM", "odometry", "mapping", "detection", "jamming", "spoofing", "fusion", "robust"))
    if not keywords:
        return ""
    return f" 从{label}抽取到的线索看，后文会围绕 {', '.join(keywords[:5])} 展开。"


def _problem_context(paper: dict[str, Any], reading: PaperReading) -> list[str]:
    terms = set(paper.get("matched_terms", []))
    title = paper["title"]
    if {"spoofing", "jamming", "interference"} & terms:
        return [
            "GNSS 在铁路、无人系统和车载定位里常被当作全局位置来源，但它面对干扰、欺骗和遮挡时很脆弱；只看最终位置跳变，往往已经太晚。",
            "这类论文真正关心的不是“能不能检测到一次异常”，而是能不能在低成本接收机和真实噪声背景下稳定地区分干扰、正常波动和接收机状态变化。",
            _evidence_sentence(reading, "从论文线索看，作者把接收机内部观测量作为检测依据，而不是只依赖最终 PVT 结果。"),
        ]
    if {"fusion", "multi-sensor", "multimodal"} & terms:
        return [
            "多传感器融合的难点不是把 LiDAR、相机、IMU、GNSS 都接进系统，而是在不同场景下知道哪些观测可信、哪些观测应该降权或剔除。",
            "GNSS 受限、几何退化、动态物体和跨会话环境变化都会破坏单一传感器假设，因此论文通常要证明系统在这些不完美条件下仍能闭环工作。",
            f"从题目《{title}》看，重点不只是单点精度，而是传感器组合、可配置性和大场景一致建图能力。",
        ]
    return [
        "SLAM/里程计论文的背景通常是：前端几何估计不稳定会一路传导到后端优化，最后表现为漂移、错配或地图撕裂。",
        "复杂几何、低分辨率 LiDAR、稀疏区域和动态场景会让手工几何估计变得脆弱，因此作者往往试图让局部几何或匹配约束更可靠。",
        f"从题目《{title}》看，这篇论文适合重点关注它如何定义局部几何、如何训练/估计，以及它是否真的改善 SLAM 轨迹和地图质量。",
    ]


def _source_clues(paper: dict[str, Any], reading: PaperReading) -> list[str]:
    text = " ".join(part for part in (reading.abstract, reading.conclusion) if part)
    terms = set(paper.get("matched_terms", []))
    if not text:
        return [
            "这篇论文的机器可读文本结构不完整，因此解读主要依据题名、图表和论文元数据；正式引用实验结论前仍建议回到原文逐段核对。",
            "阅读时可以先围绕图表建立主线，再回到方法和实验部分确认作者的变量定义、阈值和数据集设置。",
        ]

    keywords = _keyword_hits(text, ("GNSS", "AGC", "CNO", "LiDAR", "visual", "inertial", "SLAM", "odometry", "mapping", "detection", "jamming", "spoofing", "fusion", "robust"))
    clues = []
    if {"spoofing", "jamming", "interference"} & terms:
        clues.append("原文开篇把问题放在 GNSS 完整性和交通自动化背景下，因此这不是单纯的信号处理实验，而是面向安全关键定位的异常检测问题。")
        clues.append("文本线索显示作者关注接收机内部观测量和干扰检测之间的关系；读者应把 AGC/CNO 当作检测链路中的状态量，而不是普通曲线。")
    elif {"fusion", "multi-sensor", "multimodal"} & terms:
        clues.append("原文主线围绕多传感器融合的稳定定位展开；阅读时要追踪每个传感器提供的是先验、运动约束、几何约束还是全局约束。")
        clues.append("如果论文强调 configurable、cross-session 或 dense mapping，就要额外关注系统在传感器缺失和场景变化下是否仍保持同一套估计逻辑。")
    else:
        clues.append("原文主线围绕 SLAM/里程计中的几何表达或估计稳定性展开；阅读时要把局部几何、匹配关系和后端优化联系起来看。")
        clues.append("如果作者引入自监督、学习式几何或新地图表达，关键是看它最终如何影响轨迹误差、局部地图质量和退化场景鲁棒性。")

    if keywords:
        clues.append(f"从可抽取文本中反复出现的术语看，建议跟踪这些线索：{', '.join(keywords[:8])}。")
    return clues


def _research_questions(paper: dict[str, Any], reading: PaperReading) -> list[str]:
    terms = set(paper.get("matched_terms", []))
    if {"spoofing", "jamming", "interference"} & terms:
        return [
            "AGC、C/N0 等接收机观测量能否比定位结果更早反映干扰？",
            "在不同干扰强度和时间区间下，哪个检测器更敏感，哪个更容易漏检？",
            "如果把检测结果接入多传感器定位系统，能否作为 GNSS 观测权重或完整性标志使用？",
        ]
    if {"fusion", "multi-sensor", "multimodal"} & terms:
        return [
            "系统能否在不同传感器组合下保持同一套估计框架，而不是为每种组合重写一套管线？",
            "LiDAR、视觉、IMU、GNSS 在前端或后端分别提供什么约束，失效时如何降级？",
            "论文的实验是否覆盖大尺度、退化、跨会话或 GNSS 受限场景，而不只是理想数据集？",
        ]
    return [
        "局部几何到底如何被表示：协方差、平面、曲率、对应关系，还是可学习的几何特征？",
        "这种表示如何进入 SLAM：影响点云匹配、残差权重、后端约束，还是地图更新？",
        "实验是否证明它改善了轨迹精度、收敛速度和退化场景稳定性，而不是只在可视化上更好看？",
    ]


def _method_points(paper: dict[str, Any], reading: PaperReading) -> list[str]:
    terms = set(paper.get("matched_terms", []))
    if {"spoofing", "jamming", "interference"} & terms:
        return [
            "输入层：构造或回放 GNSS 信号，并叠加可控干扰；同时记录接收机输出的 C/N0、AGC gain 等内部状态量。",
            "检测层：把 AGC/CNO 的变化转成事件边界或检测标志，核心是判断这些变化是否和干扰区间一致。",
            "对比层：分别评估 AGC-based detector、CNO-based detector 的响应差异，看低功率干扰、强干扰和不同时间段下的漏检情况。",
            "工程层：最值得借鉴的是“先检测观测可信度，再决定 GNSS 是否参与定位融合”的思路。",
        ]
    if {"fusion", "multi-sensor", "multimodal"} & terms:
        return [
            "输入层：系统通常接收 LiDAR、视觉、IMU、GNSS 等异构数据；第一步是时间同步、外参标定和异常观测筛除。",
            "估计层：论文的关键通常在滤波器、因子图或后端优化中，把不同观测写成可统一处理的约束。",
            "退化处理：真正要看的不是传感器都正常时的表现，而是 GNSS 缺失、视觉退化、LiDAR 几何不足时系统如何降级。",
            "地图层：如果论文强调 dense mapping 或 cross-session localization，就要看地图表达是否支持长期维护和跨场景复用。",
        ]
    return [
        "输入层：从点云、局部邻域或连续帧中构造几何信息，重点看局部结构是否足够稳定。",
        "表示层：把几何关系编码为协方差、曲面、对应关系或可学习特征，目标是减少稀疏和噪声带来的不稳定。",
        "优化层：这些几何信息会进入匹配、残差权重、回环或地图更新，最终影响轨迹和地图一致性。",
        "验证层：最有说服力的是消融实验和退化场景对比，能说明新增模块不是只带来额外计算量。",
    ]


def _experiment_points(paper: dict[str, Any], reading: PaperReading) -> list[str]:
    terms = set(paper.get("matched_terms", []))
    if {"spoofing", "jamming", "interference"} & terms:
        return [
            "先看实验场景是否可控：干扰信号如何生成、持续多久、功率如何变化、是否有无干扰基线。",
            "再看指标是否和任务一致：检测任务要看漏检、误检、检测延迟，而不只是画出曲线变化。",
            "图里的 AGC/CNO 曲线要和干扰区间对齐看；如果弱干扰下某个指标不响应，就说明它不能单独作为完整性判据。",
        ]
    if {"fusion", "multi-sensor", "multimodal"} & terms:
        return [
            "先看数据集覆盖面：室内/室外、城市峡谷、隧道、跨会话、GNSS denied 是否真的出现。",
            "再看消融实验：去掉 GNSS、视觉、LiDAR、IMU 后，系统是否还能稳定工作。",
            "最后看计算代价：多模态融合容易堆模块，公众号读者最该关心实时性、资源占用和失败案例。",
        ]
    return [
        "先看轨迹指标：绝对轨迹误差、相对位姿误差、回环前后漂移是否明显改善。",
        "再看地图质量：局部结构是否更锐利，重建是否有重影、撕裂或尺度漂移。",
        "最后看消融和泛化：只在一个数据集有效的几何模块，工程迁移价值会打折。",
    ]


def _contribution_and_limits(paper: dict[str, Any], reading: PaperReading) -> list[str]:
    terms = set(paper.get("matched_terms", []))
    if {"spoofing", "jamming", "interference"} & terms:
        return [
            "贡献：把 GNSS 干扰检测落到接收机可观测量上，使检测逻辑更接近真实系统可以在线获取的数据。",
            "贡献：通过不同检测器对比，帮助判断 AGC 与 C/N0 在低功率和强干扰下的适用边界。",
            "局限：如果干扰类型、接收机型号、天线环境变化，阈值和检测规律可能需要重新标定。",
            "局限：检测到干扰不等于完成鲁棒定位，还需要和 INS/视觉/LiDAR 等融合模块共同决定 GNSS 权重。",
        ]
    if {"fusion", "multi-sensor", "multimodal"} & terms:
        return [
            "贡献：把多种传感器约束放到统一定位/建图框架里，降低了单一传感器退化带来的系统风险。",
            "贡献：如果系统支持多种组合，就更接近真实平台，因为工程现场经常会遇到某个传感器缺失或质量下降。",
            "局限：多模态系统高度依赖同步和标定，论文指标好不代表部署后也能稳定复现。",
            "局限：dense mapping 或大尺度建图可能带来显著计算和存储成本，需要看实时性边界。",
        ]
    return [
        "贡献：围绕局部几何或地图表达改进 SLAM 的关键薄弱环节，有助于减少前端错误向后端传播。",
        "贡献：如果实验包含消融和退化场景，说明方法不只是调参，而是在机制上提高了鲁棒性。",
        "局限：局部几何方法通常依赖点云密度、传感器噪声和场景结构，跨平台迁移需要重新验证。",
        "局限：如果训练或参数选择依赖特定数据集，部署到新城市、新建筑或低成本雷达时可能退化。",
    ]


def _engineering_points(paper: dict[str, Any], reading: PaperReading) -> list[str]:
    terms = set(paper.get("matched_terms", []))
    if {"spoofing", "jamming", "interference"} & terms:
        return [
            "复现第一步：记录原始 GNSS 观测和接收机状态量，不要只保存最终经纬度。",
            "复现第二步：把干扰/异常区间标注出来，分别评估 AGC、C/N0、残差和定位跳变的响应。",
            "工程接入：把检测结果输出为 GNSS 可信度分数，用来调整融合定位里的观测协方差或剔除策略。",
            "上线前检查：不同接收机、不同天线、不同城市环境都要重新校准阈值，避免把遮挡误判为攻击。",
        ]
    if {"fusion", "multi-sensor", "multimodal"} & terms:
        return [
            "复现第一步：先搭最小可运行组合，例如 LiDAR+IMU 或 VIO，再逐步加入 GNSS/视觉/热成像等额外观测。",
            "复现第二步：建立传感器质量监控，记录同步误差、外参漂移、观测残差和异常剔除比例。",
            "工程接入：不要把 GNSS 当作永远正确的全局约束，而应把它和干扰检测、完整性监测一起接入。",
            "上线前检查：设计传感器失效实验，例如遮挡相机、降低 LiDAR 特征、模拟 GNSS 跳变，看系统能否优雅降级。",
        ]
    return [
        "复现第一步：确认论文新增模块位于前端、后端还是地图表达层，避免把整个系统一次性重写。",
        "复现第二步：先在公开数据集上复现轨迹指标，再看局部地图和失败案例，不要只看平均误差。",
        "工程接入：如果模块只改变局部几何或权重，可以优先做成可插拔前端，而不是侵入整个 SLAM 后端。",
        "上线前检查：用低纹理、稀疏点云、动态物体和闭环失败场景做压力测试。",
    ]


def _followup_questions(paper: dict[str, Any]) -> list[str]:
    terms = set(paper.get("matched_terms", []))
    if {"spoofing", "jamming", "interference"} & terms:
        return [
            "如果攻击不是线性 chirp，而是更隐蔽的 spoofing 或 meaconing，指标是否仍然敏感？",
            "检测器能否输出连续可信度，而不是只输出 0/1 告警？",
            "和 IMU、视觉、LiDAR 融合后，GNSS 异常检测应该在前端、后端还是完整性监测层处理？",
        ]
    if {"fusion", "multi-sensor", "multimodal"} & terms:
        return [
            "哪一个传感器失效时系统最脆弱，论文有没有给出清晰的降级路径？",
            "标定误差和时间同步误差对结果影响有多大？",
            "如果换成低成本传感器或更大规模地图，计算和存储是否还能接受？",
        ]
    return [
        "新增几何模块在极端稀疏或动态场景中是否仍有效？",
        "它提升的是前端匹配质量，还是后端优化的稳定性？",
        "如果不使用作者的数据集和参数，方法是否仍能泛化？",
    ]


def _figure_reading(paper: dict[str, Any], reading: PaperReading, figure: DeepDiveFigure, index: int) -> str:
    caption = figure.caption.lower()
    terms = set(paper.get("matched_terms", []))
    if "setup" in caption or "framework" in caption or "architecture" in caption or "system" in caption or "overview" in caption or "pipeline" in caption:
        return "这张图适合当作论文的“主地图”来读：左侧通常是传感器或数据输入，中间是同步、融合、检测、建图或优化模块，右侧是定位、地图或告警输出。读它时不要急着看细节，先沿着箭头走一遍数据流，就能知道作者到底把创新点放在前端观测、后端优化，还是系统组织方式上。"
    if {"spoofing", "jamming", "interference"} & terms:
        if index == 1:
            return "把这张图当成“观测量响应图”来读：干扰发生时，接收机前端的 AGC、C/N0 或检测量会出现同步变化。阅读重点不是曲线本身，而是变化是否清晰、是否和干扰区间对齐、弱干扰时是否仍能被看见。"
        return "第二张图通常更接近“检测结果图”或“对比图”：重点比较不同检测器在同一时间轴上的响应差异，尤其是低功率干扰是否漏检、强干扰是否稳定触发。"
    if {"fusion", "multi-sensor", "multimodal"} & terms:
        if index == 1:
            return "这类图通常展示大场景重建、轨迹或系统输出。读图时先看地图是否连续、轨迹是否闭合，再看它是否体现多传感器融合带来的稳定性，而不是只看视觉效果是否漂亮。"
        return "第二张图适合看对比和细节：不同传感器组合、不同场景或不同退化条件下，系统是否还能保持地图一致和定位稳定。"
    if {"slam", "odometry", "mapping"} & terms:
        if index == 1:
            return "这类图往往是在解释几何建模或约束构造。读图时先分清输入点、局部几何、对应关系和位姿变换分别是什么，再看这些量如何进入 SLAM 前端或后端。"
        return "这张图更适合看结果验证：轨迹是否贴近真值、迭代是否收敛、地图或局部结构是否因为新模块变得更稳定。"
    if "agc" in caption or "cno" in caption or "detection" in caption:
        return "读这张图时不要只看曲线是否变化，而要把变化和干扰发生区间对齐：AGC 的突降、C/N0 的下降或检测脉冲，分别代表接收机前端增益控制、卫星信号质量和检测器输出。真正有价值的是弱干扰下谁先响应、谁漏检。"
    if "map" in caption or "mapping" in caption or "trajectory" in caption or "odometry" in caption:
        return "这类图要同时看轨迹和地图：轨迹是否闭合、地图是否重影、转弯和长走廊是否漂移。漂亮的可视化不等于鲁棒，最好结合数值指标和失败案例一起判断。"
    if index == 1:
        return "先把这张图当成系统结构图看：输入是什么、核心模块在哪里、输出怎样被用于检测或定位，是判断论文能否迁移的第一步。"
    return "这张图更适合看实验验证逻辑：关注曲线或模块之间的差异，而不是只看作者给出的结论。"


def _authors(paper: dict[str, Any]) -> str:
    authors = paper.get("authors") or []
    if len(authors) <= 4:
        return ", ".join(authors)
    return ", ".join(authors[:4]) + " 等"


def _commentary_author() -> str:
    return os.getenv("WECHAT_AUTHOR", "波波机器人")


def _wechat_title(paper: dict[str, Any]) -> str:
    title = "论文解读｜" + paper["title"]
    return title[:64]


def _digest(paper: dict[str, Any]) -> str:
    return _one_sentence(paper)[:120]


def _is_publish_unauthorized(message: str) -> bool:
    lowered = message.lower()
    return "48001" in lowered or "api unauthorized" in lowered


def _slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9.]+", "-", value)
    return value.strip("-")[:70] or "paper"


def _section_title(text: str) -> str:
    return (
        '<section style="margin:28px 0 14px;">'
        '<p style="margin:0 0 7px;width:42px;height:4px;background:#25d8b8;border-radius:2px;"></p>'
        f'<h2 style="margin:0;color:#122b34;font-size:21px;line-height:1.45;font-weight:800;">{html.escape(text)}</h2>'
        "</section>"
    )


def _paragraph(text: str) -> str:
    return f'<p style="margin:0 0 16px;color:#43565d;font-size:15px;line-height:1.9;">{html.escape(text)}</p>'


def _numbered_cards(items: list[str]) -> str:
    cards = []
    for index, item in enumerate(items, start=1):
        cards.append(
            '<section style="margin:0 0 10px;padding:13px 14px;background:#f7fbfb;'
            'border:1px solid #e0eeee;border-radius:8px;">'
            f'<p style="margin:0;color:#40545c;font-size:14px;line-height:1.85;"><strong style="color:#0b9984;">{index}.</strong> {html.escape(item)}</p>'
            "</section>"
        )
    return "".join(cards)


def _markdown_bullets(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items]


def _evidence_sentence(reading: PaperReading, fallback: str) -> str:
    text = reading.abstract or reading.conclusion
    if not text:
        return fallback
    keywords = []
    for token in ("AGC", "CNO", "GNSS", "LiDAR", "visual", "inertial", "SLAM", "odometry", "mapping", "detection"):
        if token.lower() in text.lower():
            keywords.append(token)
    if not keywords:
        return fallback
    return f"从摘要和图注线索看，论文反复围绕 {', '.join(list(dict.fromkeys(keywords))[:5])} 展开，说明这些量就是阅读时应优先跟踪的主线。"


def _keyword_hits(text: str, candidates: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    hits = []
    for candidate in candidates:
        if candidate.lower() in lowered:
            hits.append(candidate)
    return hits


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate per-paper deep-dive articles with figures extracted from PDFs.")
    parser.add_argument("--input-json", default=Path("outputs/2026-07-03-gnss-slam-digest.json"), type=Path)
    parser.add_argument("--output-dir", default=Path("outputs/deepdives"), type=Path)
    parser.add_argument("--limit", default=3, type=int)
    parser.add_argument("--figures", default=2, type=int)
    parser.add_argument("--publish-mode", choices=("none", "draft", "publish"), default="none")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
