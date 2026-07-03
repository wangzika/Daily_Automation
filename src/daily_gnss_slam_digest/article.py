from __future__ import annotations

import html
import json
from datetime import date
from pathlib import Path
from typing import Mapping

from .config import PROJECT_TITLE
from .models import RecommendedPaper


def build_markdown(
    recommendations: list[RecommendedPaper],
    issue_date: date,
    image_paths: Mapping[str, str] | None = None,
) -> str:
    title = build_title(issue_date)
    image_paths = image_paths or {}
    lines: list[str] = [
        f"# {title}",
        "",
        "今天的推荐聚焦三个交叉点：GNSS 欺骗/干扰检测、多模态融合定位、SLAM 与鲁棒里程计。筛选逻辑优先考虑主题相关性、新近度、引用/venue/开源代码等质量信号，以及是否能给工程系统带来可验证的思路。",
        "",
        "## 筛选方法论",
        "",
        "这份日报不是简单按 arXiv 最新排序，而是先用主题查询收集候选论文，再做标题级去重，并按关键词命中、主题覆盖、发布时间、引用/venue/代码/数据集线索和工程迁移价值排序。阅读时建议重点看：问题定义是否清晰、观测量是否可靠、融合位置是否合理、实验是否覆盖失败案例。",
        "",
    ]
    if "methodology" in image_paths:
        lines.extend([f"![筛选方法论]({image_paths['methodology']})", ""])

    lines.extend(["## 今日速览", ""])
    for index, item in enumerate(recommendations, start=1):
        paper = item.paper
        lines.extend(
            [
                f"{index}. **{paper.title}**",
                f"   - 作者：{_format_authors(paper.authors)}",
                f"   - 日期：{paper.published.date().isoformat()}",
                f"   - 链接：{paper.url}",
                f"   - 质量信号：{_quality_summary(item)}",
                f"   - 推荐理由：{item.reason}",
            ]
        )

    lines.extend(["", "## 重点推荐", ""])
    for index, item in enumerate(recommendations, start=1):
        paper = item.paper
        lines.extend(
            [
                f"### {index}. {paper.title}",
                "",
                f"- **论文信息**：{_format_authors(paper.authors)}；{paper.published.date().isoformat()}；{paper.primary_category or 'arXiv'}",
                f"- **原文链接**：{paper.url}",
                f"- **关键词**：{_format_terms(item.matched_terms)}",
                f"- **质量信号**：{_quality_summary(item)}",
                f"- **为什么值得读**：{_analysis_for(item)}",
                f"- **对 GNSS/融合/SLAM 系统的启发**：{_engineering_takeaway(item)}",
                f"- **摘要要点**：{_abstract_digest(item)}",
                "",
            ]
        )

    if "rubric" in image_paths:
        lines.extend(["## 推荐阅读框架", "", f"![推荐阅读框架]({image_paths['rubric']})", ""])

    lines.extend(
        [
            "## 今日观察",
            "",
            "GNSS 相关论文正在从单点接收机检测走向跨传感器、跨平台和时空一致性验证；SLAM 方向则越来越强调在退化、动态和大尺度场景下的恢复能力。对自动驾驶、无人机和机器人系统来说，下一步值得重点关注的是：把 GNSS 完整性监测放进状态估计闭环，而不是只把它当成后处理告警。",
            "",
            "## 明日检索关键词",
            "",
            "`GNSS spoofing detection`、`PNT integrity`、`LiDAR-Inertial-Visual-GNSS`、`degeneracy-aware odometry`、`multimodal SLAM`、`factor graph fusion`。",
            "",
            "> 本文基于公开论文元数据生成，建议阅读原文后再引用具体实验结论。",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def build_html(
    recommendations: list[RecommendedPaper],
    issue_date: date,
    image_urls: Mapping[str, str] | None = None,
) -> str:
    title = build_title(issue_date)
    image_urls = image_urls or {}

    body_parts: list[str] = [
        (
            '<section style="margin:0 0 20px;padding:18px 18px 16px;'
            'border-left:4px solid #25d8b8;background:#f5fbfa;color:#24343a;'
            'line-height:1.85;font-size:15px;">'
            "今天的推荐聚焦 <strong>GNSS 欺骗/干扰检测</strong>、"
            "<strong>多模态融合定位</strong>、<strong>SLAM 与鲁棒里程计</strong>。"
            "筛选逻辑优先考虑主题相关性、新近度、引用/venue/开源代码等质量信号，"
            "以及是否能给工程系统带来可验证的思路。"
            "</section>"
        ),
        _section_title("筛选方法论"),
        _paragraph("这份日报不是简单按 arXiv 最新排序，而是先用主题查询收集候选论文，再做标题级去重，并按关键词命中、主题覆盖、发布时间、引用/venue/代码/数据集线索和工程迁移价值排序。读者可以把它当成一个每日研究雷达：先定位方向，再判断是否值得阅读全文。"),
    ]
    if "methodology" in image_urls:
        body_parts.append(_article_image(image_urls["methodology"], "方法论：从论文流到工程判断"))

    body_parts.extend([_method_cards(), _section_title("今日速览")])

    for index, item in enumerate(recommendations, start=1):
        paper = item.paper
        body_parts.append(
            '<section style="margin:0 0 12px;padding:14px 15px;border:1px solid #e5eef0;'
            'border-radius:8px;background:#ffffff;">'
            f'<p style="margin:0 0 8px;color:#0b9984;font-size:13px;">#{index} · {paper.published.date().isoformat()} · {html.escape(paper.primary_category or "arXiv")}</p>'
            f'<p style="margin:0 0 8px;color:#17272d;font-weight:700;font-size:16px;line-height:1.55;">{html.escape(paper.title)}</p>'
            f'<p style="margin:0;color:#687d84;font-size:13px;line-height:1.7;">{html.escape(_format_authors(paper.authors))}</p>'
            f'<p style="margin:8px 0 0;color:#40545c;font-size:13px;line-height:1.7;">质量信号：{html.escape(_quality_summary(item))}</p>'
            "</section>"
        )

    body_parts.append(_section_title("重点推荐"))
    for index, item in enumerate(recommendations, start=1):
        body_parts.append(_paper_card(index, item))

    if "rubric" in image_urls:
        body_parts.extend([_section_title("推荐阅读框架"), _article_image(image_urls["rubric"], "推荐阅读框架")])

    body_parts.extend(
        [
            _section_title("今日观察"),
            _callout("GNSS 相关论文正在从单点接收机检测走向跨传感器、跨平台和时空一致性验证；SLAM 方向则越来越强调在退化、动态和大尺度场景下的恢复能力。对自动驾驶、无人机和机器人系统来说，下一步值得重点关注的是：把 GNSS 完整性监测放进状态估计闭环，而不是只把它当成后处理告警。"),
            _section_title("明日检索关键词"),
            _tag_line(("GNSS spoofing detection", "PNT integrity", "LiDAR-Inertial-Visual-GNSS", "degeneracy-aware odometry", "multimodal SLAM", "factor graph fusion")),
            '<p style="margin:22px 0 0;color:#8a9da3;font-size:13px;line-height:1.8;">本文基于公开论文元数据生成，建议阅读原文后再引用具体实验结论。</p>',
        ]
    )

    return (
        '<section style="max-width:677px;margin:0 auto;color:#24343a;'
        'font-family:-apple-system,BlinkMacSystemFont,Helvetica Neue,Arial,sans-serif;">'
        f'<h1 style="margin:0 0 14px;color:#10272f;font-size:24px;line-height:1.35;font-weight:800;">{html.escape(title)}</h1>'
        + "\n".join(body_parts)
        + "</section>"
    )


def write_outputs(
    recommendations: list[RecommendedPaper],
    issue_date: date,
    output_dir: Path,
    image_paths: Mapping[str, str] | None = None,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{issue_date.isoformat()}-gnss-slam-digest"
    markdown_path = output_dir / f"{stem}.md"
    html_path = output_dir / f"{stem}.html"
    json_path = output_dir / f"{stem}.json"

    markdown_path.write_text(build_markdown(recommendations, issue_date, image_paths=image_paths), encoding="utf-8")
    html_path.write_text(build_html(recommendations, issue_date, image_urls=image_paths), encoding="utf-8")
    json_path.write_text(_to_json(recommendations), encoding="utf-8")

    return {"markdown": markdown_path, "html": html_path, "json": json_path}


def build_title(issue_date: date) -> str:
    return f"{PROJECT_TITLE} | {issue_date.isoformat()}"


def build_digest(recommendations: list[RecommendedPaper]) -> str:
    if not recommendations:
        return "今日未检索到足够相关的新论文，建议扩大检索窗口。"
    first = recommendations[0].paper.title
    return f"今日精选 {len(recommendations)} 篇 GNSS 欺骗检测、多模态融合与 SLAM 相关论文，重点推荐：{first}"


def _format_authors(authors: tuple[str, ...]) -> str:
    if not authors:
        return "Unknown"
    if len(authors) <= 4:
        return ", ".join(authors)
    return ", ".join(authors[:4]) + " 等"


def _format_terms(terms: tuple[str, ...]) -> str:
    return "、".join(terms[:10]) if terms else "GNSS、fusion、SLAM"


def _quality_summary(item: RecommendedPaper) -> str:
    signals = item.quality_signals
    parts: list[str] = [f"质量分 {item.quality_score:.1f}"]
    citation_count = signals.get("citation_count")
    if isinstance(citation_count, int):
        parts.append(f"引用 {citation_count}")
    influential_count = signals.get("influential_citation_count")
    if isinstance(influential_count, int) and influential_count > 0:
        parts.append(f"高影响引用 {influential_count}")
    venue = signals.get("venue")
    if isinstance(venue, str) and venue:
        parts.append(f"venue {venue}")
    if signals.get("code_url"):
        parts.append("代码开源")
    elif signals.get("code_signal"):
        parts.append("有代码线索")
    if signals.get("dataset_signal"):
        parts.append("数据集/benchmark")
    if signals.get("real_world_signal"):
        parts.append("真实实验")
    if len(parts) == 1:
        parts.append("暂无外部质量元数据")
    return "；".join(parts[:6])


def _analysis_for(item: RecommendedPaper) -> str:
    topics = "、".join(item.topic_scores.keys()) or "相关方向"
    terms = _format_terms(item.matched_terms)
    quality = _quality_summary(item)
    return f"这篇论文同时覆盖 {topics}，并在标题/摘要中出现 {terms} 等信号；质量侧还有 {quality}。它适合用来观察该方向近期如何处理鲁棒性、异常检测或融合估计问题。"


def _engineering_takeaway(item: RecommendedPaper) -> str:
    terms = set(item.matched_terms)
    if {"spoofing", "jamming", "interference"} & terms:
        return "可借鉴其异常定义和误报抑制思路，把 GNSS 可信度作为状态估计输入的一部分，而不是孤立阈值。"
    if {"lidar", "visual", "inertial", "imu", "fusion"} & terms:
        return "适合关注传感器时空同步、退化场景切换和外点剔除策略，这些通常决定系统能否从实验室走向实车/无人机部署。"
    if {"slam", "odometry", "loop", "mapping"} & terms:
        return "可以从前端观测选择、后端约束建模和回环恢复三个角度拆解，判断它是否适合迁移到自己的 SLAM 栈。"
    return "建议重点看数据集、消融实验和失败案例，判断论文方法是否能落到真实平台。"


def _abstract_digest(item: RecommendedPaper) -> str:
    terms = set(item.matched_terms)
    if {"spoofing", "jamming", "interference"} & terms:
        domain = "GNSS 欺骗/干扰场景下的异常识别与完整性监测"
        focus = "可观测量设计、误报控制、攻击与非攻击故障的区分方式"
    elif {"fusion", "multi-sensor", "multimodal"} & terms:
        domain = "多传感器融合定位中的一致性、同步和退化处理"
        focus = "融合框架、传感器缺失时的降级策略、外点剔除和实时性"
    elif {"slam", "odometry", "mapping"} & terms:
        domain = "SLAM/里程计在复杂环境中的鲁棒状态估计"
        focus = "前端几何建模、后端约束、回环或地图表达对鲁棒性的贡献"
    else:
        domain = "机器人定位与感知系统中的鲁棒估计问题"
        focus = "问题设定、数据集、对比基线和失败案例"

    method_terms = _format_terms(item.matched_terms[:6])
    return (
        f"从题名与摘要看，论文主要关注 {domain}；方法线索包括 {method_terms}。"
        f"阅读全文时建议重点看 {focus}，再判断是否适合迁移到自己的工程链路。"
    )


def _paragraph(text: str) -> str:
    return f'<p style="margin:0 0 16px;color:#43565d;font-size:15px;line-height:1.9;">{html.escape(text)}</p>'


def _section_title(text: str) -> str:
    return (
        '<section style="margin:28px 0 14px;">'
        '<p style="margin:0 0 7px;width:42px;height:4px;background:#25d8b8;border-radius:2px;"></p>'
        f'<h2 style="margin:0;color:#122b34;font-size:21px;line-height:1.45;font-weight:800;">{html.escape(text)}</h2>'
        "</section>"
    )


def _article_image(src: str, caption: str) -> str:
    return (
        '<section style="margin:16px 0 20px;">'
        f'<img src="{html.escape(src)}" alt="{html.escape(caption)}" style="display:block;width:100%;height:auto;border-radius:8px;"/>'
        f'<p style="margin:8px 0 0;text-align:center;color:#7f9399;font-size:12px;">{html.escape(caption)}</p>'
        "</section>"
    )


def _method_cards() -> str:
    items = (
        ("1", "先看问题", "欺骗/干扰、融合退化，还是 SLAM 鲁棒性？"),
        ("2", "再看质量", "引用、venue、代码、数据集和真实实验线索是否足够？"),
        ("3", "最后看迁移", "误报率、实时性、失败案例和传感器配置是否可信？"),
    )
    cards = []
    for number, title, body in items:
        cards.append(
            '<section style="margin:0 0 10px;padding:13px 14px;background:#f7fbfb;'
            'border:1px solid #e0eeee;border-radius:8px;">'
            f'<p style="margin:0 0 6px;color:#0b9984;font-weight:700;font-size:14px;">{number}. {html.escape(title)}</p>'
            f'<p style="margin:0;color:#51676f;font-size:14px;line-height:1.75;">{html.escape(body)}</p>'
            "</section>"
        )
    return "".join(cards)


def _paper_card(index: int, item: RecommendedPaper) -> str:
    paper = item.paper
    return (
        '<section style="margin:0 0 22px;padding:18px 16px;border:1px solid #dce9eb;'
        'border-radius:10px;background:#ffffff;">'
        f'<p style="margin:0 0 10px;color:#0b9984;font-size:14px;font-weight:700;">{index:02d} · {paper.published.date().isoformat()} · {html.escape(paper.primary_category or "arXiv")}</p>'
        f'<h3 style="margin:0 0 12px;color:#10272f;font-size:18px;line-height:1.5;font-weight:800;">{html.escape(paper.title)}</h3>'
        f'<p style="margin:0 0 12px;color:#72868c;font-size:13px;line-height:1.7;">作者：{html.escape(_format_authors(paper.authors))}</p>'
        f'{_label_block("关键词", _format_terms(item.matched_terms))}'
        f'{_label_block("质量信号", _quality_summary(item))}'
        f'{_label_block("为什么值得读", _analysis_for(item))}'
        f'{_label_block("工程启发", _engineering_takeaway(item))}'
        f'{_label_block("摘要要点", _abstract_digest(item))}'
        f'<p style="margin:12px 0 0;font-size:14px;line-height:1.8;">原文：<a href="{html.escape(paper.url)}" style="color:#0b9984;text-decoration:none;">{html.escape(paper.url)}</a></p>'
        "</section>"
    )


def _label_block(label: str, body: str) -> str:
    return (
        '<section style="margin:10px 0 0;">'
        f'<p style="margin:0 0 4px;color:#0f7f72;font-size:13px;font-weight:700;">{html.escape(label)}</p>'
        f'<p style="margin:0;color:#40545c;font-size:14px;line-height:1.82;">{html.escape(body)}</p>'
        "</section>"
    )


def _callout(text: str) -> str:
    return (
        '<section style="margin:0 0 18px;padding:16px;background:#f4fbf9;'
        'border-left:4px solid #25d8b8;color:#34484f;font-size:15px;line-height:1.9;">'
        f"{html.escape(text)}"
        "</section>"
    )


def _tag_line(tags: tuple[str, ...]) -> str:
    return "".join(
        f'<span style="display:inline-block;margin:0 8px 8px 0;padding:5px 9px;'
        f'border-radius:14px;background:#eef8f7;color:#0b8275;font-size:12px;">{html.escape(tag)}</span>'
        for tag in tags
    )


def _to_json(recommendations: list[RecommendedPaper]) -> str:
    payload = []
    for item in recommendations:
        paper = item.paper
        payload.append(
            {
                "title": paper.title,
                "authors": list(paper.authors),
                "url": paper.url,
                "pdf_url": paper.pdf_url,
                "published": paper.published.isoformat(),
                "updated": paper.updated.isoformat(),
                "categories": list(paper.categories),
                "primary_category": paper.primary_category,
                "arxiv_id": paper.arxiv_id,
                "comment": paper.comment,
                "journal_ref": paper.journal_ref,
                "doi": paper.doi,
                "citation_count": paper.citation_count,
                "influential_citation_count": paper.influential_citation_count,
                "venue": paper.venue,
                "code_url": paper.code_url,
                "score": item.score,
                "topic_scores": item.topic_scores,
                "matched_terms": list(item.matched_terms),
                "quality_score": item.quality_score,
                "quality_signals": item.quality_signals,
                "reason": item.reason,
            }
        )
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
