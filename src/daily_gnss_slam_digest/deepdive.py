from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from io import BytesIO
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
    source: str = "paper"
    children: tuple[str, ...] = ()


@dataclass(frozen=True)
class PaperReading:
    abstract: str
    introduction: str
    method: str
    experiments: str
    conclusion: str
    captions: tuple[str, ...]


@dataclass(frozen=True)
class TextPolishResult:
    mode: str
    reason: str = ""
    texts: dict[str, str] | None = None


@dataclass(frozen=True)
class FigureCaptionAnchor:
    page_index: int
    page_width: float
    page_height: float
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    caption: str
    figure_number: str


FIGURE_SECTION_ORDER = ("intro", "method", "experiment")
FIGURE_SECTION_SOURCES = {
    "intro_group": "intro",
    "method_group": "method",
    "experiment_group": "experiment",
    "paper_composite": "experiment",
}
PAPER_CHAPTER_ROLES = ("intro", "method", "experiment", "discussion")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    papers = json.loads(args.input_json.read_text(encoding="utf-8"))[: args.limit]
    if not papers:
        print("No papers found.", file=sys.stderr)
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    article_runtime_items: list[dict[str, Any]] = []
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
        variants = _image_variants(args.image_mode)

        pdf_path = paper_dir / "paper.pdf"
        _download(paper["pdf_url"], pdf_path)

        captions = _extract_figure_captions(pdf_path)
        reading = _build_reading(pdf_path, captions)
        paper_figures = _extract_figures(
            pdf_path,
            paper_dir,
            captions,
            max_figures=_figure_pool_size(args.figures),
            figure_keywords=_split_keywords(args.figure_keywords),
        )
        fallback_figures: list[DeepDiveFigure] = []
        if not paper_figures and "paper" in variants:
            fallback_figures = _render_fallback_figures(pdf_path, paper_dir, max_figures=args.figures)
        source_figures = paper_figures or fallback_figures

        for variant in variants:
            figures, cover_figure = _figures_for_variant(
                variant=variant,
                paper=paper,
                reading=reading,
                source_figures=source_figures,
                output_dir=paper_dir,
                max_figures=args.figures,
            )
            if not figures:
                print(f"No figures available for {variant} deep dive: {paper.get('title', '')}", file=sys.stderr)

            text_polish = _generate_text_polish(paper, reading, figures)
            image_runtime_mode = _image_runtime_mode(variant, figures)
            local_image_map = {f"figure_{i}": figure.path.name for i, figure in enumerate(figures, start=1)}
            markdown = build_deepdive_markdown(paper, reading, figures, local_image_map, text_polish=text_polish)
            html_text = build_deepdive_html(paper, reading, figures, local_image_map, text_polish=text_polish)

            article_stem = _article_stem(variant, variants)
            md_path = paper_dir / f"{article_stem}.md"
            html_path = paper_dir / f"{article_stem}.html"
            md_path.write_text(markdown, encoding="utf-8")
            html_path.write_text(html_text, encoding="utf-8")
            created.append(html_path)
            article_runtime_items.append(
                {
                    "variant": variant,
                    "html_path": str(html_path),
                    "md_path": str(md_path),
                    "content_mode": text_polish.mode,
                    "content_reason": text_polish.reason,
                    "image_mode": image_runtime_mode,
                }
            )
            print(f"Wrote {variant} deep dive: {html_path}")

            if publisher and access_token:
                cover_media_id = None
                if cover_figure and os.getenv("DEEPDIVE_PAPER_COVER", "1").lower() not in {"0", "false", "no", "off"}:
                    try:
                        cover_result = publisher.upload_permanent_image(access_token, cover_figure.path)
                        cover_media_id = str(cover_result.get("media_id") or "")
                        if cover_media_id:
                            cover_media_ids.append(cover_media_id)
                            print(f"Uploaded {variant} cover media_id: {cover_media_id}")
                    except WeChatPublisherError as exc:
                        print(f"{variant} cover upload failed, using default cover: {exc}", file=sys.stderr)
                image_urls = {
                    f"figure_{i}": publisher.upload_article_image(access_token, figure.path)
                    for i, figure in enumerate(figures, start=1)
                }
                wechat_html = build_deepdive_html(
                    paper,
                    reading,
                    figures,
                    image_urls,
                    include_title=False,
                    text_polish=text_polish,
                )
                title = _wechat_title(paper, variant=variant if len(variants) > 1 else None)
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
                        "pdf_url": paper.get("pdf_url"),
                        "code_url": _paper_code_url(paper),
                        "html_path": str(html_path),
                        "md_path": str(md_path),
                        "content_mode": text_polish.mode,
                        "content_reason": text_polish.reason,
                        "image_mode": image_runtime_mode,
                    }
                )
                print(f"Created WeChat {variant} deep-dive draft media_id: {media_id}")
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
                "articles_detail": article_runtime_items,
                "draft_media_ids": draft_ids,
                "cover_media_ids": cover_media_ids,
                "drafts": draft_email_items,
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
                f"   解读模式：{_content_mode_label(str(draft.get('content_mode') or 'fallback'))}",
                f"   配图模式：{draft.get('image_mode') or '论文原图'}",
                "   解读下载：",
                f"   - HTML版：{_file_url(str(draft.get('html_path') or ''))}",
                f"   - Markdown版：{_file_url(str(draft.get('md_path') or ''))}",
            ]
        )
        source_lines = _draft_source_lines(draft)
        if source_lines:
            lines.append("   阅读原文：")
            lines.extend(f"   - {line}" for line in source_lines)
        reason = str(draft.get("content_reason") or "")
        if str(draft.get("content_mode") or "") not in {"api", "gemini", "siliconflow", "ollama"} and reason:
            lines.append(f"   回退原因：{reason}")

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


def _content_mode_label(mode: str) -> str:
    if mode in {"api", "gemini"}:
        return "AI 润色（Gemini）"
    if mode == "siliconflow":
        return "AI 润色（SiliconFlow）"
    if mode == "ollama":
        return "本地模型润色（Ollama）"
    if mode == "disabled":
        return "传统模板"
    return "传统模板（AI 不可用时回退）"


def _file_url(path_text: str) -> str:
    if not path_text:
        return ""
    try:
        path = Path(path_text)
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.resolve().as_uri()
    except ValueError:
        return path_text


def _draft_source_lines(draft: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for label, key in (("原文页面", "source_url"), ("PDF下载", "pdf_url"), ("代码/项目", "code_url")):
        url = str(draft.get(key) or "").strip()
        if url:
            lines.append(f"{label}：{url}")
    return lines


def build_deepdive_markdown(
    paper: dict[str, Any],
    reading: PaperReading,
    figures: list[DeepDiveFigure],
    image_map: dict[str, str],
    *,
    text_polish: TextPolishResult | None = None,
) -> str:
    title = _article_title(paper)
    chapters = _chapter_walkthrough(paper, reading)
    figure_by_section, supplemental_figures = _section_figures(figures)
    image_by_path = _image_map_by_path(figures, image_map)
    lines = [
        f"# {title}",
        "",
        f"- 作者：{_commentary_author()}",
        f"- 论文作者：{_authors(paper)}",
        f"- 日期：{paper.get('published', '')[:10]}",
        f"- 原文：{paper.get('url', '')}",
        "",
        "## 阅读原文",
        "",
        *_source_links_markdown(paper),
        "",
        "## 一句话读懂",
        "",
        _polished_text(text_polish, "one_sentence", _one_sentence(paper, reading)),
        "",
        "## 读前抓手",
        "",
        *_markdown_bullets(_source_clues(paper, reading)),
        "",
        "## 故事版导读",
        "",
        _polished_text(text_polish, "story_intro", _story_intro(paper, reading)),
        "",
        "## 按论文章节精读",
        "",
    ]
    for index, (role, chapter) in enumerate(zip(PAPER_CHAPTER_ROLES, chapters), start=1):
        lines.extend(_chapter_markdown_one(chapter, role, index, text_polish))
        figure = figure_by_section.get(role)
        if figure:
            lines.extend(
                _figure_markdown_block(
                    paper,
                    reading,
                    figure,
                    image_by_path.get(figure.path, figure.path.name),
                    _figure_display_index(figures, figure),
                    text_polish,
                )
            )

    if supplemental_figures:
        lines.extend(["## 补充图", ""])
        for figure in supplemental_figures:
            lines.extend(
                _figure_markdown_block(
                    paper,
                    reading,
                    figure,
                    image_by_path.get(figure.path, figure.path.name),
                    _figure_display_index(figures, figure),
                    text_polish,
                )
            )

    lines.extend(["## 读完之后可以追问", "", *_markdown_bullets(_followup_questions(paper)), "", f"> {_image_note(figures)}"])
    return "\n".join(lines).strip() + "\n"


def build_deepdive_html(
    paper: dict[str, Any],
    reading: PaperReading,
    figures: list[DeepDiveFigure],
    image_map: dict[str, str],
    *,
    include_title: bool = True,
    text_polish: TextPolishResult | None = None,
) -> str:
    title = _article_title(paper)
    chapters = _chapter_walkthrough(paper, reading)
    figure_by_section, supplemental_figures = _section_figures(figures)
    image_by_path = _image_map_by_path(figures, image_map)
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
        _section_title("阅读原文"),
        _source_links_html(paper),
        _section_title("一句话读懂"),
        _paragraph(_polished_text(text_polish, "one_sentence", _one_sentence(paper, reading))),
        _section_title("读前抓手"),
        _numbered_cards(_source_clues(paper, reading)),
        _section_title("故事版导读"),
        _paragraph(_polished_text(text_polish, "story_intro", _story_intro(paper, reading))),
        _section_title("按论文章节精读"),
        ]
    )

    for index, (role, chapter) in enumerate(zip(PAPER_CHAPTER_ROLES, chapters), start=1):
        parts.append(_chapter_card_one(chapter, role, index, text_polish))
        figure = figure_by_section.get(role)
        if figure:
            parts.append(
                _figure_html_block(
                    paper,
                    reading,
                    figure,
                    image_by_path.get(figure.path, figure.path.name),
                    _figure_display_index(figures, figure),
                    text_polish,
                )
            )

    if supplemental_figures:
        parts.append(_section_title("补充图"))
        for figure in supplemental_figures:
            parts.append(
                _figure_html_block(
                    paper,
                    reading,
                    figure,
                    image_by_path.get(figure.path, figure.path.name),
                    _figure_display_index(figures, figure),
                    text_polish,
                )
            )

    parts.extend(
        [
            _section_title("读完之后可以追问"),
            _numbered_cards(_followup_questions(paper)),
            f'<p style="margin:22px 0 0;color:#8a9da3;font-size:12px;line-height:1.8;">{html.escape(_image_note(figures))}</p>',
            "</section>",
        ]
    )
    return "".join(parts)


def _image_map_by_path(figures: list[DeepDiveFigure], image_map: dict[str, str]) -> dict[Path, str]:
    return {figure.path: image_map.get(f"figure_{index}", figure.path.name) for index, figure in enumerate(figures, start=1)}


def _figure_display_index(figures: list[DeepDiveFigure], figure: DeepDiveFigure) -> int:
    for index, item in enumerate(figures, start=1):
        if item.path == figure.path:
            return index
    return 1


def _section_figures(figures: list[DeepDiveFigure]) -> tuple[dict[str, DeepDiveFigure], list[DeepDiveFigure]]:
    by_section: dict[str, DeepDiveFigure] = {}
    supplemental: list[DeepDiveFigure] = []
    for figure in figures:
        section = _figure_section(figure)
        if section in FIGURE_SECTION_ORDER and section not in by_section:
            by_section[section] = figure
        else:
            supplemental.append(figure)
    return by_section, supplemental


def _figure_markdown_block(
    paper: dict[str, Any],
    reading: PaperReading,
    figure: DeepDiveFigure,
    src: str,
    display_index: int,
    text_polish: TextPolishResult | None,
) -> list[str]:
    figure_caption = _display_figure_caption(figure.caption, display_index, figure.source)
    return [
        f"![{figure_caption}]({src})",
        "",
        figure_caption,
        "",
        _polished_text(text_polish, f"figure:{figure.path.name}", _figure_reading(paper, reading, figure, display_index)),
        "",
    ]


