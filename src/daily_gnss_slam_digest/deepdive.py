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

from .notify import (
    NotificationResult,
    describe_notification_result,
    notify_automation_summary,
    notify_publish_issue,
    step_notifications_suppressed,
    wechat_backend_url,
)
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
    draft_email_items: list[dict[str, Any]] = []
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
            wechat_html = build_deepdive_html(paper, reading, figures, image_urls, include_title=False)
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
            draft_email_items.append(
                {
                    "title": title,
                    "media_id": media_id,
                    "source_url": paper.get("url"),
                    "html_path": html_path,
                    "md_path": md_path,
                }
            )
            print(f"Created WeChat deep-dive draft media_id: {media_id}")
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
    if draft_email_items:
        print(
            describe_notification_result(
                _notify_deepdive_drafts_created(
                    drafts=draft_email_items,
                    publish_mode=args.publish_mode,
                    manifest=manifest,
                    publish_blocked_reason=publish_blocked_reason,
                    publish_results=publish_results,
                )
            )
        )
    if publish_failed:
        return 4
    return 0


def _notify_deepdive_drafts_created(
    *,
    drafts: list[dict[str, Any]],
    publish_mode: str,
    manifest: Path,
    publish_blocked_reason: str | None,
    publish_results: list[dict[str, Any]],
) -> NotificationResult:
    if step_notifications_suppressed():
        return NotificationResult(False, "step email notification suppressed")

    lines = [
        "论文解读草稿：已创建",
        "",
        "【关键信息】",
        f"- 数量：{len(drafts)} 篇",
        f"- 模式：{publish_mode}",
        f"- 公众号草稿箱：{wechat_backend_url()}",
        f"- 输出清单：{manifest.resolve()}",
        "",
        "【草稿】",
    ]
    for index, draft in enumerate(drafts, start=1):
        lines.extend(
            [
                f"{index}. {draft['title']}",
                f"   media_id：{draft['media_id']}",
            ]
        )

    if publish_blocked_reason:
        lines.extend(["", "【发布提醒】", f"- 正式发布已跳过：{publish_blocked_reason}"])
    if publish_results:
        lines.extend(["", "【发布结果】"])
        for result in publish_results:
            status = result.get("status", "unknown")
            reason = result.get("reason")
            line = f"- {result.get('media_id', '')}: {status}"
            if reason:
                line += f"；{reason}"
            lines.append(line)

    lines.extend(["", "请到公众号后台草稿箱检查排版、封面和图片后再发布。"])
    return notify_automation_summary(subject=f"公众号论文解读草稿已创建｜{len(drafts)}篇", lines=lines)