def _figure_html_block(
    paper: dict[str, Any],
    reading: PaperReading,
    figure: DeepDiveFigure,
    src: str,
    display_index: int,
    text_polish: TextPolishResult | None,
) -> str:
    figure_caption = _display_figure_caption(figure.caption, display_index, figure.source)
    return (
        '<section style="margin:0 0 22px;padding:14px;border:1px solid #e1eeee;border-radius:10px;background:#ffffff;">'
        f'<img src="{html.escape(src)}" alt="{html.escape(figure_caption)}" style="display:block;width:100%;height:auto;border-radius:6px;"/>'
        f'<p style="margin:10px 0 8px;color:#0b9984;font-size:13px;font-weight:700;line-height:1.6;">{html.escape(figure_caption)}</p>'
        f'<p style="margin:0;color:#43565d;font-size:14px;line-height:1.85;">'
        f'{html.escape(_polished_text(text_polish, f"figure:{figure.path.name}", _figure_reading(paper, reading, figure, display_index)))}</p>'
        "</section>"
    )


def _chapter_markdown_one(
    chapter: tuple[str, str, tuple[str, ...]],
    role: str,
    index: int,
    text_polish: TextPolishResult | None,
) -> list[str]:
    title, body, points = chapter
    lines = [
        f"### {index}. {_paper_chapter_title(role, title)}",
        "",
        _polished_text(text_polish, _chapter_text_key(role, "body"), body),
        "",
    ]
    if points:
        polished_points = [
            _polished_text(text_polish, _chapter_text_key(role, f"point:{point_index}"), point)
            for point_index, point in enumerate(points, start=1)
        ]
        lines.extend([*_markdown_bullets(polished_points), ""])
    return lines


def _chapter_card_one(
    chapter: tuple[str, str, tuple[str, ...]],
    role: str,
    index: int,
    text_polish: TextPolishResult | None,
) -> str:
    title, body, points = chapter
    point_html = ""
    if points:
        point_html = "".join(
            f'<p style="margin:8px 0 0;color:#40545c;font-size:14px;line-height:1.8;">'
            f'<strong style="color:#0b9984;">{point_index}.</strong> '
            f'{html.escape(_polished_text(text_polish, _chapter_text_key(role, f"point:{point_index}"), point))}</p>'
            for point_index, point in enumerate(points, start=1)
        )
    return (
        '<section style="margin:0 0 12px;padding:14px 15px;background:#f7fbfb;'
        'border:1px solid #e0eeee;border-radius:8px;">'
        f'<p style="margin:0 0 8px;color:#0b9984;font-size:14px;font-weight:800;">{index}. {html.escape(_paper_chapter_title(role, title))}</p>'
        f'<p style="margin:0;color:#40545c;font-size:14px;line-height:1.9;">'
        f'{html.escape(_polished_text(text_polish, _chapter_text_key(role, "body"), body))}</p>'
        f"{point_html}"
        "</section>"
    )


def _chapter_text_key(role: str, suffix: str) -> str:
    return f"chapter:{role}:{suffix}"


def _paper_chapter_title(role: str, fallback: str) -> str:
    titles = {
        "intro": "Introduction：研究背景与问题",
        "method": "Method：方法与系统设计",
        "experiment": "Experiments：实验设置与结果",
        "discussion": "Discussion：结论、边界与复现",
    }
    return titles.get(role, fallback)


def _image_note(figures: list[DeepDiveFigure]) -> str:
    if any(figure.source == "ai" for figure in figures):
        return "概念图为辅助示意图，论文原图来自 PDF；图片仅用于论文解读和学术讨论，正式转载前建议核对论文许可和作者要求。"
    return "图像来自论文 PDF，仅用于论文解读和学术讨论，正式转载前建议核对论文许可和作者要求。"


def _source_links(paper: dict[str, Any]) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    for label, value in (
        ("原文页面", paper.get("url")),
        ("PDF下载", paper.get("pdf_url")),
        ("代码/项目", _paper_code_url(paper)),
    ):
        url = str(value or "").strip()
        if url and url not in {item[1] for item in links}:
            links.append((label, url))
    return links


def _source_links_markdown(paper: dict[str, Any]) -> list[str]:
    links = _source_links(paper)
    if not links:
        return ["- 暂无可跳转的原文链接，请回到论文列表核对。"]
    return [f"- [{label}]({url})" for label, url in links]


def _source_links_html(paper: dict[str, Any]) -> str:
    links = _source_links(paper)
    if not links:
        return _paragraph("暂无可跳转的原文链接，请回到论文列表核对。")
    cards = []
    for label, url in links:
        cards.append(
            '<p style="margin:8px 0 0;color:#40545c;font-size:14px;line-height:1.8;">'
            f'<a href="{html.escape(url)}" style="color:#0b9984;text-decoration:none;">{html.escape(label)}：{html.escape(url)}</a>'
            "</p>"
        )
    return (
        '<section style="margin:0 0 16px;padding:13px 14px;background:#f7fbfb;'
        'border:1px solid #e0eeee;border-radius:8px;">'
        + "".join(cards)
        + "</section>"
    )


def _paper_code_url(paper: dict[str, Any]) -> str:
    direct = str(paper.get("code_url") or "").strip()
    if direct:
        return direct
    signals = paper.get("quality_signals") or {}
    if isinstance(signals, dict):
        for key in ("code_url", "github_url", "project_url"):
            value = str(signals.get(key) or "").strip()
            if value:
                return value
    return ""