def build_deepdive_markdown(
    paper: dict[str, Any],
    reading: PaperReading,
    figures: list[DeepDiveFigure],
    image_map: dict[str, str],
) -> str:
    title = _article_title(paper)
    chapters = _chapter_walkthrough(paper, reading)
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
        "## 读前抓手",
        "",
        *_markdown_bullets(_source_clues(paper, reading)),
        "",
        "## 故事版导读",
        "",
        _story_intro(paper, reading),
        "",
        "## 章节精读",
        "",
        *_chapter_markdown(chapters[:2]),
        "### 3. 主图和关键图解：先沿着数据流走一遍",
        "",
    ]
    for i, figure in enumerate(figures, start=1):
        key = f"figure_{i}"
        figure_caption = _display_figure_caption(figure.caption, i)
        lines.extend(
            [
                f"![{figure_caption}]({image_map.get(key, figure.path.name)})",
                "",
                figure_caption,
                "",
                _figure_reading(paper, reading, figure, i),
                "",
            ]
        )

    lines.extend(
        [
            *_chapter_markdown(chapters[2:], start=4),
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
    *,
    include_title: bool = True,
) -> str:
    title = _article_title(paper)
    chapters = _chapter_walkthrough(paper, reading)
    parts = [
        '<section style="max-width:677px;margin:0 auto;color:#24343a;font-family:-apple-system,BlinkMacSystemFont,Helvetica Neue,Arial,sans-serif;">',
    ]
    if include_title:
        parts.append(f'<h1 style="margin:0 0 14px;color:#10272f;font-size:22px;line-height:1.45;font-weight:800;">{html.escape(title)}</h1>')
    parts.extend(
        [
        '<section style="margin:0 0 18px;padding:15px 16px;background:#f5fbfa;border-left:4px solid #25d8b8;color:#33484f;font-size:14px;line-height:1.9;">',
        f"作者：{html.escape(_commentary_author())}<br/>",
        f"论文作者：{html.escape(_authors(paper))}<br/>",
        f"日期：{html.escape(str(paper.get('published', ''))[:10])}<br/>",
        f'原文：<a href="{html.escape(paper.get("url", ""))}" style="color:#0b9984;text-decoration:none;">{html.escape(paper.get("url", ""))}</a>',
        "</section>",
        _section_title("一句话读懂"),
        _paragraph(_one_sentence(paper, reading)),
        _section_title("读前抓手"),
        _numbered_cards(_source_clues(paper, reading)),
        _section_title("故事版导读"),
        _paragraph(_story_intro(paper, reading)),
        _section_title("章节精读"),
        _chapter_cards(chapters[:2]),
        _inline_chapter_title(3, "主图和关键图解：先沿着数据流走一遍"),
        ]
    )

    for i, figure in enumerate(figures, start=1):
        key = f"figure_{i}"
        src = image_map.get(key, figure.path.name)
        figure_caption = _display_figure_caption(figure.caption, i)
        parts.extend(
            [
                '<section style="margin:0 0 22px;padding:14px;border:1px solid #e1eeee;border-radius:10px;background:#ffffff;">',
                f'<img src="{html.escape(src)}" alt="{html.escape(figure_caption)}" style="display:block;width:100%;height:auto;border-radius:6px;"/>',
                f'<p style="margin:10px 0 8px;color:#0b9984;font-size:13px;font-weight:700;line-height:1.6;">{html.escape(figure_caption)}</p>',
                f'<p style="margin:0;color:#43565d;font-size:14px;line-height:1.85;">{html.escape(_figure_reading(paper, reading, figure, i))}</p>',
                "</section>",
            ]
        )

    parts.extend(
        [
            _chapter_cards(chapters[2:], start=4),
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
            caption = _clean_figure_caption(match.group(1))
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
        return _clean_figure_caption(captions[index - 1])
    return f"论文原图 {index}（从 PDF 直接提取）"


def _display_figure_caption(caption: str, display_index: int) -> str:
    caption = _clean_figure_caption(caption)
    match = re.match(r"^(?:Fig(?:ure)?\.?)\s*(\d+)\s*[.:]?\s*(.*)$", caption, re.IGNORECASE)
    prefix = "主图" if display_index == 1 else "论文图"
    if match:
        body = _short_figure_caption_body(match.group(2))
        return f"{prefix}：{body}" if body else prefix
    body = _short_figure_caption_body(caption)
    return f"{prefix}：{body}" if body else prefix


def _clean_figure_caption(caption: str) -> str:
    caption = " ".join(caption.split())
    caption = re.sub(r"([A-Za-z])-\s+([a-z])", r"\1\2", caption)
    caption = caption.replace("ﬁ", "fi").replace("ﬂ", "fl")
    return caption.strip()


def _short_figure_caption_body(caption: str) -> str:
    caption = _clean_figure_caption(caption)
    if not caption:
        return ""
    first_sentence = re.split(r"(?<=[.!?])\s+", caption, maxsplit=1)[0]
    first_sentence = first_sentence.rstrip(" .。")
    if len(first_sentence) <= 82:
        return first_sentence
    return first_sentence[:79].rstrip(" -:：,，.;。") + "..."


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
        "setup",
        "experimental setup",
        "infrastructure",
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
    reading = reading or PaperReading("", "", "", "", "", ())
    profile = _domain_profile(paper, reading)
    facts = _paper_facts(paper, reading)
    claim = facts.get("method") or facts.get("finding") or facts.get("problem")
    if claim:
        return (
            f"这篇论文围绕{profile['actor']}遇到的“{profile['problem']}”展开，"
            f"核心看点是{_claim_to_plain_chinese(claim, profile, 'method')}。"
        )
    return f"这篇论文值得按“{profile['problem']} -> {profile['method']} -> {profile['experiment']}”这条线读。"


def _story_intro(paper: dict[str, Any], reading: PaperReading) -> str:
    profile = _domain_profile(paper, reading)
    facts = _paper_facts(paper, reading)
    title = _display_title(paper)
    opening = _claim_to_plain_chinese(facts.get("problem", ""), profile, "problem")
    method = _claim_to_plain_chinese(facts.get("method", ""), profile, "method")
    experiment = _claim_to_plain_chinese(facts.get("experiment", ""), profile, "experiment")
    ending = _claim_to_plain_chinese(facts.get("finding", ""), profile, "finding")
    return (
        f"读《{title}》时，可以先把主角放在{profile['scene']}里："
        f"{opening}。作者接着把镜头推到做法上，重点是{method}。"
        f"到了实验部分，证据会落在{experiment}。最后再回到工程问题：{ending}。"
        f"这样读下来，论文就不是一堆模块名，而是一条从风险、动作、证据到落地边界的线。"
    )


def _chapter_walkthrough(paper: dict[str, Any], reading: PaperReading) -> list[tuple[str, str, tuple[str, ...]]]:
    profile = _domain_profile(paper, reading)
    facts = _paper_facts(paper, reading)
    return [
        (
            "背景和问题：先看矛盾从哪来",
            _section_narrative(
                reading.introduction or _abstract_text(paper, reading),
                profile,
                "problem",
                facts.get("problem", ""),
            ),
            tuple(_chapter_points(paper, reading, "problem", 4)),
        ),
        (
            "方法拆解：把做法拆成输入、核心动作和输出",
            _section_narrative(
                reading.method or _abstract_text(paper, reading),
                profile,
                "method",
                facts.get("method", ""),
            ),
            tuple(_chapter_points(paper, reading, "method", 5)),
        ),
        (
            "实验验证：看数据、场景和指标是否对得上问题",
            _section_narrative(
                reading.experiments or _abstract_text(paper, reading),
                profile,
                "experiment",
                facts.get("experiment", ""),
            ),
            tuple(_chapter_points(paper, reading, "experiment", 5)),
        ),
        (
            "贡献边界和复现：把亮点翻成工程判断",
            _section_narrative(
                reading.conclusion or _abstract_text(paper, reading),
                profile,
                "finding",
                facts.get("finding", ""),
            ),
            tuple(_chapter_points(paper, reading, "finding", 4)),
        ),
    ]


def _chapter_markdown(chapters: list[tuple[str, str, tuple[str, ...]]], start: int = 1) -> list[str]:
    lines: list[str] = []
    for index, (title, body, points) in enumerate(chapters, start=start):
        lines.extend([f"### {index}. {title}", "", body, ""])
        if points:
            lines.extend([*_markdown_bullets(list(points)), ""])
    return lines


def _chapter_cards(chapters: list[tuple[str, str, tuple[str, ...]]], start: int = 1) -> str:
    cards = []
    for index, (title, body, points) in enumerate(chapters, start=start):
        point_html = ""
        if points:
            point_html = "".join(
                f'<p style="margin:8px 0 0;color:#40545c;font-size:14px;line-height:1.8;">'
                f'<strong style="color:#0b9984;">{point_index}.</strong> {html.escape(point)}</p>'
                for point_index, point in enumerate(points, start=1)
            )
        cards.append(
            '<section style="margin:0 0 12px;padding:14px 15px;background:#f7fbfb;'
            'border:1px solid #e0eeee;border-radius:8px;">'
            f'<p style="margin:0 0 8px;color:#0b9984;font-size:14px;font-weight:800;">{index}. {html.escape(title)}</p>'
            f'<p style="margin:0;color:#40545c;font-size:14px;line-height:1.9;">{html.escape(body)}</p>'
            f"{point_html}"
            "</section>"
        )
    return "".join(cards)


def _section_narrative(section_text: str, profile: dict[str, str], role: str, fallback_claim: str = "") -> str:
    claim = fallback_claim or _pick_sentence(section_text, _role_terms(profile, role), role)
    anchor = _claim_to_plain_chinese(claim, profile, role)
    if role == "problem":
        return (
            f"这一节先给问题定边界：主角是{profile['actor']}，压力来自{profile['problem']}。"
            f"{anchor}。读到这里要抓住两个变量：系统相信了什么输入，以及这个输入在什么条件下会失真。"
        )
    if role == "method":
        return (
            f"方法部分可以拆成三步：先确认输入数据，再看作者怎样构造{profile['method']}，"
            f"最后看输出如何服务于{profile['engineering']}。{anchor}。"
            "这一步要把每个模块和它消耗的观测量对上号。"
        )
    if role == "experiment":
        return (
            f"实验部分要回答“证据够不够”。这篇的证据应落在{profile['experiment']}。"
            f"{anchor}。读表格和曲线时，把数据来源、对比对象、失败场景和指标单位放在一起看。"
        )
    return (
        f"收束部分要看作者把贡献限定在哪里。对工程读者来说，关键不是记住一个新名字，"
        f"而是判断它能否接到{profile['engineering']}。{anchor}。"
    )


def _source_clues(paper: dict[str, Any], reading: PaperReading) -> list[str]:
    profile = _domain_profile(paper, reading)
    facts = _paper_facts(paper, reading)
    terms = _paper_terms(paper, reading)
    clues = [
        f"先圈题目里的关键词：{', '.join(terms[:8]) or _display_title(paper)}。它们把文章带到{profile['scene']}，后文要追的是{profile['problem']}。",
        f"摘要给出的第一条线索是：{_claim_to_plain_chinese(facts.get('problem', ''), profile, 'problem')}。这决定了文章不是只看最终效果，而是在追踪问题怎样发生。",
        f"第二条线索落在做法：{_claim_to_plain_chinese(facts.get('method', ''), profile, 'method')}。读方法时优先找输入、假设、核心运算和输出。",
    ]
    if reading.captions:
        caption_terms = _paper_terms_from_text(" ".join(reading.captions))[:5]
        if caption_terms:
            clues.append(f"图注里反复出现 {', '.join(caption_terms)}，说明主图很可能承载了系统流程、实验设置或结果对比。")
    quality = paper.get("quality_signals") or {}
    if paper.get("code_url") or quality.get("code_signal"):
        clues.append("这篇有代码或复现线索，读完方法后可以直接检查代码是否覆盖数据预处理、训练/检测和评估脚本。")
    elif quality.get("dataset_signal"):
        clues.append("这篇有数据集或 benchmark 线索，实验部分要重点看数据来源是否贴近真实部署场景。")
    return clues


def _chapter_points(paper: dict[str, Any], reading: PaperReading, role: str, limit: int) -> list[str]:
    profile = _domain_profile(paper, reading)
    source = _section_source(paper, reading, role)

    claims = _select_sentences(source, _role_terms(profile, role), limit)
    labels = {
        "problem": ("场景压力", "失效来源", "作者抓住的变量", "这对定位系统的影响"),
        "method": ("输入/观测", "核心步骤", "模型或检测量", "输出形式", "接入方式"),
        "experiment": ("数据来源", "实验场景", "对比指标", "结果读法", "失败边界"),
        "finding": ("主要贡献", "适用条件", "工程收益", "需要复核的边界"),
    }[role]

    points: list[str] = []
    for label, claim in zip(labels, claims):
        points.append(f"{label}：{_point_from_claim(label, claim, profile, role)}。")
    while len(points) < min(limit, len(labels)):
        label = labels[len(points)]
        points.append(f"{label}：{_fallback_point(profile, role, label, source)}。")
    return points


def _followup_questions(paper: dict[str, Any]) -> list[str]:
    reading = PaperReading(str(paper.get("abstract") or ""), "", "", "", "", ())
    profile = _domain_profile(paper, reading)
    terms = _paper_terms(paper, reading)
    first_term = terms[0] if terms else profile["actor"]
    return [
        f"如果把 {first_term} 换到自己的机器人或车辆平台，最先需要重新标定的是输入数据、阈值，还是传感器外参？",
        f"论文里的证据是否覆盖了{profile['scene']}里最容易失败的场景，还是只证明了一个受控设置？",
        f"这套做法接入{profile['engineering']}时，应该输出连续可信度、离散告警，还是直接改变优化权重？",
    ]


def _figure_reading(paper: dict[str, Any], reading: PaperReading, figure: DeepDiveFigure, index: int) -> str:
    profile = _domain_profile(paper, reading)
    caption = figure.caption
    caption_terms = _paper_terms_from_text(caption)
    lowered = caption.lower()
    evidence = f"图注里的关键词是 {', '.join(caption_terms[:5])}。" if caption_terms else ""
    if any(term in lowered for term in ("setup", "framework", "architecture", "system", "overview", "pipeline", "workflow", "flow")):
        return (
            f"这张图适合当作全文路线图：按“输入 -> {profile['method']} -> 输出”走一遍，"
            f"就能看清作者把创新放在观测、模型、检测还是优化环节。{evidence}"
        )
    if any(term in lowered for term in ("experiment", "evaluation", "result", "performance", "benchmark", "table")):
        return (
            f"这张图要和实验段落一起读：先确认数据来自哪里，再看指标怎样衡量{profile['problem']}是否被缓解。"
            f"{evidence}曲线或柱状图最有价值的地方，是能不能解释强弱场景、失败样本和对比方法之间的差异。"
        )
    if any(term in lowered for term in ("map", "mapping", "trajectory", "odometry", "localization", "pose")):
        return (
            f"这张图在展示定位或建图结果。先看轨迹连续性、地图重影、回环前后变化，再回到正文确认这些变化由哪些观测支撑。{evidence}"
        )
    if any(term in lowered for term in ("gnss", "gps", "spoof", "jamming", "interference", "timing", "signal")):
        return (
            f"这张图围绕信号或时间轴展开。读图时把异常输入、接收机状态和最终告警连起来，"
            f"看作者是否把{profile['problem']}从现象拆成了可测量的变量。{evidence}"
        )
    if index == 1:
        return (
            f"主图先用来建立文章地图：谁是输入，谁在中间处理，谁是输出。"
            f"有了这条线，再读方法和实验就不会被模块名绕住。{evidence}"
        )
    return f"这张图放在后面看细节：它要么补充实验对比，要么解释某个模块的内部变量。读的时候把它和{profile['experiment']}对应起来。{evidence}"


def _domain_profile(paper: dict[str, Any], reading: PaperReading) -> dict[str, str]:
    text = _combined_text(paper, reading).lower()
    terms = set(str(term).lower() for term in paper.get("matched_terms", []))
    if terms & {"spoofing", "jamming", "interference", "integrity", "pnt"} or any(
        token in text for token in ("gnss", "gps", "spoof", "jamming", "interference", "pnt", "timing protection")
    ):
        return {
            "actor": "GNSS/PNT 接收机以及依赖它的车辆、机器人或授时系统",
            "scene": "开放环境里的定位、导航和授时链路",
            "problem": "外部信号可能被伪造、压制或缓慢拉偏，系统却还会输出看似可信的位置或时间",
            "method": "接收机观测、攻击构造、检测统计量、保护级或轻量模型",
            "experiment": "真实设备、回放信号、公开攻击数据、误报漏报、时间误差或部署算力",
            "engineering": "GNSS 可信度评估、融合定位降权、告警策略和完整性监测",
        }
    if any(token in text for token in ("slam", "odometry", "mapping", "lidar", "imu", "visual", "camera", "3dgs", "gaussian")):
        return {
            "actor": "移动机器人定位与建图系统",
            "scene": "室内外移动机器人、自动驾驶或大尺度建图场景",
            "problem": "单一传感器会在遮挡、稀疏几何、动态物体或长距离运行中失去稳定约束",
            "method": "传感器融合、几何约束、地图表达、回环检测或学习式前端",
            "experiment": "轨迹误差、地图一致性、传感器退化、跨数据集对比和实时性",
            "engineering": "SLAM 前端/后端、地图维护、传感器降级和部署算力预算",
        }
    if any(token in text for token in ("navigation", "planning", "embodied", "language", "policy", "manipulation")):
        return {
            "actor": "需要把感知、决策和行动连起来的机器人",
            "scene": "真实或仿真的自主导航、任务执行和人机交互场景",
            "problem": "高层任务描述和底层运动控制之间存在语义、几何和安全约束的落差",
            "method": "视觉语言模型、策略学习、地图记忆、路径规划或任务分解",
            "experiment": "任务成功率、泛化场景、交互成本、失败恢复和真实平台验证",
            "engineering": "机器人任务规划、在线决策、可解释失败分析和安全约束",
        }
    return {
        "actor": "定位、感知或机器人系统",
        "scene": "复杂真实场景中的自主系统部署",
        "problem": "观测存在噪声、缺失或分布变化，系统仍要输出可信结果",
        "method": "问题建模、观测设计、算法约束和实验验证",
        "experiment": "数据来源、对比基线、指标定义、消融实验和失败案例",
        "engineering": "可复现实现、参数标定、部署成本和风险控制",
    }


def _paper_facts(paper: dict[str, Any], reading: PaperReading) -> dict[str, str]:
    abstract = _abstract_text(paper, reading)
    profile = _domain_profile(paper, reading)
    return {
        "problem": _pick_sentence(
            _section_source(paper, reading, "problem"),
            ("challenge", "problem", "threat", "exposed", "difficult", "risk", "limited", "robust", "vulnerable"),
            "problem",
        ),
        "method": _pick_sentence(
            _section_source(paper, reading, "method"),
            ("propose", "present", "introduce", "develop", "investigate", "approach", "pipeline", "framework", "model", "monitor", "search"),
            "method",
        ),
        "experiment": _pick_sentence(
            _section_source(paper, reading, "experiment"),
            ("experiment", "evaluate", "validated", "dataset", "benchmark", "results", "tested", "calibrated", "simulation"),
            "experiment",
        ),
        "finding": _pick_sentence(
            _section_source(paper, reading, "finding"),
            ("show", "demonstrate", "result", "improve", "outperform", "contribution", "provide", "open source", "susceptible"),
            "finding",
        )
        or f"{profile['method']}最终要服务于{profile['engineering']}",
    }


def _claim_to_plain_chinese(claim: str, profile: dict[str, str], role: str) -> str:
    evidence = _evidence_summary(claim)
    if role == "problem":
        base = f"{profile['actor']}面对的核心风险是{profile['problem']}"
    elif role == "method":
        base = f"方法主线是围绕{profile['method']}把输入、处理和输出连起来"
    elif role == "experiment":
        base = f"实验主线是用{profile['experiment']}验证问题是否真的被触碰到"
    else:
        base = f"结论要落到{profile['engineering']}"
    return f"{base}；{evidence}" if evidence else base


def _point_from_claim(label: str, claim: str, profile: dict[str, str], role: str) -> str:
    evidence = _evidence_summary(claim)
    if role == "problem":
        if label == "场景压力":
            return f"{evidence}，说明论文把问题放在{profile['scene']}里看，定位结果会继续影响后续通信、控制或授时"
        if label == "失效来源":
            return f"{evidence}，危险点在于输入被污染后，{profile['actor']}仍可能给出像正常一样的输出"
        if label == "作者抓住的变量":
            return f"{evidence}，这就是后文要反复跟踪的观测量、攻击参数或系统状态"
        return f"{evidence}，影响会从单个观测扩散到{profile['engineering']}"
    if role == "method":
        if label == "输入/观测":
            return f"{evidence}，先确认这些输入是实测、回放、仿真，还是由模型生成"
        if label == "核心步骤":
            return f"{evidence}，把这些步骤按时间顺序串起来，就是论文的主处理链"
        if label == "模型或检测量":
            return f"{evidence}，读到这里要分清哪些是可测变量，哪些是作者构造出的判断量"
        if label == "输出形式":
            return f"{evidence}，输出必须能被后续模块消费，才有机会接入{profile['engineering']}"
        return f"{evidence}，工程接入时要明确它改变告警、权重、地图还是控制决策"
    if role == "experiment":
        if label == "数据来源":
            return f"{evidence}，先看数据来自真实设备、公开数据集还是仿真环境"
        if label == "实验场景":
            return f"{evidence}，场景越贴近{profile['scene']}，结论越值得迁移"
        if label == "对比指标":
            return f"{evidence}，这里要看指标是否直接对应{profile['problem']}"
        if label == "结果读法":
            return f"{evidence}，重点不是单个数值好看，而是强弱场景和失败样本能否解释得通"
        return f"{evidence}，这些边界决定方法换平台后要重新标定什么"
    if label == "主要贡献":
        return f"{evidence}，贡献要回到{profile['engineering']}才有工程价值"
    if label == "适用条件":
        return f"{evidence}，这些条件决定论文结论能不能迁移到自己的传感器和场景"
    if label == "工程收益":
        return f"{evidence}，真正的收益是减少误信、漂移、漏检或计算开销"
    return f"{evidence}，复现时要优先检查数据、参数、同步和评价脚本"


def _fallback_point(profile: dict[str, str], role: str, label: str, source: str = "") -> str:
    details = _detail_tokens(source)
    numbers = _numbers_and_units(source)
    if role == "problem":
        if details:
            return f"围绕 {', '.join(details[:4])}，把{profile['problem']}拆成可观察的输入变化"
        return f"围绕{profile['actor']}，把{profile['problem']}拆成可观察的输入变化"
    if role == "method":
        if label == "核心步骤" and details:
            return f"把 {', '.join(details[:5])} 串成流程，确认每一步的输入和输出"
        if label == "模型或检测量" and details:
            return f"重点跟踪 {', '.join(details[:5])}，看它们是观测量、模型模块还是实验设备"
        if label == "输出形式":
            return f"输出要能回到{profile['engineering']}，否则方法只停留在离线演示"
        if label == "接入方式":
            return f"把结果接到{profile['engineering']}时，要明确它改变的是告警、权重、地图还是控制决策"
        return f"检查{profile['method']}分别消耗什么输入、产生什么中间量、怎样输出给后续模块"
    if role == "experiment":
        if numbers:
            return f"数字线索包括 {', '.join(numbers[:5])}，先看这些数字对应场景强度、速度、误差还是算力"
        if details:
            return f"围绕 {', '.join(details[:5])} 复核数据来源、测试平台和对比对象"
        return f"把{profile['experiment']}和论文声称要解决的问题逐项对齐"
    if details:
        return f"把 {', '.join(details[:4])} 放回{profile['engineering']}，判断它是否能进入自己的系统"
    return f"把{label}落回{profile['engineering']}，判断它是否能进入自己的系统"


def _evidence_summary(claim: str) -> str:
    details = _detail_tokens(claim)
    numbers = _numbers_and_units(claim)
    if details and numbers:
        return f"线索落在 {', '.join(details[:4])}，数字包括 {', '.join(numbers[:4])}"
    if details:
        return f"线索落在 {', '.join(details[:5])}"
    if numbers:
        return f"数字线索包括 {', '.join(numbers[:5])}"
    phrase = _short_evidence(claim, max_words=16)
    return f"短句线索是 {phrase}" if phrase else "这一段给出的证据需要回到原文细读"


def _abstract_text(paper: dict[str, Any], reading: PaperReading) -> str:
    return str(paper.get("abstract") or "") or reading.abstract


def _section_source(paper: dict[str, Any], reading: PaperReading, role: str) -> str:
    abstract = _abstract_text(paper, reading)
    if role == "problem":
        candidate = reading.introduction
    elif role == "method":
        candidate = reading.method
    elif role == "experiment":
        candidate = reading.experiments
    else:
        candidate = reading.conclusion
    if not candidate or _section_is_noisy(candidate):
        return abstract
    if abstract and abstract not in candidate:
        return f"{candidate} {abstract}"
    return candidate


def _section_is_noisy(text: str) -> bool:
    lowered = text.lower()
    if any(token in lowered[:800] for token in ("arxiv:", "funded by", "copyright", "personal use of this material")):
        return True
    sentences = _sentence_candidates(text)
    return len(sentences) < 2 and len(text) > 350


def _combined_text(paper: dict[str, Any], reading: PaperReading) -> str:
    return " ".join(
        part
        for part in (
            str(paper.get("title") or ""),
            str(paper.get("abstract") or ""),
            reading.abstract,
            reading.introduction,
            reading.method,
            reading.experiments,
            reading.conclusion,
            " ".join(reading.captions),
            " ".join(str(term) for term in paper.get("matched_terms", [])),
        )
        if part
    )


def _paper_terms(paper: dict[str, Any], reading: PaperReading) -> list[str]:
    candidates = [str(term) for term in paper.get("matched_terms", [])]
    candidates.extend(_paper_terms_from_text(_combined_text(paper, reading)))
    seen: dict[str, str] = {}
    for term in candidates:
        clean = term.strip()
        if not clean:
            continue
        key = clean.lower()
        seen.setdefault(key, clean if clean.isupper() else _canonical_term(clean))
    return list(seen.values())


def _paper_terms_from_text(text: str) -> list[str]:
    candidates = (
        "GNSS",
        "GPS",
        "PNT",
        "SLAM",
        "LiDAR",
        "IMU",
        "VIO",
        "C/N0",
        "AGC",
        "SDR",
        "V2X",
        "3DGS",
        "spoofing",
        "jamming",
        "interference",
        "integrity",
        "timing",
        "localization",
        "navigation",
        "mapping",
        "odometry",
        "fusion",
        "visual",
        "camera",
        "robot",
        "planning",
        "benchmark",
        "dataset",
        "open source",
        "quantization",
        "pruning",
        "architecture search",
    )
    return _keyword_hits(text, candidates)


def _canonical_term(term: str) -> str:
    mapping = {
        "gnss": "GNSS",
        "gps": "GPS",
        "pnt": "PNT",
        "slam": "SLAM",
        "lidar": "LiDAR",
        "imu": "IMU",
        "vio": "VIO",
        "cno": "C/N0",
        "c/n0": "C/N0",
        "agc": "AGC",
        "sdr": "SDR",
        "v2x": "V2X",
        "3dgs": "3DGS",
    }
    return mapping.get(term.lower(), term)


def _role_terms(profile: dict[str, str], role: str) -> tuple[str, ...]:
    common = tuple(_paper_terms_from_text(" ".join(profile.values())))
    if role == "problem":
        return common + ("challenge", "problem", "threat", "risk", "vulnerable", "degradation", "failure", "noise", "attack")
    if role == "method":
        return common + ("propose", "present", "method", "framework", "pipeline", "algorithm", "model", "monitor", "estimator", "search")
    if role == "experiment":
        return common + ("experiment", "evaluation", "dataset", "benchmark", "result", "validated", "tested", "simulation", "metric")
    return common + ("contribution", "show", "demonstrate", "improve", "outperform", "limitation", "future", "open source")


def _pick_sentence(text: str, include: tuple[str, ...] = (), role: str = "") -> str:
    selected = _select_sentences(text, include, 1, role=role)
    return selected[0] if selected else ""


def _select_sentences(text: str, include: tuple[str, ...], limit: int, *, role: str = "") -> list[str]:
    candidates = _sentence_candidates(text)
    if not candidates:
        return []
    scored = []
    include_lower = tuple(item.lower() for item in include if item)
    for position, sentence in enumerate(candidates):
        lowered = sentence.lower()
        score = max(0, 8 - position)
        score += sum(4 for term in include_lower if term in lowered)
        if re.search(r"\d", sentence):
            score += 3
        if any(token in lowered for token in ("we ", "this paper", "our ", "propose", "present", "introduce", "show", "demonstrate")):
            score += 3
        if role == "experiment" and any(token in lowered for token in ("experiment", "dataset", "benchmark", "result", "validated", "tested")):
            score += 6
        if role == "method" and any(token in lowered for token in ("propose", "pipeline", "framework", "model", "method", "algorithm")):
            score += 6
        scored.append((score, position, sentence))
    scored.sort(key=lambda item: (-item[0], item[1]))
    selected: list[str] = []
    seen_phrases: set[str] = set()
    for _score, _position, sentence in scored:
        key = _short_evidence(sentence, max_words=10).lower()
        if key in seen_phrases:
            continue
        seen_phrases.add(key)
        selected.append(sentence)
        if len(selected) >= limit:
            break
    return selected


def _sentence_candidates(text: str) -> list[str]:
    clean = _clean_text(text)
    if not clean:
        return []
    pieces = re.split(r"(?<=[.!?。！？])\s+", clean)
    candidates: list[str] = []
    for piece in pieces:
        sentence = piece.strip(" -")
        if not sentence:
            continue
        if len(sentence) < 45 and not re.search(r"\d", sentence):
            continue
        if len(sentence) > 420:
            sentence = sentence[:420].rsplit(" ", 1)[0].rstrip(" ,;:") + "."
        lowered = sentence.lower()
        if lowered.startswith(("references", "acknowledg", "copyright")):
            continue
        if any(token in lowered for token in ("arxiv:", "funded by", "personal use of this material")):
            continue
        if re.match(r"^\d+\s+figure\s+\d+", lowered):
            continue
        if lowered.count("[") >= 3 and len(sentence) < 260:
            continue
        candidates.append(sentence)
    return candidates


def _short_evidence(text: str, max_words: int = 22, max_chars: int = 132) -> str:
    text = _clean_text(text)
    if not text:
        return ""
    words = text.split()
    if len(words) > max_words:
        text = " ".join(words[:max_words]).rstrip(" ,;:-") + "..."
    if len(text) > max_chars:
        text = text[: max_chars - 3].rstrip(" ,;:-") + "..."
    return text


def _numbers_and_units(text: str) -> list[str]:
    patterns = (
        r"\b\d+(?:\.\d+)?\s?(?:km/h|m/s|ms|ns|s|dB|Hz|kHz|MHz|GHz|m|km|%|x)\b",
        r"\b\d+/\d+\b",
        r"\b\d+(?:\.\d+)?\s?(?:pages|figures|tables|scenarios|devices)\b",
    )
    values: list[str] = []
    for pattern in patterns:
        values.extend(match.group(0) for match in re.finditer(pattern, text, flags=re.IGNORECASE))
    return list(dict.fromkeys(values))


def _detail_tokens(text: str) -> list[str]:
    tokens = _paper_terms_from_text(text)
    tokens.extend(
        match.group(0).strip()
        for match in re.finditer(r"\b[A-Z][A-Za-z0-9/+.-]{2,}(?:\s+[A-Z][A-Za-z0-9/+.-]{2,}){0,2}\b", text)
    )
    for phrase in (
        "Haversine distance",
        "temporal discretization",
        "linear interpolation",
        "baseband signal",
        "coordinate generation",
        "architecture search",
        "structured pruning",
        "static quantization",
        "raw pseudoranges",
        "broadcast ephemeris",
        "cross-satellite consistency",
    ):
        if phrase.lower() in text.lower():
            tokens.append(phrase)
    cleaned: dict[str, str] = {}
    stop_terms = {
        "the",
        "this",
        "under",
        "within",
        "both",
        "first",
        "second",
        "third",
        "yet",
        "it",
        "future work the",
        "future work",
        "and future work the",
        "controlled testbench",
        "common attack pattern",
    }
    for token in tokens:
        token = token.strip(" ,.;:()[]")
        token = re.sub(r"\s+", " ", token)
        token = re.sub(r"\b(The|This|Under|Within|Both)$", "", token).strip()
        if token.lower() in stop_terms:
            continue
        if len(token) < 3:
            continue
        cleaned.setdefault(token.lower(), _canonical_term(token))
    return list(cleaned.values())


def _authors(paper: dict[str, Any]) -> str:
    authors = paper.get("authors") or []
    if len(authors) <= 4:
        return ", ".join(authors)
    return ", ".join(authors[:4]) + " 等"


def _commentary_author() -> str:
    return os.getenv("WECHAT_AUTHOR", "波波机器人")


def _article_title(paper: dict[str, Any]) -> str:
    return "论文解读｜" + _display_title(paper)


def _display_title(paper: dict[str, Any]) -> str:
    return _normalize_title(str(paper.get("title") or "Untitled paper"))


def _normalize_title(value: str) -> str:
    title = _clean_text(value)
    title = re.sub(
        r"\$?\s*\\sum_\{?i=0\}?\^\{?5\}?\s*C_5\^i\s*\$?",
        "32",
        title,
    )
    title = re.sub(r"\$([^$]+)\$", r"\1", title)
    title = title.replace("\\", "")
    title = re.sub(r"\s+", " ", title).strip()
    if "LXD-SLAM" in title and "32" in title and "Configurable Sensor Combinations" in title:
        return "LXD-SLAM：LiDAR+X 稠密 SLAM，32 种传感器组合"
    return title


def _wechat_title(paper: dict[str, Any]) -> str:
    display_title = _display_title(paper)
    lowered = display_title.lower()
    if "jamming" in lowered and "agc" in lowered:
        return "论文解读｜GNSS干扰检测：AGC与C/N0"
    if "lxd-slam" in lowered:
        return "论文解读｜LXD-SLAM：32种传感器组合"
    if "self-supervised" in lowered and "geometry" in lowered:
        return "论文解读｜LiDAR SLAM自监督几何推理"
    title = "论文解读｜" + display_title
    if len(title) <= 34:
        return title
    return title[:31].rstrip(" -:：,，") + "..."


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


def _inline_chapter_title(index: int, text: str) -> str:
    return (
        '<section style="margin:0 0 12px;padding:14px 15px;background:#f7fbfb;'
        'border:1px solid #e0eeee;border-radius:8px;">'
        f'<p style="margin:0;color:#0b9984;font-size:14px;font-weight:800;">{index}. {html.escape(text)}</p>'
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