def _download(url: str, output: Path) -> None:
    if output.exists() and output.stat().st_size > 0:
        return
    request = urllib.request.Request(url, headers={"User-Agent": "daily-gnss-slam-digest/0.1"})
    last_error: BaseException | None = None
    for attempt in range(1, _download_retries() + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                output.write_bytes(response.read())
            return
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt < _download_retries():
                time.sleep(min(2 * attempt, 8))
    if last_error:
        raise last_error


def _download_retries() -> int:
    try:
        return max(1, int(os.getenv("DEEPDIVE_DOWNLOAD_RETRIES", "3")))
    except ValueError:
        return 3


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


def _extract_figures(
    pdf_path: Path,
    output_dir: Path,
    captions: list[str],
    max_figures: int,
    figure_keywords: tuple[str, ...] = (),
) -> list[DeepDiveFigure]:
    candidates = [
        *_rendered_figure_candidates(pdf_path, output_dir, figure_keywords),
        *_embedded_figure_candidates(pdf_path, output_dir, captions, figure_keywords),
    ]
    candidates.sort(key=lambda item: item[0], reverse=True)

    selected: list[DeepDiveFigure] = []
    seen: set[str] = set()
    for _score, caption, image, source in candidates:
        key = _figure_candidate_key(caption, image)
        if key in seen:
            continue
        seen.add(key)
        out = output_dir / f"figure-{len(selected) + 1}.jpg"
        image.save(out, format="JPEG", quality=92, optimize=True, progressive=True)
        selected.append(DeepDiveFigure(out, caption, source=source))
        if len(selected) >= max_figures:
            break
    return selected


def _embedded_figure_candidates(
    pdf_path: Path,
    output_dir: Path,
    captions: list[str],
    figure_keywords: tuple[str, ...] = (),
) -> list[tuple[float, str, Image.Image, str]]:
    raw_dir = output_dir / "raw_images"
    raw_dir.mkdir(parents=True, exist_ok=True)
    prefix = raw_dir / "img"
    try:
        subprocess.run(["pdfimages", "-j", str(pdf_path), str(prefix)], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return []

    candidates: list[tuple[float, str, Image.Image, str]] = []
    for raw_index, path in enumerate(sorted(raw_dir.iterdir()), start=1):
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
        if _is_low_information_image(image):
            continue
        if _looks_like_icon_or_logo(image):
            continue
        caption = _unmatched_embedded_caption(raw_index)
        score = _paper_figure_score(image, caption, figure_keywords) - 18.0
        candidates.append((score, caption, image, "paper_embedded"))
    return candidates


def _rendered_figure_candidates(
    pdf_path: Path,
    output_dir: Path,
    figure_keywords: tuple[str, ...] = (),
) -> list[tuple[float, str, Image.Image, str]]:
    anchors = _extract_caption_anchors(pdf_path)
    if not anchors:
        return []
    page_limit = _rendered_figure_page_limit()
    anchors = [anchor for anchor in anchors if anchor.page_index <= page_limit]
    if not anchors:
        return []

    render_dir = output_dir / "rendered_figure_pages"
    render_dir.mkdir(parents=True, exist_ok=True)
    prefix = render_dir / "page"
    env = os.environ.copy()
    env.setdefault("XDG_CACHE_HOME", str((output_dir / ".cache").resolve()))
    last_page = min(max(anchor.page_index for anchor in anchors), page_limit)
    try:
        subprocess.run(
            ["pdftoppm", "-r", str(_rendered_figure_dpi()), "-f", "1", "-l", str(last_page), "-png", str(pdf_path), str(prefix)],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
    except (OSError, subprocess.CalledProcessError):
        return []

    candidates: list[tuple[float, str, Image.Image, str]] = []
    for anchor in anchors:
        page_path = _rendered_page_path(render_dir, anchor.page_index)
        if not page_path.exists():
            continue
        try:
            with Image.open(page_path) as page_image:
                image = _crop_rendered_figure(page_image.convert("RGB"), anchor)
        except OSError:
            continue
        width, height = image.size
        area = width * height
        if width < 320 or height < 130 or area < 75_000:
            continue
        if _is_low_information_image(image):
            continue
        score = _paper_figure_score(image, anchor.caption, figure_keywords) + 42.0
        if _caption_keyword_hits(anchor.caption, _rendered_figure_priority_keywords()):
            score += 32.0
        candidates.append((score, anchor.caption, image, "paper_render"))
    return candidates


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
        if _is_low_information_image(image):
            continue
        out = output_dir / f"figure-{i}.jpg"
        image.save(out, format="JPEG", quality=90, optimize=True, progressive=True)
        figures.append(DeepDiveFigure(out, f"论文 PDF 第 {i} 页截图", source="pdf_page"))
    return figures


def _extract_caption_anchors(pdf_path: Path) -> list[FigureCaptionAnchor]:
    try:
        result = subprocess.run(
            ["pdftotext", "-bbox-layout", str(pdf_path), "-"],
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return _parse_caption_anchors(result.stdout)


def _parse_caption_anchors(text: str) -> list[FigureCaptionAnchor]:
    page_re = re.compile(r"<page\s+([^>]*)>(.*?)</page>", re.DOTALL)
    line_re = re.compile(r"<line\s+([^>]*)>(.*?)</line>", re.DOTALL)
    anchors: list[FigureCaptionAnchor] = []
    for page_index, page_match in enumerate(page_re.finditer(text), start=1):
        page_attrs = _bbox_attrs(page_match.group(1))
        page_width = page_attrs.get("width", 0.0)
        page_height = page_attrs.get("height", 0.0)
        if page_width <= 0 or page_height <= 0:
            continue
        lines: list[tuple[dict[str, float], str]] = []
        for line_match in line_re.finditer(page_match.group(2)):
            attrs = _bbox_attrs(line_match.group(1))
            line_text = _bbox_line_text(line_match.group(2))
            if attrs and line_text:
                lines.append((attrs, line_text))
        anchors.extend(_caption_anchors_from_lines(page_index, page_width, page_height, lines))
    return anchors


def _bbox_attrs(text: str) -> dict[str, float]:
    attrs: dict[str, float] = {}
    for key, value in re.findall(r'(\w+)="([^"]*)"', text):
        if key in {"xMin", "xMax", "yMin", "yMax", "width", "height"}:
            try:
                attrs[key] = float(value)
            except ValueError:
                continue
    return attrs


def _bbox_line_text(line_block: str) -> str:
    words = re.findall(r"<word\s+[^>]*>(.*?)</word>", line_block, flags=re.DOTALL)
    return " ".join(html.unescape(word.strip()) for word in words if word.strip())


def _caption_anchors_from_lines(
    page_index: int,
    page_width: float,
    page_height: float,
    lines: list[tuple[dict[str, float], str]],
) -> list[FigureCaptionAnchor]:
    anchors: list[FigureCaptionAnchor] = []
    for index, (attrs, text) in enumerate(lines):
        figure_number = _figure_caption_number(text)
        if not figure_number:
            continue
        bbox = dict(attrs)
        caption_parts = [text]
        cursor = index + 1
        while cursor < len(lines):
            next_attrs, next_text = lines[cursor]
            same_line = abs(next_attrs.get("yMin", 0.0) - bbox.get("yMin", 0.0)) < 3.0
            if same_line:
                caption_parts.append(next_text)
                bbox["xMax"] = max(bbox.get("xMax", 0.0), next_attrs.get("xMax", 0.0))
                bbox["yMax"] = max(bbox.get("yMax", 0.0), next_attrs.get("yMax", 0.0))
                cursor += 1
                continue
            if _is_caption_continuation(next_attrs, next_text, bbox, page_width):
                caption_parts.append(next_text)
                bbox["xMin"] = min(bbox.get("xMin", 0.0), next_attrs.get("xMin", 0.0))
                bbox["xMax"] = max(bbox.get("xMax", 0.0), next_attrs.get("xMax", 0.0))
                bbox["yMax"] = max(bbox.get("yMax", 0.0), next_attrs.get("yMax", 0.0))
                cursor += 1
                continue
            break
        caption = _clean_figure_caption(" ".join(caption_parts))
        anchors.append(
            FigureCaptionAnchor(
                page_index=page_index,
                page_width=page_width,
                page_height=page_height,
                x_min=bbox.get("xMin", 0.0),
                y_min=attrs.get("yMin", 0.0),
                x_max=bbox.get("xMax", 0.0),
                y_max=bbox.get("yMax", attrs.get("yMax", 0.0)),
                caption=caption[:260],
                figure_number=figure_number,
            )
        )
    return anchors


def _figure_caption_number(text: str) -> str:
    match = re.match(r"^Fig(?:ure)?\.?\s*(\d+)(?P<sep>[.:])?\s*(?P<body>.*)$", text.strip(), re.IGNORECASE)
    if not match:
        return ""
    body = match.group("body").strip()
    if body.startswith((",", ";")):
        return ""
    if _caption_body_looks_like_reference(body):
        return ""
    return match.group(1)


def _caption_body_looks_like_reference(body: str) -> bool:
    if not body:
        return False
    first = re.split(r"\s+", body, maxsplit=1)[0].strip(".,:;()[]").lower()
    return first in {
        "and",
        "shows",
        "presents",
        "depicts",
        "illustrates",
        "reports",
        "compares",
        "contains",
        "demonstrates",
        "summarizes",
        "provides",
        "gives",
        "analyzes",
        "where",
        "while",
    }


def _is_caption_continuation(next_attrs: dict[str, float], next_text: str, bbox: dict[str, float], page_width: float) -> bool:
    if _figure_caption_number(next_text):
        return False
    gap = next_attrs.get("yMin", 0.0) - bbox.get("yMax", 0.0)
    if gap < -1.0 or gap > 10.0:
        return False
    if re.match(r"^(?:[IVX]+\.|\d+(?:\.\d+)*\.?)\s+[A-Z]", next_text):
        return False
    left_aligned = abs(next_attrs.get("xMin", 0.0) - bbox.get("xMin", 0.0)) < 32.0
    full_width_caption = bbox.get("xMin", page_width) < page_width * 0.2 and bbox.get("xMax", 0.0) > page_width * 0.72
    return left_aligned or full_width_caption


def _rendered_page_path(render_dir: Path, page_index: int) -> Path:
    return render_dir / f"page-{page_index}.png"


def _rendered_figure_page_limit() -> int:
    try:
        return max(1, int(os.getenv("DEEPDIVE_RENDER_FIGURE_PAGES", "12")))
    except ValueError:
        return 12


def _rendered_figure_dpi() -> int:
    try:
        return max(120, int(os.getenv("DEEPDIVE_RENDER_FIGURE_DPI", "200")))
    except ValueError:
        return 200


def _crop_rendered_figure(page_image: Image.Image, anchor: FigureCaptionAnchor) -> Image.Image:
    scale_x = page_image.width / max(anchor.page_width, 1.0)
    scale_y = page_image.height / max(anchor.page_height, 1.0)
    x0, y0, x1, y1 = _rendered_figure_crop_box(anchor)
    crop = page_image.crop((int(x0 * scale_x), int(y0 * scale_y), int(x1 * scale_x), int(y1 * scale_y)))
    crop = _select_visual_block_above_caption(crop)
    return _trim_white(crop)


def _rendered_figure_crop_box(anchor: FigureCaptionAnchor) -> tuple[float, float, float, float]:
    page_width = anchor.page_width
    center_x = (anchor.x_min + anchor.x_max) / 2
    full_width = anchor.x_min < page_width * 0.18 and anchor.x_max > page_width * 0.72
    margin = 42.0
    gutter = 6.0
    if full_width:
        x0, x1 = margin, page_width - margin
        crop_height = 260.0
    elif center_x < page_width / 2:
        x0, x1 = margin, page_width / 2 - gutter
        crop_height = 280.0
    else:
        x0, x1 = page_width / 2 + gutter, page_width - margin
        crop_height = 280.0
    y1 = max(36.0, anchor.y_min - 4.0)
    y0 = max(36.0, y1 - crop_height)
    return x0, y0, x1, y1


def _select_visual_block_above_caption(image: Image.Image) -> Image.Image:
    if image.height < 80:
        return image
    gray = image.convert("L").resize((image.width, max(1, image.height // 2)))
    active: list[bool] = []
    for y in range(gray.height):
        dark_ratio = sum(1 for x in range(gray.width) if gray.getpixel((x, y)) < 245) / max(gray.width, 1)
        active.append(dark_ratio > 0.025)

    groups: list[tuple[int, int]] = []
    start: int | None = None
    for index, is_active in enumerate([*active, False]):
        if is_active and start is None:
            start = index
        elif not is_active and start is not None:
            if index - start >= 2:
                groups.append((start, index))
            start = None
    if not groups:
        return image

    merged: list[tuple[int, int]] = []
    for group in groups:
        if merged and group[0] - merged[-1][1] < 8:
            merged[-1] = (merged[-1][0], group[1])
        else:
            merged.append(group)

    candidates = [group for group in merged if group[1] > gray.height * 0.22]
    selected = max(candidates or merged, key=lambda group: (group[1], group[1] - group[0]))
    selected_index = merged.index(selected)
    while selected_index > 0 and selected[1] - selected[0] < 55:
        previous = merged[selected_index - 1]
        selected = (previous[0], selected[1])
        selected_index -= 1

    y0 = max(0, selected[0] * 2 - 20)
    y1 = min(image.height, selected[1] * 2 + 20)
    return image.crop((0, y0, image.width, y1))


def _figure_candidate_key(caption: str, image: Image.Image) -> str:
    match = re.match(r"^\s*Fig(?:ure)?\.?\s*(\d+)\b", caption, re.IGNORECASE)
    if match:
        return f"fig:{match.group(1)}"
    normalized = re.sub(r"\W+", "", caption.lower())[:80]
    if normalized:
        return f"caption:{normalized}"
    return f"image:{image.width}x{image.height}"


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


def _is_low_information_image(image: Image.Image) -> bool:
    sample = image.convert("L").resize((min(96, max(1, image.width)), min(96, max(1, image.height))))
    pixels = list(sample.getdata())
    if not pixels:
        return True
    minimum = min(pixels)
    maximum = max(pixels)
    dark_ratio = sum(1 for value in pixels if value < 12) / len(pixels)
    light_ratio = sum(1 for value in pixels if value > 248) / len(pixels)
    if dark_ratio > 0.92 or light_ratio > 0.985:
        return True
    if maximum - minimum < 10:
        return True
    return _ink_ratio(image) < 0.015


def _figure_file_is_usable(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            return not _is_low_information_image(_trim_white(image.convert("RGB")))
    except OSError:
        return False


def _looks_like_icon_or_logo(image: Image.Image) -> bool:
    width, height = image.size
    ratio = width / max(height, 1)
    area = width * height
    if area > 420_000 or not 0.82 <= ratio <= 1.22:
        return False
    sample = image.convert("L").resize((64, 64))
    pixels = list(sample.getdata())
    if not pixels:
        return True
    very_dark = sum(1 for value in pixels if value < 25) / len(pixels)
    very_light = sum(1 for value in pixels if value > 230) / len(pixels)
    return very_dark > 0.25 or very_light > 0.65


def _paper_figure_score(image: Image.Image, caption: str, figure_keywords: tuple[str, ...]) -> float:
    width, height = image.size
    ratio = width / max(height, 1)
    area = width * height
    score = min(area / 60_000, 35.0)
    if 1.15 <= ratio <= 3.8:
        score += 18.0
    elif height > width * 1.18:
        score -= 20.0
    if _caption_keyword_hits(caption, figure_keywords):
        score += 55.0
    lowered = caption.lower()
    if any(term in lowered for term in ("fig.", "figure", "图")):
        score += 4.0
    if any(term in lowered for term in ("table", "tab.", "表 ")):
        score -= 12.0
    return score


def _caption_keyword_hits(caption: str, figure_keywords: tuple[str, ...] = ()) -> list[str]:
    terms = figure_keywords or _default_figure_keywords()
    lowered = caption.lower()
    return [term for term in terms if term and term.lower() in lowered]


def _default_figure_keywords() -> tuple[str, ...]:
    return (
        "framework",
        "architecture",
        "architecture overview",
        "pipeline",
        "overview",
        "system",
        "system overview",
        "workflow",
        "flow",
        "schematic",
        "block diagram",
        "structure",
        "diagram",
        "registration",
        "hash map",
        "voxel",
        "kalman",
        "filter",
        "sensor fusion",
        "setup",
        "experimental setup",
        "method",
        "network",
        "infrastructure",
        "proposed",
        "框架",
        "架构",
        "流程",
        "系统",
        "结构",
        "方法",
        "实验设置",
    )


def _rendered_figure_priority_keywords() -> tuple[str, ...]:
    return (
        "architecture",
        "architecture overview",
        "framework",
        "pipeline",
        "system overview",
        "structure",
        "block diagram",
        "schematic",
        "workflow",
        "flow",
        "hash map",
        "voxel",
        "sensor fusion",
        "kalman",
        "registration",
    )


def _caption_for(captions: list[str], index: int) -> str:
    if 0 <= index - 1 < len(captions):
        return _clean_figure_caption(captions[index - 1])
    return f"论文原图 {index}（从 PDF 直接提取）"


def _unmatched_embedded_caption(index: int) -> str:
    return f"PDF 内嵌图片 {index}（未匹配到可靠图注）"


def _display_figure_caption(caption: str, display_index: int, source: str = "paper") -> str:
    caption = _clean_figure_caption(caption)
    if source == "ai":
        body = _short_figure_caption_body(caption)
        return f"概念图：{body}" if body else "概念图：方法流程示意"
    section = FIGURE_SECTION_SOURCES.get(source)
    if section:
        body = _short_figure_caption_body(_translate_figure_caption(caption))
        prefix = {
            "intro": "Introduction 图组",
            "method": "Method 图组",
            "experiment": "Experiments 图组",
        }[section]
        return f"{prefix}：{body}" if body else prefix
    caption = _translate_figure_caption(caption)
    match = re.match(r"^(?:Fig(?:ure)?\.?)\s*(\d+)\s*[.:]?\s*(.*)$", caption, re.IGNORECASE)
    prefix = "论文图"
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


def _caption_without_figure_number(caption: str) -> str:
    caption = re.sub(r"^\s*图\s*\d+\s*[.．:：、-]*\s*", "", caption)
    caption = re.sub(r"^\s*(?:Fig(?:ure)?\.?)\s*\d+\s*[.:：、-]*\s*", "", caption, flags=re.IGNORECASE)
    return caption.strip()


def _translate_figure_caption(caption: str) -> str:
    caption = _caption_without_figure_number(_clean_figure_caption(caption))
    if not caption:
        return ""
    if not _has_real_figure_caption(caption):
        return "从 PDF 提取的论文原图"

    lowered = caption.lower().rstrip(" .。")
    exact = {
        "system overview": "系统总览",
        "system overview of sa-livo": "SA-LIVO 系统总览",
        "representative mapping results of sa-livo across diverse environments": "SA-LIVO 在多种环境中的代表性建图结果",
        "spoofing attack setup with sdr, obu, rsu, and synthetic trajectory": "包含 SDR、OBU、RSU 和合成轨迹的欺骗攻击设置",
        "functional block diagram of the gps l1 c/a signal simulation and transmis-": "GPS L1 C/A 信号仿真与发射的功能模块图",
    }
    if lowered in exact:
        return exact[lowered]

    translated = caption
    phrase_map = (
        (r"\bSystem Overview\b", "系统总览"),
        (r"\bsystem overview\b", "系统总览"),
        (r"\bRepresentative mapping results\b", "代表性建图结果"),
        (r"\bacross diverse environments\b", "在多种环境中"),
        (r"\bdiverse environments\b", "多种环境"),
        (r"\bproposed framework\b", "所提出的框架"),
        (r"\bproposed method\b", "所提出的方法"),
        (r"\bframework\b", "框架"),
        (r"\barchitecture\b", "架构"),
        (r"\bpipeline\b", "流程"),
        (r"\bworkflow\b", "工作流"),
        (r"\bblock diagram\b", "模块图"),
        (r"\bfunctional block diagram\b", "功能模块图"),
        (r"\bspoofing attack setup\b", "欺骗攻击设置"),
        (r"\bspoofing attack\b", "欺骗攻击"),
        (r"\bsynthetic trajectory\b", "合成轨迹"),
        (r"\bexperimental setup\b", "实验设置"),
        (r"\bsetup\b", "设置"),
        (r"\bmapping results\b", "建图结果"),
        (r"\bmapping\b", "建图"),
        (r"\blocalization\b", "定位"),
        (r"\bodometry\b", "里程计"),
        (r"\btrajectory\b", "轨迹"),
        (r"\bresults\b", "结果"),
        (r"\bevaluation\b", "评估"),
    )
    for pattern, replacement in phrase_map:
        translated = re.sub(pattern, replacement, translated, flags=re.IGNORECASE)
    translated = translated.replace("of SA-LIVO", "：SA-LIVO")
    translated = translated.replace("SA-LIVO across", "SA-LIVO 在")
    translated = re.sub(r"\s+", " ", translated).strip(" .。")
    translated = translated.replace(" ：", "：").replace("： ", "：")
    return translated


def _has_real_figure_caption(caption: str) -> bool:
    caption = _clean_figure_caption(caption)
    return not (
        caption.startswith("论文原图")
        or caption.startswith("论文 PDF")
        or caption.startswith("PDF 内嵌图片")
        or "未匹配到可靠图注" in caption
        or re.match(r"^pdf\s+page\b", caption, re.IGNORECASE)
    )


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
    if figure.source == "ai":
        score += 120.0
    elif figure.source == "method_group":
        score += 160.0
    elif figure.source == "intro_group":
        score += 100.0
    elif figure.source == "experiment_group":
        score += 60.0
    elif figure.source == "pdf_page":
        score -= 90.0
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


def _image_variants(image_mode: str) -> tuple[str, ...]:
    mode = (image_mode or "paper").strip().lower()
    if mode == "both":
        return ("paper", "ai")
    if mode in {"paper", "ai"}:
        return (mode,)
    raise ValueError(f"Unsupported DEEPDIVE_IMAGE_MODE: {image_mode}")


def _article_stem(variant: str, variants: tuple[str, ...]) -> str:
    if len(variants) == 1:
        return "article"
    return f"article-{variant}"


def _figures_for_variant(
    *,
    variant: str,
    paper: dict[str, Any],
    reading: PaperReading,
    source_figures: list[DeepDiveFigure],
    output_dir: Path,
    max_figures: int,
) -> tuple[list[DeepDiveFigure], DeepDiveFigure | None]:
    prepared_figures = _prepare_article_figures(source_figures, output_dir, max_figures)
    if variant == "ai":
        ai_cover = _generate_ai_cover_figure(paper, reading, output_dir)
        if ai_cover:
            figures = [ai_cover, *prepared_figures]
            return figures, ai_cover
        print("Gemini cover unavailable; AI version falls back to paper figures.", file=sys.stderr)

    cover = _select_cover_figure(prepared_figures)
    return prepared_figures, cover


def _prepare_article_figures(source_figures: list[DeepDiveFigure], output_dir: Path, max_figures: int) -> list[DeepDiveFigure]:
    usable_figures = [figure for figure in source_figures if _figure_file_is_usable(figure.path)]
    if not usable_figures:
        return []

    section_candidates: dict[str, list[DeepDiveFigure]] = {section: [] for section in FIGURE_SECTION_ORDER}
    for figure in usable_figures:
        section_candidates[_figure_section(figure)].append(figure)

    if not _env_bool("DEEPDIVE_EXPERIMENT_COMPOSITE", True):
        grouped: list[DeepDiveFigure] = []
        used_paths: set[Path] = set()
        for section in FIGURE_SECTION_ORDER:
            candidates = [figure for figure in section_candidates[section] if figure.path not in used_paths]
            reliable_candidates = [figure for figure in candidates if _has_real_figure_caption(figure.caption)]
            candidate = next(iter(reliable_candidates or candidates), None)
            if candidate:
                grouped.append(_as_group_figure(candidate, section))
                used_paths.add(candidate.path)
        return grouped or usable_figures[: max(max_figures, len(FIGURE_SECTION_ORDER))]

    grouped: list[DeepDiveFigure] = []
    used_paths: set[Path] = set()
    for section in FIGURE_SECTION_ORDER:
        candidates = [figure for figure in section_candidates[section] if figure.path not in used_paths]
        reliable_candidates = [figure for figure in candidates if _has_real_figure_caption(figure.caption)]
        if reliable_candidates:
            candidates = reliable_candidates
        if not candidates:
            continue
        group = _make_figure_group(candidates[: _figure_group_limit(section)], output_dir, section)
        if group:
            grouped.append(group)
            used_paths.update(figure.path for figure in candidates[: _figure_group_limit(section)])
    return grouped or usable_figures[: max(max_figures, len(FIGURE_SECTION_ORDER))]


def _figure_group_limit(section: str) -> int:
    return {"intro": 3, "method": 4, "experiment": 4}.get(section, 3)


def _make_figure_group(figures: list[DeepDiveFigure], output_dir: Path, section: str) -> DeepDiveFigure | None:
    images: list[tuple[DeepDiveFigure, Image.Image]] = []
    for figure in figures:
        try:
            with Image.open(figure.path) as image:
                trimmed = _trim_white(image.convert("RGB"))
                if _is_low_information_image(trimmed):
                    continue
                images.append((figure, trimmed.copy()))
        except OSError:
            continue
    if len(images) < 2:
        return _as_group_figure(images[0][0], section) if images else None

    columns = 1 if section in {"intro", "method"} else 2
    rows = (len(images) + columns - 1) // columns
    cell_width = 1080 if columns == 1 else 640
    cell_height = 520 if columns == 1 else 390
    pad = 18
    label_height = 28
    if columns == 1:
        fitted_images = [_fit_image(image, cell_width, 620) for _figure, image in images]
        canvas_height = pad + sum(image.height + label_height + pad for image in fitted_images)
        canvas = Image.new("RGB", (cell_width + 2 * pad, canvas_height), "white")
        y = pad
        for index, fitted in enumerate(fitted_images):
            x = pad + (cell_width - fitted.width) // 2
            canvas.paste(fitted, (x, y))
            _draw_basic_label(canvas, f"({chr(ord('a') + index)})", pad, y + fitted.height + 6)
            y += fitted.height + label_height + pad

        out = output_dir / f"{section}-group.jpg"
        canvas.save(out, format="JPEG", quality=92, optimize=True, progressive=True)
        used_figures = [figure for figure, _image in images]
        caption = _group_caption(section, used_figures)
        return DeepDiveFigure(out, caption, source=f"{section}_group", children=tuple(figure.caption for figure in used_figures))

    if columns == 2 and len(images) == 3:
        top_images = [_fit_image(image, cell_width, cell_height) for _figure, image in images[:2]]
        bottom_image = _fit_image(images[2][1], columns * cell_width + pad, 430)
        top_height = max(image.height for image in top_images)
        canvas_width = columns * cell_width + (columns + 1) * pad
        canvas_height = pad + top_height + label_height + pad + bottom_image.height + label_height + pad
        canvas = Image.new("RGB", (canvas_width, canvas_height), "white")
        for index, fitted in enumerate(top_images):
            x = pad + index * (cell_width + pad) + (cell_width - fitted.width) // 2
            y = pad + (top_height - fitted.height) // 2
            canvas.paste(fitted, (x, y))
            _draw_basic_label(canvas, f"({chr(ord('a') + index)})", pad + index * (cell_width + pad), pad + top_height + 6)
        bottom_y = pad + top_height + label_height + pad
        canvas.paste(bottom_image, ((canvas_width - bottom_image.width) // 2, bottom_y))
        _draw_basic_label(canvas, "(c)", pad, bottom_y + bottom_image.height + 6)

        out = output_dir / f"{section}-group.jpg"
        canvas.save(out, format="JPEG", quality=92, optimize=True, progressive=True)
        used_figures = [figure for figure, _image in images]
        caption = _group_caption(section, used_figures)
        return DeepDiveFigure(out, caption, source=f"{section}_group", children=tuple(figure.caption for figure in used_figures))

    canvas = Image.new("RGB", (columns * cell_width + (columns + 1) * pad, rows * (cell_height + label_height) + (rows + 1) * pad), "white")
    for index, (_figure, image) in enumerate(images):
        row = index // columns
        column = index % columns
        fitted = _fit_image(image, cell_width, cell_height)
        x = pad + column * (cell_width + pad) + (cell_width - fitted.width) // 2
        y = pad + row * (cell_height + label_height + pad)
        canvas.paste(fitted, (x, y))
        # A plain text label is enough to help readers map subfigures without changing the source image.
        label = f"({chr(ord('a') + index)})"
        label_x = pad + column * (cell_width + pad)
        label_y = y + cell_height + 6
        _draw_basic_label(canvas, label, label_x, label_y)

    out = output_dir / f"{section}-group.jpg"
    canvas.save(out, format="JPEG", quality=92, optimize=True, progressive=True)
    used_figures = [figure for figure, _image in images]
    caption = _group_caption(section, used_figures)
    return DeepDiveFigure(out, caption, source=f"{section}_group", children=tuple(figure.caption for figure in used_figures))


def _as_group_figure(figure: DeepDiveFigure, section: str) -> DeepDiveFigure:
    return DeepDiveFigure(figure.path, _group_caption(section, [figure]), source=f"{section}_group", children=(figure.caption,))


def _group_caption(section: str, figures: list[DeepDiveFigure]) -> str:
    translated = [_translate_figure_caption(figure.caption) for figure in figures if _has_real_figure_caption(figure.caption)]
    if translated:
        return "；".join(translated[:4])
    fallback = {
        "intro": "论文背景、场景或问题设置",
        "method": "论文方法流程与系统结构",
        "experiment": "论文实验设置、结果与评估",
    }
    return fallback.get(section, "论文图组")


def _fit_image(image: Image.Image, max_width: int, max_height: int) -> Image.Image:
    copy = image.copy()
    copy.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    return copy


def _draw_basic_label(image: Image.Image, label: str, x: int, y: int) -> None:
    try:
        from PIL import ImageDraw

        draw = ImageDraw.Draw(image)
        draw.text((x, y), label, fill=(48, 68, 76))
    except Exception:
        return


def _figure_section(figure: DeepDiveFigure) -> str:
    if figure.source == "ai":
        return "intro"
    section = FIGURE_SECTION_SOURCES.get(figure.source)
    if section:
        return section
    if figure.source == "pdf_page":
        return "intro"

    caption = figure.caption.lower()
    if _is_strong_experiment_caption(caption):
        return "experiment"
    if _is_method_caption(caption):
        return "method"
    if _is_experiment_figure(figure):
        return "experiment"
    if figure.source == "paper_embedded":
        return "experiment"
    if any(
        term in caption
        for term in (
            "architecture",
            "framework",
            "pipeline",
            "workflow",
            "flow",
            "block diagram",
            "method",
            "network",
            "algorithm",
            "model",
            "proposed",
            "registration",
            "hash map",
            "voxel",
            "kalman",
            "filter",
            "sensor fusion",
            "架构",
            "框架",
            "流程",
            "结构",
            "方法",
            "算法",
        )
    ):
        return "method"
    if any(
        term in caption
        for term in (
            "introduction",
            "background",
            "motivation",
            "problem",
            "scenario",
            "attack setup",
            "data collection",
            "sensor platform",
            "infrastructure",
            "hardware setup",
            "field test setup",
            "overview",
            "system overview",
            "场景",
            "背景",
            "问题",
            "平台",
            "设置",
        )
    ):
        return "intro"
    return "method"


def _is_method_caption(caption: str) -> bool:
    return any(
        term in caption
        for term in (
            "architecture",
            "framework",
            "pipeline",
            "workflow",
            "flow",
            "system overview",
            "block diagram",
            "network",
            "algorithm",
            "registration",
            "hash map",
            "voxel",
            "kalman",
            "filter",
            "sensor fusion",
            "information fusion",
            "subspace-aware",
            "soft gate",
            "gate",
            "eigen",
            "jacobian",
            "residual",
            "factor graph",
            "optimization",
            "forward mapping",
            "state update",
            "covariance",
            "reprojection",
            "geometric illustration",
            "架构",
            "框架",
            "流程",
            "结构",
            "方法",
            "算法",
            "融合",
            "优化",
        )
    )


def _is_experiment_figure(figure: DeepDiveFigure) -> bool:
    if figure.source in {"ai", "pdf_page"}:
        return False
    caption = figure.caption.lower()
    if _is_method_caption(caption) and not _is_strong_experiment_caption(caption):
        return False
    return _is_experiment_caption(caption)


def _is_strong_experiment_caption(caption: str) -> bool:
    return any(
        _caption_contains_term(caption, term)
        for term in (
            "experiment",
            "experimental setup",
            "evaluation setup",
            "evaluation",
            "result",
            "trajectory",
            "trajectories",
            "estimated",
            "estimation",
            "accuracy",
            "error",
            "failure",
            "recovery",
            "benchmark",
            "performance",
            "dataset",
            "point cloud",
            "maps",
            "rmse",
            "ape",
            "comparison",
            "qualitative",
            "quantitative",
            "kitti",
            "hilti",
            "runtime",
            "memory",
            "computation",
            "computing",
            "time budget",
            "wall-time",
            "latency",
            "speed",
        )
    )


def _is_experiment_caption(caption: str) -> bool:
    weak_terms = ("mapping", "odometry", "localization", "pose")
    return _is_strong_experiment_caption(caption) or any(_caption_contains_term(caption, term) for term in weak_terms)


def _caption_contains_term(caption: str, term: str) -> bool:
    if " " in term or "-" in term:
        return term in caption
    if len(term) <= 5:
        return re.search(rf"\b{re.escape(term)}\b", caption) is not None
    return term in caption


def _generate_ai_cover_figure(paper: dict[str, Any], reading: PaperReading, output_dir: Path) -> DeepDiveFigure | None:
    api_key = _first_env("GEMINI_API_KEY", "GOOGLE_API_KEY")
    if not api_key:
        print("Gemini cover skipped: set GEMINI_API_KEY in .env to enable AI image mode.", file=sys.stderr)
        return None
    try:
        image_bytes = _request_gemini_cover_image(api_key, _gemini_cover_prompt(paper, reading))
        output = output_dir / "ai-cover.jpg"
        _save_cover_image(image_bytes, output)
        return DeepDiveFigure(output, _ai_cover_caption(paper, reading), source="ai")
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
        print(f"Gemini cover skipped: {exc}", file=sys.stderr)
        return None


def _request_gemini_cover_image(api_key: str, prompt: str) -> bytes:
    endpoint = os.getenv("GEMINI_IMAGE_ENDPOINT", "https://generativelanguage.googleapis.com/v1beta/interactions")
    model = os.getenv("GEMINI_IMAGE_MODEL", os.getenv("DEEPDIVE_AI_COVER_MODEL", "gemini-3.1-flash-image"))
    body = {
        "model": model,
        "input": [{"type": "text", "text": prompt}],
        "response_format": {
            "type": "image",
            "mime_type": "image/jpeg",
            "aspect_ratio": "16:9",
            "image_size": os.getenv("GEMINI_IMAGE_SIZE", "1K"),
        },
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=float(os.getenv("GEMINI_IMAGE_TIMEOUT_SECONDS", "120"))) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Gemini API HTTP {exc.code}: {detail}") from exc
    image_data = _extract_base64_image(payload)
    if not image_data:
        raise RuntimeError("Gemini API response did not include image data")
    return base64.b64decode(image_data)


def _extract_base64_image(payload: Any) -> str:
    if isinstance(payload, dict):
        output_image = payload.get("output_image") or payload.get("outputImage")
        if isinstance(output_image, dict):
            data = output_image.get("data") or output_image.get("image_data") or output_image.get("imageData")
            if isinstance(data, str):
                return data
        inline_data = payload.get("inlineData") or payload.get("inline_data")
        if isinstance(inline_data, dict):
            data = inline_data.get("data")
            mime = inline_data.get("mimeType") or inline_data.get("mime_type") or ""
            if isinstance(data, str) and str(mime).startswith("image/"):
                return data
        data = payload.get("data")
        mime = payload.get("mimeType") or payload.get("mime_type") or ""
        if isinstance(data, str) and str(mime).startswith("image/"):
            return data
        for value in payload.values():
            found = _extract_base64_image(value)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _extract_base64_image(value)
            if found:
                return found
    return ""


def _save_cover_image(image_bytes: bytes, output: Path) -> None:
    with Image.open(BytesIO(image_bytes)) as image:
        cover = image.convert("RGB")
        cover = _crop_to_ratio(cover, 16 / 9)
        cover = cover.resize((1280, 720), Image.Resampling.LANCZOS)
        cover.save(output, format="JPEG", quality=92, optimize=True, progressive=True)


def _crop_to_ratio(image: Image.Image, ratio: float) -> Image.Image:
    width, height = image.size
    current = width / max(height, 1)
    if abs(current - ratio) < 0.01:
        return image
    if current > ratio:
        new_width = int(height * ratio)
        left = max((width - new_width) // 2, 0)
        return image.crop((left, 0, left + new_width, height))
    new_height = int(width / ratio)
    top = max((height - new_height) // 2, 0)
    return image.crop((0, top, width, top + new_height))


def _gemini_cover_prompt(paper: dict[str, Any], reading: PaperReading) -> str:
    profile = _domain_profile(paper, reading)
    terms = ", ".join(_paper_terms(paper, reading)[:8])
    return (
        "Create a clean 16:9 editorial concept illustration for a Chinese technical paper-reading article. "
        "Do not include readable text, captions, logos, watermarks, UI panels, equations, or fake paper pages. "
        "Use a modern scientific style with clear visual hierarchy and realistic technical elements. "
        f"Paper title: {_display_title(paper)}. "
        f"Topic keywords: {terms}. "
        f"Scene: {profile['scene']}. Problem: {profile['problem']}. "
        f"Method idea: {profile['method']}. Evidence theme: {profile['experiment']}. "
        "Show the idea as a data-flow story: sensors or signals on the left, processing/fusion/detection in the middle, "
        "and localization, mapping, timing, or warning output on the right. "
        "Prefer teal, white, graphite, and subtle satellite/robotics/navigation cues. "
        "The image should feel like a professional magazine cover, not a screenshot."
    )


def _ai_cover_caption(paper: dict[str, Any], reading: PaperReading) -> str:
    profile = _domain_profile(paper, reading)
    return f"{profile['problem']}与{profile['method']}的概念示意"


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return ""


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", ""}


def _figure_pool_size(max_figures: int) -> int:
    try:
        configured = int(os.getenv("DEEPDIVE_FIGURE_POOL", "12"))
    except ValueError:
        configured = 12
    return max(max_figures, configured)


def _image_runtime_mode(variant: str, figures: list[DeepDiveFigure]) -> str:
    has_groups = any(figure.source in FIGURE_SECTION_SOURCES for figure in figures)
    if variant == "ai":
        if any(figure.source == "ai" for figure in figures):
            return "AI 概念图 + 论文分章节图组" if has_groups else "AI 概念图 + 论文图"
        if has_groups:
            return "AI 不可用，已回退论文分章节图组"
        return "AI 不可用，已回退论文图"
    if has_groups:
        return "论文分章节图组"
    return "论文原图"


def _split_keywords(value: str | tuple[str, ...] | None) -> tuple[str, ...]:
    if isinstance(value, tuple):
        return tuple(item.strip() for item in value if item.strip())
    if not value:
        return _default_figure_keywords()
    parts = re.split(r"[,，;；\n]+", value)
    keywords = tuple(part.strip() for part in parts if part.strip())
    return keywords or _default_figure_keywords()


def _generate_text_polish(paper: dict[str, Any], reading: PaperReading, figures: list[DeepDiveFigure]) -> TextPolishResult:
    mode = os.getenv("DEEPDIVE_TEXT_POLISH_MODE", "api").strip().lower()
    if mode in {"0", "false", "no", "off", "fallback", "traditional"}:
        return TextPolishResult("fallback", "text polish disabled")

    raw_texts = _text_polish_inputs(paper, reading, figures)
    reasons: list[str] = []
    for provider in _text_polish_provider_order(mode):
        try:
            result = _run_text_polish_provider(provider, paper, raw_texts)
        except (OSError, ValueError, RuntimeError, urllib.error.URLError, json.JSONDecodeError) as exc:
            reason = _short_error(str(exc))
            reasons.append(f"{_text_polish_provider_name(provider)}: {reason}")
            print(f"{_text_polish_provider_name(provider)} text polish skipped: {reason}", file=sys.stderr)
            continue
        cleaned = _clean_text_polish_payload(result, raw_texts)
        if cleaned:
            return TextPolishResult(provider, _text_polish_provider_reason(provider), cleaned)
        reason = f"{_text_polish_provider_name(provider)} returned no usable text"
        reasons.append(reason)
        print(f"{reason}; trying next provider.", file=sys.stderr)

    return TextPolishResult("fallback", "; ".join(reasons) or "no text polish provider configured")


def _text_polish_provider_order(mode: str) -> tuple[str, ...]:
    if mode in {"gemini", "google"}:
        return ("gemini",)
    if mode in {"siliconflow", "silicon", "sf"}:
        return ("siliconflow",)
    if mode in {"ollama", "local"}:
        return ("ollama",)
    configured = os.getenv("DEEPDIVE_TEXT_POLISH_PROVIDERS", "gemini,siliconflow,ollama")
    providers = []
    for item in re.split(r"[,，;；\s]+", configured):
        provider = item.strip().lower()
        if provider in {"google"}:
            provider = "gemini"
        if provider in {"silicon", "sf"}:
            provider = "siliconflow"
        if provider in {"local"}:
            provider = "ollama"
        if provider in {"gemini", "siliconflow", "ollama"} and provider not in providers:
            providers.append(provider)
    return tuple(providers or ["gemini", "siliconflow", "ollama"])


def _run_text_polish_provider(provider: str, paper: dict[str, Any], raw_texts: dict[str, str]) -> dict[str, str]:
    if provider == "gemini":
        api_key = _first_env("GEMINI_API_KEY", "GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("missing GEMINI_API_KEY")
        return _request_gemini_text_polish(api_key, paper, raw_texts)
    if provider == "siliconflow":
        api_key = _first_env("SILICONFLOW_API_KEY", "SILICONFLOW_TEXT_API_KEY")
        if not api_key:
            raise RuntimeError("missing SILICONFLOW_API_KEY")
        return _request_siliconflow_text_polish(api_key, paper, raw_texts)
    if provider == "ollama":
        return _request_ollama_text_polish(paper, raw_texts)
    raise RuntimeError(f"unsupported text polish provider: {provider}")


def _text_polish_provider_name(provider: str) -> str:
    if provider == "siliconflow":
        return "SiliconFlow"
    if provider == "gemini":
        return "Gemini"
    if provider == "ollama":
        return "Ollama"
    return provider


def _text_polish_provider_reason(provider: str) -> str:
    if provider == "siliconflow":
        return f"SiliconFlow text model: {_siliconflow_text_model()}"
    if provider == "gemini":
        return f"Gemini text model: {_gemini_text_model()}"
    if provider == "ollama":
        return f"Ollama local model: {_ollama_text_model()}"
    return f"text model provider: {provider}"


def _clean_text_polish_payload(polished: dict[str, str], raw_texts: dict[str, str]) -> dict[str, str]:
    return {
        key: _clean_polished_text(value)
        for key, value in polished.items()
        if key in raw_texts and isinstance(value, str) and _clean_polished_text(value)
    }


def _text_polish_inputs(paper: dict[str, Any], reading: PaperReading, figures: list[DeepDiveFigure]) -> dict[str, str]:
    texts = {
        "one_sentence": _one_sentence(paper, reading),
        "story_intro": _story_intro(paper, reading),
    }
    for role, chapter in zip(PAPER_CHAPTER_ROLES, _chapter_walkthrough(paper, reading)):
        _title, body, points = chapter
        texts[_chapter_text_key(role, "body")] = body
        for point_index, point in enumerate(points, start=1):
            texts[_chapter_text_key(role, f"point:{point_index}")] = point
    for index, figure in enumerate(figures, start=1):
        texts[f"figure:{figure.path.name}"] = _figure_reading(paper, reading, figure, index)
    return texts


def _request_gemini_text_polish(api_key: str, paper: dict[str, Any], texts: dict[str, str]) -> dict[str, str]:
    model = _gemini_text_model()
    endpoint = os.getenv("GEMINI_TEXT_ENDPOINT") or (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + urllib.parse.quote(model, safe="")
        + ":generateContent?key="
        + urllib.parse.quote(api_key, safe="")
    )
    prompt = _text_polish_prompt(paper, texts)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": float(os.getenv("GEMINI_TEXT_TEMPERATURE", "0.35")),
            "responseMimeType": "application/json",
        },
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=float(os.getenv("GEMINI_TEXT_TIMEOUT_SECONDS", "60"))) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Gemini text API HTTP {exc.code}: {detail}") from exc
    text = _extract_gemini_text(payload)
    if not text:
        raise RuntimeError("Gemini text API response did not include text")
    data = json.loads(_extract_json_object(text))
    if not isinstance(data, dict):
        raise RuntimeError("Gemini text polish response was not a JSON object")
    return {str(key): str(value) for key, value in data.items()}


def _request_siliconflow_text_polish(api_key: str, paper: dict[str, Any], texts: dict[str, str]) -> dict[str, str]:
    endpoint = os.getenv("SILICONFLOW_TEXT_ENDPOINT", "https://api.siliconflow.cn/v1/chat/completions")
    aliases = {f"k{index:03d}": key for index, key in enumerate(texts, start=1)}
    alias_texts = {alias: texts[key] for alias, key in aliases.items()}
    body: dict[str, Any] = {
        "model": _siliconflow_text_model(),
        "messages": [
            {
                "role": "system",
                "content": "你是中文科技公众号编辑，只返回合法 JSON 对象，不输出思考过程。",
            },
            {
                "role": "user",
                "content": _text_polish_prompt(paper, alias_texts),
            },
        ],
        "temperature": float(os.getenv("SILICONFLOW_TEXT_TEMPERATURE", os.getenv("GEMINI_TEXT_TEMPERATURE", "0.35"))),
        "max_tokens": int(os.getenv("SILICONFLOW_TEXT_MAX_TOKENS", "8192")),
    }
    if os.getenv("SILICONFLOW_TEXT_RESPONSE_FORMAT", "0").lower() in {"1", "true", "yes", "on"}:
        body["response_format"] = {"type": "json_object"}
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=float(os.getenv("SILICONFLOW_TEXT_TIMEOUT_SECONDS", "180"))) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"SiliconFlow text API HTTP {exc.code}: {detail}") from exc
    text = _extract_openai_message_text(payload)
    if not text:
        raise RuntimeError("SiliconFlow text API response did not include message content")
    data = json.loads(_extract_json_object(text))
    if not isinstance(data, dict):
        raise RuntimeError("SiliconFlow text polish response was not a JSON object")
    return {
        aliases.get(str(key), str(key)): str(value)
        for key, value in data.items()
    }


def _request_ollama_text_polish(paper: dict[str, Any], texts: dict[str, str]) -> dict[str, str]:
    batch_size = _ollama_text_batch_size()
    if len(texts) > batch_size:
        polished: dict[str, str] = {}
        items = list(texts.items())
        for offset in range(0, len(items), batch_size):
            batch = dict(items[offset : offset + batch_size])
            polished.update(_request_ollama_text_polish_batch(paper, batch))
        return polished
    return _request_ollama_text_polish_batch(paper, texts)


def _request_ollama_text_polish_batch(paper: dict[str, Any], texts: dict[str, str]) -> dict[str, str]:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    endpoint = os.getenv("OLLAMA_TEXT_ENDPOINT", f"{base_url}/api/chat")
    aliases = {f"k{index:03d}": key for index, key in enumerate(texts, start=1)}
    alias_texts = {alias: texts[key] for alias, key in aliases.items()}
    body: dict[str, Any] = {
        "model": _ollama_text_model(),
        "messages": [
            {
                "role": "system",
                "content": "你是中文科技公众号编辑，只返回合法 JSON 对象，不输出思考过程。",
            },
            {
                "role": "user",
                "content": _text_polish_prompt(paper, alias_texts),
            },
        ],
        "stream": False,
        "options": {
            "temperature": float(os.getenv("OLLAMA_TEXT_TEMPERATURE", "0.2")),
            "num_predict": _ollama_text_num_predict(),
        },
    }
    keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "").strip()
    if keep_alive:
        body["keep_alive"] = keep_alive
    if os.getenv("OLLAMA_TEXT_FORMAT_JSON", "1").lower() in {"1", "true", "yes", "on"}:
        body["format"] = "json"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=float(os.getenv("OLLAMA_TEXT_TIMEOUT_SECONDS", "240"))) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Ollama text API HTTP {exc.code}: {detail}") from exc
    text = _extract_ollama_message_text(payload) or _extract_openai_message_text(payload)
    if not text:
        raise RuntimeError("Ollama text API response did not include message content")
    data = json.loads(_extract_json_object(text))
    if not isinstance(data, dict):
        raise RuntimeError("Ollama text polish response was not a JSON object")
    return {
        aliases.get(str(key), str(key)): str(value)
        for key, value in data.items()
    }


def _gemini_text_model() -> str:
    return os.getenv("GEMINI_TEXT_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"


def _siliconflow_text_model() -> str:
    return os.getenv("SILICONFLOW_TEXT_MODEL", "deepseek-ai/DeepSeek-V3").strip() or "deepseek-ai/DeepSeek-V3"


def _ollama_text_model() -> str:
    return os.getenv("OLLAMA_TEXT_MODEL", "qwen3:8b").strip() or "qwen3:8b"


def _ollama_text_batch_size() -> int:
    try:
        value = int(os.getenv("OLLAMA_TEXT_BATCH_SIZE", "4"))
    except ValueError:
        return 4
    return min(max(value, 1), 20)


def _ollama_text_num_predict() -> int:
    try:
        value = int(os.getenv("OLLAMA_TEXT_NUM_PREDICT", "1024"))
    except ValueError:
        return 1024
    return max(value, 128)


def _text_polish_prompt(paper: dict[str, Any], texts: dict[str, str]) -> str:
    return (
        "你是中文科技公众号编辑。请润色下面这组论文解读文案，只提升自然度、顺滑度和可读性，"
        "不要新增事实，不要删除关键风险机制、方法机制、实验机制，不要加入“AI”“自动生成”“邮件指定”等表述。"
        "避免使用“通常”“一般”“线索落在”“数字线索”“短句线索”“原文强调的是”“可以重点看”这类模板化句式。"
        "chapter:*:point:* 的文本如果开头带“标签：”，必须保留这个标签和冒号，只润色冒号后面的解释。"
        "如果原文里出现疑似 PDF/OCR 残片、孤立数字或不完整短语，不要硬解释，改成更自然的概括。"
        "遇到图组说明时保留“这一组图”或“这一组”的表达，不要改成“这张图”。"
        "保持每个 key 对应一段中文文本，保留英文专有名词和单位。只返回 JSON 对象，键名必须与输入一致。\n\n"
        f"论文题目：{_display_title(paper)}\n"
        "待润色 JSON：\n"
        + json.dumps(texts, ensure_ascii=False, indent=2)
    )


def _extract_gemini_text(payload: Any) -> str:
    if isinstance(payload, dict):
        candidates = payload.get("candidates")
        if isinstance(candidates, list):
            for candidate in candidates:
                text = _extract_gemini_text(candidate)
                if text:
                    return text
        parts = payload.get("parts")
        if isinstance(parts, list):
            chunks = [part.get("text", "") for part in parts if isinstance(part, dict)]
            return "\n".join(chunk for chunk in chunks if chunk).strip()
        content = payload.get("content")
        if isinstance(content, dict):
            return _extract_gemini_text(content)
        text = payload.get("text")
        if isinstance(text, str):
            return text.strip()
    return ""


def _extract_openai_message_text(payload: Any) -> str:
    if isinstance(payload, dict):
        choices = payload.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str) and content.strip():
                        return content.strip()
                text = choice.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
        output = payload.get("output")
        if isinstance(output, str):
            return output.strip()
    return ""


def _extract_ollama_message_text(payload: Any) -> str:
    if isinstance(payload, dict):
        message = payload.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
        response = payload.get("response")
        if isinstance(response, str):
            return response.strip()
    return ""


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start : end + 1]
    return stripped


def _clean_polished_text(text: str) -> str:
    text = _clean_text(text)
    text = text.strip("` ")
    text = _remove_template_phrases(text)
    limit = 900
    if len(text) > limit:
        sentence_end = max(text.rfind("。", 0, limit), text.rfind("！", 0, limit), text.rfind("？", 0, limit))
        if sentence_end > int(limit * 0.55):
            return text[: sentence_end + 1]
        text = text[:limit].rstrip("，,；;。 ") + "。"
    return text


def _remove_template_phrases(text: str) -> str:
    replacements = (
        ("通常置于", "放在"),
        ("通常放在", "放在"),
        ("通常出现在", "出现在"),
        ("通常位于", "位于"),
        ("通常用于", "用于"),
        ("通常在", "在"),
        ("一般来说，", ""),
        ("一般而言，", ""),
        ("一般", ""),
        ("通常", ""),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _polished_text(polish: TextPolishResult | None, key: str, fallback: str) -> str:
    if polish and polish.texts:
        value = polish.texts.get(key)
        if value:
            return value
    return fallback


def _short_error(text: str) -> str:
    text = _clean_text(text)
    if len(text) <= 160:
        return text
    return text[:157].rstrip() + "..."


def _one_sentence(paper: dict[str, Any], reading: PaperReading | None = None) -> str:
    reading = reading or PaperReading("", "", "", "", "", ())
    profile = _domain_profile(paper, reading)
    facts = _paper_facts(paper, reading)
    claim = facts.get("method") or facts.get("finding") or facts.get("problem")
    evidence = _evidence_summary(claim or "")
    tail = f"；{evidence}" if evidence else ""
    if claim:
        return (
            f"这篇论文要解决的是{profile['actor']}在{profile['scene']}里遇到的“{profile['problem']}”，"
            f"读法上可以盯住{profile['method']}如何从输入走到可落地的{profile['engineering']}{tail}。"
        )
    return f"这篇论文值得按“{profile['problem']} -> {profile['method']} -> {profile['experiment']}”这条线读。"


def _story_intro(paper: dict[str, Any], reading: PaperReading) -> str:
    profile = _domain_profile(paper, reading)
    title = _display_title(paper)
    terms = _paper_terms(paper, reading)[:3]
    term_text = f"题目里的 {_join_readable(terms)} 已经把范围圈出来。" if terms else ""
    return (
        f"读《{title}》时，可以先把它当成一个工程故事：系统在{profile['scene']}里工作，"
        f"但{profile['problem']}，原本稳定的输入链路就会被打乱。{term_text}"
        f"接着看作者怎样用{profile['method']}把问题拆开，再看实验是否真的覆盖{profile['experiment']}。"
        f"最后回到自己的平台，判断它能不能接进{profile['engineering']}。"
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
    evidence = _evidence_summary(claim)
    evidence_sentence = f"{evidence}。" if evidence else ""
    if role == "problem":
        return (
            f"开篇先回答为什么这个问题值得做：{profile['actor']}原本依赖稳定输入工作，"
            f"但现场会出现这样的麻烦：{profile['problem']}。{evidence_sentence}"
            "读这一段时，不必急着记术语，先看清作者认为“危险”到底发生在哪个环节。"
        )
    if role == "method":
        return (
            f"方法部分可以当作一条处理链来看：输入是什么，{profile['method']}怎样组织信息，"
            f"最后又怎样服务于{profile['engineering']}。{evidence_sentence}"
            "这样读会比逐个背模块名轻松，也更容易看出作者真正改动了哪里。"
        )
    if role == "experiment":
        return (
            f"实验部分重点看证据链是否完整：数据从哪里来，场景够不够真实，指标是否能说明问题。"
            f"这篇主要用{profile['experiment']}验证。{evidence_sentence}"
            "如果图表里能同时看到成功样例和困难样例，结论就更有参考价值。"
        )
    return (
        f"最后再看边界：作者证明了什么，哪些条件下成立，换到自己的平台是否还需要重做标定或实验。"
        f"对工程读者来说，关键是它能否接到{profile['engineering']}。{evidence_sentence}"
    )


def _source_clues(paper: dict[str, Any], reading: PaperReading) -> list[str]:
    profile = _domain_profile(paper, reading)
    facts = _paper_facts(paper, reading)
    terms = _paper_terms(paper, reading)
    clues = [
        f"题目里最值得先圈出的词是：{', '.join(terms[:8]) or _display_title(paper)}。它们把文章带到{profile['scene']}，也暗示后面要解决{profile['problem']}。",
        f"摘要先交代问题：{_claim_to_plain_chinese(facts.get('problem', ''), profile, 'problem')}。这决定了文章的重点不是堆结果，而是解释问题为什么会发生。",
        f"接着看做法：{_claim_to_plain_chinese(facts.get('method', ''), profile, 'method')}。方法部分优先找清楚输入、假设、核心运算和输出。",
    ]
    if reading.captions:
        caption_terms = _paper_terms_from_text(" ".join(reading.captions))[:5]
        if caption_terms:
            clues.append(f"图注里反复出现 {', '.join(caption_terms)}，这些词多半对应系统流程、实验设置或结果展示，读图时可以先从这里入手。")
    quality = paper.get("quality_signals") or {}
    if paper.get("code_url") or quality.get("code_signal"):
        clues.append("这篇有代码或复现信息，读完方法后可以直接检查代码是否覆盖数据预处理、训练/检测和评估脚本。")
    elif quality.get("dataset_signal"):
        clues.append("这篇有数据集或 benchmark 信息，实验部分要重点看数据来源是否贴近真实部署场景。")
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
    if first_term.lower() in {
        "robust",
        "odometry",
        "localization",
        "mapping",
        "navigation",
        "fusion",
        "dataset",
        "benchmark",
    }:
        first_term = profile["actor"]
    return [
        f"如果把 {first_term} 换到自己的机器人或车辆平台，最先需要重新标定的是输入数据、阈值，还是传感器外参？",
        f"论文里的证据是否覆盖了{profile['scene']}里最容易失败的场景，还是只证明了一个受控设置？",
        f"这套做法接入{profile['engineering']}时，应该输出连续可信度、离散告警，还是直接改变优化权重？",
    ]


def _figure_reading(paper: dict[str, Any], reading: PaperReading, figure: DeepDiveFigure, index: int) -> str:
    profile = _domain_profile(paper, reading)
    caption = figure.caption
    lowered = caption.lower()
    translated_caption = _translate_figure_caption(caption)
    translation = f"原文图注可以译为：“{translated_caption}”。" if _has_real_figure_caption(caption) and translated_caption else ""
    if figure.source == "ai":
        return (
            f"这张概念图是辅助示意，用来把论文里的{profile['problem']}和{profile['method']}放到同一张画面里。"
            "它不替代论文原图，只负责让读者先有一个直观印象，再回到后面的原图和实验细节。"
        )
    if figure.source == "pdf_page":
        return (
            "这是一页论文截图，适合作为全文入口。它的价值不是展示某个具体实验图，"
            f"而是帮读者先看到论文如何引出{profile['problem']}，再进入方法和实验部分。"
        )
    section = FIGURE_SECTION_SOURCES.get(figure.source)
    if section:
        translated = [_translate_figure_caption(caption) for caption in figure.children if _has_real_figure_caption(caption)]
        prefix = "原图注可译为"
        if translated:
            joined = "；".join(translated[:4])
            if section == "intro":
                return (
                    f"{prefix}：“{joined}”。"
                    f"这一组放在 Introduction 后面，先交代论文面对的场景、平台或风险来源，"
                    f"让读者知道{profile['problem']}不是抽象概念，而是会在真实输入链路里出现的问题。"
                )
            if section == "method":
                return (
                    f"{prefix}：“{joined}”。"
                    "这一组放在 Method 后面，重点看输入、处理模块和输出之间怎样连接。"
                    f"读到这里，可以把它当成{profile['method']}的路线图，再回到正文看每个模块为什么存在。"
                )
            return (
                f"{prefix}：“{joined}”。"
                "这一组放在 Experiments 后面，适合把场景、指标和结果放在一起看："
                f"它要回答的不是单张图好不好看，而是这些证据能否支撑{profile['experiment']}。"
            )
        if section == "intro":
            return f"这一组图放在 Introduction 后面，用来交代论文的研究场景和问题来源，帮助读者先理解{profile['problem']}。"
        if section == "method":
            return f"这一组图放在 Method 后面，用来说明{profile['method']}怎样从输入走到输出。"
        return (
            "这一组图放在 Experiments 后面，重点看数据、指标、场景和结果是否互相对得上，"
            f"以及它们能否支撑{profile['experiment']}。"
        )
    if any(term in lowered for term in ("setup", "framework", "architecture", "system", "overview", "pipeline", "workflow", "flow")):
        return (
            f"{translation}它展示的是论文的整体组织方式：哪些传感器或观测先进来，"
            "中间经过哪些估计、融合或更新模块，最后形成状态、地图或告警结果。"
        )
    if any(term in lowered for term in ("experiment", "evaluation", "result", "performance", "benchmark", "table")):
        return (
            f"{translation}这类结果图主要回答“实验是否站得住”：场景是否足够多，"
            "指标是否能支撑作者的结论，以及失败或退化场景有没有被清楚展示。"
        )
    if any(term in lowered for term in ("map", "mapping", "trajectory", "odometry", "localization", "pose")):
        return (
            f"{translation}它展示的是定位、里程计或建图效果。读这类图时，重点看轨迹是否连续、"
            "地图是否有明显重影，以及不同场景下结果是否保持稳定。"
        )
    if any(term in lowered for term in ("gnss", "gps", "spoof", "jamming", "interference", "timing", "signal")):
        return (
            f"{translation}它讲的是信号、时间或接收机状态之间的关系。把异常输入、接收机响应和最终输出连起来，"
            "就能看出作者如何把风险变成可观测、可评估的问题。"
        )
    if index == 1:
        return (
            f"{translation}这张图先帮读者建立整体印象：论文讨论的对象是什么，"
            "主要模块在哪里，最后希望解决什么工程问题。"
        )
    if not translation:
        return "这张图没有解析到完整原文图注，可以把它当作正文细节的补充：要么解释某个模块，要么展示一个实验现象，读的时候和相邻段落一起看即可。"
    return f"{translation}这张图更像是对正文细节的补充：要么解释某个模块，要么补充实验现象，读的时候和相邻段落一起看即可。"


def _domain_profile(paper: dict[str, Any], reading: PaperReading) -> dict[str, str]:
    text = _combined_text(paper, reading).lower()
    terms = set(str(term).lower() for term in paper.get("matched_terms", []))
    gnss_security = terms & {"spoofing", "jamming", "interference", "integrity", "pnt"} or any(
        token in text for token in ("spoof", "jamming", "interference", "pnt", "timing protection", "protection level", "osnma")
    )
    slam_or_robotics = any(
        token in text
        for token in (
            "slam",
            "odometry",
            "mapping",
            "lidar",
            "imu",
            "visual",
            "camera",
            "3dgs",
            "gaussian",
            "livo",
            "lio",
            "vio",
        )
    )
    if gnss_security and not slam_or_robotics:
        return {
            "actor": "GNSS/PNT 接收机以及依赖它的车辆、机器人或授时系统",
            "scene": "开放环境里的定位、导航和授时链路",
            "problem": "外部信号被伪造、压制或缓慢拉偏时，系统仍可能输出看似可信的位置或时间",
            "method": "接收机观测、攻击构造、检测统计量、保护级或轻量模型",
            "experiment": "真实设备、回放信号、公开攻击数据、误报漏报、时间误差或部署算力",
            "engineering": "GNSS 可信度评估、融合定位降权、告警策略和完整性监测",
        }
    if slam_or_robotics and "uav" in text and "gps-denied" in text:
        return {
            "actor": "GPS-denied 无人机定位系统",
            "scene": "没有稳定 GNSS 的无人机巡检、测绘和跨时段重定位场景",
            "problem": "GNSS 不可用、跨时段外观变化和视角差异会削弱地图匹配与位姿约束",
            "method": "3D LiDAR、相机观测、跨 session 地图匹配、特征关联和位姿估计",
            "experiment": "跨时段定位误差、匹配成功率、地图变化、飞行平台验证和失败样例",
            "engineering": "无人机重定位、离线地图复用、传感器同步和无 GNSS 飞行安全",
        }
    if slam_or_robotics and any(token in text for token in ("lidar-inertial-visual", "visual-inertial", "lidar-inertial", "livo")):
        return {
            "actor": "LiDAR-IMU-相机融合里程计与建图系统",
            "scene": "室内外移动机器人、自动驾驶和大尺度三维建图场景",
            "problem": "遮挡、弱纹理、几何退化或高速运动会让单一观测源失去稳定约束",
            "method": "LiDAR、IMU 与相机紧耦合融合、退化方向识别、状态更新和体素地图维护",
            "experiment": "轨迹误差、地图质量、退化场景、实时频率和公开数据集对比",
            "engineering": "LIVO 前端/后端、地图更新、退化处理和车载/机器人实时部署",
        }
    if slam_or_robotics:
        return {
            "actor": "移动机器人定位与建图系统",
            "scene": "室内外移动机器人、自动驾驶或大尺度建图场景",
            "problem": "遮挡、稀疏几何、动态物体或长距离运行会削弱单一传感器约束",
            "method": "传感器融合、几何约束、地图表达、回环检测或学习式前端",
            "experiment": "轨迹误差、地图一致性、传感器退化、跨数据集对比和实时性",
            "engineering": "SLAM 前端/后端、地图维护、传感器降级和部署算力预算",
        }
    if gnss_security or any(
        token in text for token in ("gnss", "gps")
    ):
        return {
            "actor": "GNSS/PNT 接收机以及依赖它的车辆、机器人或授时系统",
            "scene": "开放环境里的定位、导航和授时链路",
            "problem": "外部信号被伪造、压制或缓慢拉偏时，系统仍可能输出看似可信的位置或时间",
            "method": "接收机观测、攻击构造、检测统计量、保护级或轻量模型",
            "experiment": "真实设备、回放信号、公开攻击数据、误报漏报、时间误差或部署算力",
            "engineering": "GNSS 可信度评估、融合定位降权、告警策略和完整性监测",
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
    if not evidence:
        return _fallback_point(profile, role, label, claim)
    if role == "problem":
        if label == "场景压力":
            return f"{evidence}，说明论文不是孤立讨论算法，而是把问题放回{profile['scene']}里看"
        if label == "失效来源":
            return f"{evidence}，危险点在于输入被污染后，{profile['actor']}仍可能给出像正常一样的输出"
        if label == "作者抓住的变量":
            return f"{evidence}，这就是后文要反复跟踪的观测量、攻击参数或系统状态"
        return f"{evidence}，影响会从单个观测扩散到{profile['engineering']}"
    if role == "method":
        if label == "输入/观测":
            return f"{evidence}，读这一项时先确认输入来自实测、回放、仿真，还是由模型生成"
        if label == "核心步骤":
            return f"{evidence}，把这些步骤按时间顺序串起来，就是论文的主处理链"
        if label == "模型或检测量":
            return f"{evidence}，这里要分清哪些量直接来自传感器，哪些量是作者为了判断风险或约束状态而构造出来的"
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
    details = _usable_detail_tokens(_detail_tokens(source))
    numbers = _usable_numbers(_numbers_and_units(source))
    if role == "problem":
        if len(details) >= 2:
            return f"把{_join_readable(details[:3])}放到同一个场景里看，核心是定位{profile['problem']}最先出现在哪个环节"
        if label == "场景压力":
            return f"先看论文把{profile['actor']}放进什么场景，开阔、遮挡、长距离或弱纹理环境都会改变系统可靠性"
        if label == "失效来源":
            return f"重点找输入在哪一步开始变坏：可能是观测退化、同步误差、动态干扰，也可能是外部信号被伪造或压制"
        if label == "作者抓住的变量":
            return "注意作者选了哪些可观测量来描述风险，例如残差、协方差、地图一致性、保护级、置信度或状态漂移"
        return f"影响不会只停在单个传感器，最后会传到{profile['engineering']}，这也是论文值得读的工程原因"
    if role == "method":
        if label == "输入/观测":
            if len(details) >= 2:
                return f"先把{_join_readable(details[:3])}分成传感器输入、平台或中间状态，后面的公式才容易跟上"
            return "先把传感器输入、时间同步和状态变量分清楚，后面再看各模块怎样传递信息"
        if label == "核心步骤" and len(details) >= 2:
            return f"把{_join_readable(details[:4])}按处理顺序串起来，确认每一步吃什么输入、吐出什么中间量"
        if label == "模型或检测量":
            if len(details) >= 2:
                return f"把{_join_readable(details[:4])}放回处理链里看，判断它们分别是观测量、模型模块还是实验设备"
            if len(numbers) >= 2:
                return f"把{_join_readable(numbers[:3])}对应到频率、误差、速度或算力上，避免把单个数字误读成结论"
            return "先分清直接观测、人工构造的约束量和最终优化目标，很多论文的创新就藏在这三者的连接方式里"
        if label == "输出形式":
            return f"输出要能回到{profile['engineering']}，否则方法只停留在离线演示"
        if label == "接入方式":
            return f"把结果接到{profile['engineering']}时，要明确它改变的是告警、权重、地图还是控制决策"
        return f"检查{profile['method']}分别消耗什么输入、产生什么中间量、怎样输出给后续模块"
    if role == "experiment":
        if label == "数据来源":
            if len(details) >= 2:
                return f"用{_join_readable(details[:3])}对照数据来源，重点确认真实采集、公开数据集和仿真各占多少"
            return "先确认数据来自真实设备、公开数据集还是仿真环境，再看是否覆盖论文声称的应用场景"
        if label == "实验场景":
            return f"把测试场景和{profile['scene']}对齐，看是否覆盖开阔、遮挡、长距离或传感器退化等困难条件"
        if label == "对比指标":
            if len(numbers) >= 2:
                return f"把{_join_readable(numbers[:3])}对应到误差、速度、距离或算力上，确认指标是否真的支撑结论"
            return f"先看指标是否直接衡量{profile['problem']}，再看它和对比方法是否公平"
        if label == "结果读法":
            return "重点不是单个结果好看，而是成功样例、困难样例和失败样例能不能共同解释作者的结论"
        if label == "失败边界":
            return "留意作者没有覆盖的场景：传感器失效、同步误差、动态物体、远距离运行或算力限制都可能改变结论"
        if len(numbers) >= 2:
            return f"先把{_join_readable(numbers[:4])}这些数字对应到场景强度、速度、误差或算力，不要只看单个数值大小"
        if len(details) >= 2:
            return f"围绕{_join_readable(details[:4])}复核数据来源、测试平台和对比对象"
        return f"把论文声称要解决的问题，和{profile['experiment']}逐项对齐"
    if len(details) >= 2:
        return f"结合{_join_readable(details[:3])}看结论边界，判断它是否真的能进入{profile['engineering']}"
    if label == "主要贡献":
        return "先用一句话归纳作者到底解决了什么：是提高鲁棒性、降低算力、扩展传感器组合，还是给出更清楚的风险边界"
    if label == "适用条件":
        return "看清楚成立条件：传感器配置、同步精度、场景覆盖、数据规模和算力预算一变，结论可能也会变"
    if label == "工程收益":
        return f"把收益翻译成系统语言：它能否减少误信、漂移、漏检、重建破碎或{profile['engineering']}里的计算开销"
    return "复现前先检查数据、参数、同步、评价脚本和失败样例；这些比单看平均指标更能暴露方法边界"


def _evidence_summary(claim: str) -> str:
    details = _usable_detail_tokens(_detail_tokens(claim))
    numbers = _usable_numbers(_numbers_and_units(claim))
    if details and len(numbers) >= 2:
        return f"这里提到{_join_readable(details[:3])}，同时给出{_join_readable(numbers[:3])}这类运行条件"
    if len(details) >= 2 and numbers:
        return f"这里提到{_join_readable(details[:3])}，并给出一个量化条件来说明具体设置"
    if len(details) >= 3:
        return f"这里串起{_join_readable(details[:4])}，适合用来定位系统组成或实验对象"
    if len(numbers) >= 2:
        return f"这里给出{_join_readable(numbers[:4])}这类量化条件，后面要看它们对应误差、速度还是算力"
    phrase = _safe_evidence_phrase(claim)
    return f"这一段的重点是{phrase}" if phrase else ""


def _join_readable(items: list[str] | tuple[str, ...]) -> str:
    clean = [item.strip() for item in items if item and item.strip()]
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]}和{clean[1]}"
    return "、".join(clean[:-1]) + f"和{clean[-1]}"


def _safe_evidence_phrase(text: str) -> str:
    phrase = _short_evidence(text, max_words=18, max_chars=118)
    if not _is_meaningful_evidence_text(phrase):
        return ""
    if not re.search(r"[\u4e00-\u9fff]", phrase):
        return ""
    return phrase


def _is_meaningful_evidence_text(text: str) -> bool:
    text = _clean_text(text).strip(" ,.;:，。；：")
    if not text:
        return False
    if re.fullmatch(r"[\d\s,.;:()\[\]{}+\-/%]+", text):
        return False
    if len(text) < 28 and len(re.findall(r"[A-Za-z]{3,}|[\u4e00-\u9fff]", text)) < 4:
        return False
    return True


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
        "ubspace aware": "Subspace-Aware",
        "subspace aware": "Subspace-Aware",
        "subspace-aware": "Subspace-Aware",
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
        if not _is_meaningful_evidence_text(sentence):
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
        r"\b\d+(?:\.\d+)?\s?(?:km/h|m/s|ms|ns|s|dB|Hz|kHz|MHz|GHz|m|km|%)\b",
        r"\b\d+(?:\.\d+)?x\b",
        r"\b\d+/\d+\b",
        r"\b\d+(?:\.\d+)?\s?(?:pages|figures|tables|scenarios|devices)\b",
    )
    values: list[str] = []
    for pattern in patterns:
        values.extend(match.group(0) for match in re.finditer(pattern, text, flags=re.IGNORECASE))
    return list(dict.fromkeys(values))


def _usable_numbers(numbers: list[str]) -> list[str]:
    usable: list[str] = []
    for number in numbers:
        clean = number.strip()
        if re.match(r"^\d{3,}\s*x$", clean, re.IGNORECASE):
            continue
        if clean.lower().endswith("x") and not re.match(r"^\d+(?:\.\d+)?x$", clean, re.IGNORECASE):
            continue
        usable.append(clean)
    return list(dict.fromkeys(usable))


def _detail_tokens(text: str) -> list[str]:
    tokens = _paper_terms_from_text(text)
    tokens.extend(
        match.group(0).strip()
        for match in re.finditer(r"\b[A-Z][A-Za-z0-9/+.-]{2,}(?:\s+[A-Z][A-Za-z0-9/+.-]{2,}){0,2}\b", text)
        if _looks_like_technical_name(match.group(0))
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
        "these",
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
        "command measured entry",
        "gps-referenced yas-region",
        "yas-region",
    }
    for token in tokens:
        token = token.strip(" ,.;:()[]")
        token = re.sub(r"\s+", " ", token)
        token = re.sub(r"\b(The|This|Under|Within|Both)$", "", token).strip()
        lowered = token.lower()
        if lowered in stop_terms:
            continue
        if lowered.startswith(("these ", "this ", "the ")):
            continue
        if "referenced" in lowered and "gps" not in lowered and "gnss" not in lowered:
            continue
        if len(token) < 3:
            continue
        cleaned.setdefault(token.lower(), _canonical_term(token))
    return list(cleaned.values())


def _usable_detail_tokens(tokens: list[str]) -> list[str]:
    generic = {
        "gnss",
        "gps",
        "slam",
        "lidar",
        "imu",
        "vio",
        "livo",
        "visual",
        "camera",
        "localization",
        "navigation",
        "mapping",
        "odometry",
        "fusion",
        "dataset",
        "benchmark",
        "robot",
        "table",
        "table i",
        "table ii",
        "table iii",
        "table iv",
    }
    blocked_fragments = (
        "omponent- wise",
        "component- wise",
        "ablation",
        "sion",
        "avg ",
    )
    blocked_exact = {
        "idar",
        "isual",
        "nfo",
        "orm",
    }
    cleaned: list[str] = []
    for token in tokens:
        item = token.strip()
        lowered = item.lower()
        if not item or lowered in generic or lowered in blocked_exact:
            continue
        if any(fragment in lowered for fragment in blocked_fragments):
            continue
        cleaned.append(item)
    if cleaned:
        return list(dict.fromkeys(cleaned))
    return []


def _looks_like_technical_name(token: str) -> bool:
    token = token.strip(" ,.;:()[]")
    if not token:
        return False
    lowered = token.lower()
    if lowered.startswith(("the ", "this ", "these ", "where ", "while ")):
        return False
    if lowered in {"command measured entry", "gps-referenced yas-region", "yas-region", "idar", "isual", "nfo", "orm"}:
        return False
    if re.search(r"\b[A-Z]{2,}\b", token):
        return True
    if re.search(r"\d", token):
        return True
    if any(mark in token for mark in ("/", "+")):
        return True
    allowed = (
        "HackRF",
        "Commsignia",
        "Septentrio",
        "Livox",
        "Jetson",
        "Yas Marina",
    )
    return any(name.lower() in lowered for name in allowed)


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


def _wechat_title(paper: dict[str, Any], *, variant: str | None = None) -> str:
    display_title = _display_title(paper)
    lowered = display_title.lower()
    if "jamming" in lowered and "agc" in lowered:
        return _with_variant_suffix("论文解读｜GNSS干扰检测：AGC与C/N0", variant)
    if "lxd-slam" in lowered:
        return _with_variant_suffix("论文解读｜LXD-SLAM：32种传感器组合", variant)
    if "self-supervised" in lowered and "geometry" in lowered:
        return _with_variant_suffix("论文解读｜LiDAR SLAM自监督几何推理", variant)
    title = "论文解读｜" + display_title
    title = _with_variant_suffix(title, variant)
    if len(title) <= 34:
        return title
    return title[:31].rstrip(" -:：,，") + "..."


def _with_variant_suffix(title: str, variant: str | None) -> str:
    if variant == "ai":
        return f"{title}｜AI版"
    if variant == "paper":
        return f"{title}｜原图版"
    return title


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
    return f"从摘要和图注看，论文反复围绕 {', '.join(list(dict.fromkeys(keywords))[:5])} 展开，说明这些量就是阅读时应优先跟踪的主线。"


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
    parser.add_argument(
        "--image-mode",
        choices=("paper", "ai", "both"),
        default=os.getenv("DEEPDIVE_IMAGE_MODE", "paper"),
        help="paper=use matched paper figures, ai=use a Gemini concept cover, both=write both versions.",
    )
    parser.add_argument(
        "--figure-keywords",
        default=os.getenv("DEEPDIVE_FIGURE_KEYWORDS", ",".join(_default_figure_keywords())),
        help="Comma-separated caption keywords used to prioritize framework or flowchart-like paper figures.",
    )
    parser.add_argument("--publish-mode", choices=("none", "draft", "publish"), default="none")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
