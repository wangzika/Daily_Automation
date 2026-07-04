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
    focus_topic: str = "",
) -> str:
    title = build_title(issue_date)
    image_paths = image_paths or {}
    focus_topic = focus_topic or "GNSS 欺骗/干扰检测、多模态融合定位、SLAM 与鲁棒里程计"
    suggested_terms = _suggested_terms_for_focus(focus_topic)
    lines: list[str] = [
        f"# {title}",
        "",
    ]
    if "header" in image_paths:
        lines.extend([f"![{focus_topic}]({image_paths['header']})", ""])

    lines.extend(
        [
            f"今天这期看 **{focus_topic}**。",
            "",
            _opening_note(focus_topic, len(recommendations)),
            "",
        ]
    )

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

    lines.extend(
        [
            "## 今日观察",
            "",
            _topic_observation(focus_topic),
            "",
            "## 明日检索关键词",
            "",
            "、".join(f"`{term}`" for term in suggested_terms) + "。",
            "",
            "> 具体实验结论建议回到原文核对后再引用。",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def build_html(
    recommendations: list[RecommendedPaper],
    issue_date: date,
    image_urls: Mapping[str, str] | None = None,
    focus_topic: str = "",
) -> str:
    title = build_title(issue_date)
    image_urls = image_urls or {}
    focus_topic = focus_topic or "GNSS 欺骗/干扰检测、多模态融合定位、SLAM 与鲁棒里程计"
    suggested_terms = _suggested_terms_for_focus(focus_topic)

    body_parts: list[str] = []
    if "header" in image_urls:
        body_parts.append(_article_image(image_urls["header"], ""))

    body_parts.extend(
        [
            (
                '<section style="margin:0 0 20px;padding:18px 18px 16px;'
                'border-left:4px solid #25d8b8;background:#f5fbfa;color:#24343a;'
                'line-height:1.85;font-size:15px;">'
                f"今天这期看 <strong>{html.escape(focus_topic)}</strong>。"
                f"{html.escape(_opening_note(focus_topic, len(recommendations)))}"
                "</section>"
            ),
            _section_title("今日速览"),
        ]
    )

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

    body_parts.extend(
        [
            _section_title("今日观察"),
            _callout(_topic_observation(focus_topic)),
            _section_title("明日检索关键词"),
            _tag_line(suggested_terms),
            '<p style="margin:22px 0 0;color:#8a9da3;font-size:13px;line-height:1.8;">具体实验结论建议回到原文核对后再引用。</p>',
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
    focus_topic: str = "",
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{issue_date.isoformat()}-gnss-slam-digest"
    markdown_path = output_dir / f"{stem}.md"
    html_path = output_dir / f"{stem}.html"
    json_path = output_dir / f"{stem}.json"

    markdown_path.write_text(
        build_markdown(recommendations, issue_date, image_paths=image_paths, focus_topic=focus_topic),
        encoding="utf-8",
    )
    html_path.write_text(
        build_html(recommendations, issue_date, image_urls=image_paths, focus_topic=focus_topic),
        encoding="utf-8",
    )
    json_path.write_text(_to_json(recommendations), encoding="utf-8")

    return {"markdown": markdown_path, "html": html_path, "json": json_path}


def build_title(issue_date: date) -> str:
    return f"{PROJECT_TITLE} | {issue_date.isoformat()}"


def build_digest(recommendations: list[RecommendedPaper], focus_topic: str = "") -> str:
    if not recommendations:
        return "今日未检索到足够相关的新论文，建议扩大检索窗口。"
    first = recommendations[0].paper.title
    topic_text = focus_topic or "GNSS 欺骗检测、多模态融合与 SLAM"
    return f"今日围绕 {topic_text} 精选 {len(recommendations)} 篇相关论文，重点推荐：{first}"


def _opening_note(focus_topic: str, count: int) -> str:
    if "具身导航" in focus_topic:
        return f"我挑了 {count} 篇最近值得看的论文，重点放在语言指令、视觉理解和移动机器人决策怎样接到一起。这个方向热闹，但真正有价值的工作通常能说明机器人在哪里失败、怎样恢复、能否走出仿真。"
    if "3DGS" in focus_topic or "NeRF" in focus_topic:
        return f"我挑了 {count} 篇最近值得看的论文，重点放在神经场地图和实时 SLAM 的结合。读这类工作时，最值得盯住的是地图表达带来的增益，是否抵得过计算、内存和动态场景里的代价。"
    if "开放词汇" in focus_topic:
        return f"我挑了 {count} 篇最近值得看的论文，重点看语义地图怎样从“能建图”走向“能听懂任务”。如果地图里的物体、区域和语言目标能稳定对上，导航系统就会多一层可解释的抓手。"
    if "地点识别" in focus_topic:
        return f"我挑了 {count} 篇最近值得看的论文，重点看长期定位和回环检测。一个系统能不能在季节、天气、光照和视角变化后认出同一个地方，往往决定它能不能长期运行。"
    if "多机器人" in focus_topic:
        return f"我挑了 {count} 篇最近值得看的论文，重点看多机器人之间怎样共享地图、约束和相对位姿。协同 SLAM 的难点不只是多几台设备，而是通信受限、错误关联和全局一致性会同时出现。"
    if "PNT" in focus_topic or "GNSS" in focus_topic:
        return f"我挑了 {count} 篇最近值得看的论文，重点看 GNSS 异常、PNT 完整性和抗欺骗抗干扰。真正有用的工作不只报告检测率，还会说明误报从哪里来，以及定位系统怎样在告警后继续工作。"
    if "退化场景" in focus_topic or "里程计" in focus_topic:
        return f"我挑了 {count} 篇最近值得看的论文，重点看视觉、激光、惯导和 GNSS 在退化场景里的互相补位。鲁棒里程计的关键不是传感器堆得多，而是知道什么时候该相信谁。"
    return f"我挑了 {count} 篇最近值得看的论文，重点看它们能给机器人导航、定位和建图系统带来什么具体启发。"


def _topic_observation(focus_topic: str) -> str:
    if "具身导航" in focus_topic:
        return "具身导航正在从“给定目标点”转向“理解人的意图”。这会把定位、地图、感知和策略学习绑得更紧：机器人不仅要知道自己在哪，还要知道目标是什么、哪些路径可执行、失败后怎样重新规划。"
    if "3DGS" in focus_topic or "NeRF" in focus_topic:
        return "神经场 SLAM 的吸引力在于地图更稠密、更接近可渲染世界；挑战在于实时性、内存占用和动态物体处理。近期值得关注的是：这些方法能否从漂亮重建走向稳定定位。"
    if "开放词汇" in focus_topic:
        return "开放词汇语义地图把语言和空间连起来，让机器人可以围绕“桌子旁边”“红色门口”这类目标行动。下一步的关键，是让语义标签在长期运行中保持一致，而不是每次换视角就重新猜一遍。"
    if "地点识别" in focus_topic:
        return "长期定位的核心问题很朴素：同一个地方在不同时间看起来不像同一个地方。好的地点识别方法要在外观变化中抓住稳定结构，同时避免把相似走廊、路口和建筑误认为回环。"
    if "多机器人" in focus_topic:
        return "多机器人 SLAM 的价值不只是更快建图，而是让系统在单机视野不足时仍能补全环境。难点也很现实：带宽有限、坐标系不统一、错误回环会被迅速放大。"
    if "PNT" in focus_topic or "GNSS" in focus_topic:
        return "PNT 韧性正在从单一 GNSS 接收机指标，走向多源一致性判断。对机器人和无人系统来说，更可靠的做法是把欺骗、干扰、遮挡和传感器退化一起放进状态估计链路里处理。"
    if "退化场景" in focus_topic or "里程计" in focus_topic:
        return "鲁棒里程计最怕的是系统不知道自己已经不可靠。最近的趋势是把退化检测、传感器可信度和因子图约束放在一起，让系统在弱纹理、强动态、空旷或遮挡场景下有更平滑的降级能力。"
    return "导航定位论文越来越强调真实平台里的稳定性：不仅要在标准数据集上好看，还要能解释误差从哪里来、失败后怎样恢复、部署时要付出多少计算和传感器成本。"


def _format_authors(authors: tuple[str, ...]) -> str:
    if not authors:
        return "Unknown"
    if len(authors) <= 4:
        return ", ".join(authors)
    return ", ".join(authors[:4]) + " 等"


def _format_terms(terms: tuple[str, ...]) -> str:
    return "、".join(terms[:10]) if terms else "GNSS、fusion、SLAM"


def _suggested_terms_for_focus(focus_topic: str) -> tuple[str, ...]:
    presets: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "具身导航",
            (
                "embodied navigation",
                "vision-language navigation",
                "object navigation",
                "navigation foundation model",
                "mobile robot policy",
                "VLM navigation",
            ),
        ),
        (
            "3DGS",
            (
                "Gaussian Splatting SLAM",
                "3D Gaussian Splatting mapping",
                "NeRF SLAM",
                "neural implicit SLAM",
                "dense visual SLAM",
                "real-time reconstruction",
            ),
        ),
        (
            "开放词汇",
            (
                "open vocabulary mapping",
                "semantic mapping",
                "language-guided navigation",
                "object goal navigation",
                "scene graph SLAM",
                "3D semantic map",
            ),
        ),
        (
            "地点识别",
            (
                "visual place recognition",
                "LiDAR place recognition",
                "loop closure",
                "long-term localization",
                "cross-modal place recognition",
                "re-localization",
            ),
        ),
        (
            "多机器人",
            (
                "multi-robot SLAM",
                "collaborative SLAM",
                "distributed mapping",
                "cooperative localization",
                "communication-efficient SLAM",
                "multi-agent localization",
            ),
        ),
        (
            "韧性 PNT",
            (
                "resilient PNT",
                "GNSS spoofing detection",
                "GNSS jamming detection",
                "PNT integrity",
                "OSNMA",
                "GNSS denied localization",
            ),
        ),
        (
            "退化场景",
            (
                "robust odometry",
                "LiDAR-inertial odometry",
                "visual-inertial odometry",
                "factor graph fusion",
                "degeneracy-aware odometry",
                "sensor degradation",
            ),
        ),
    )
    for needle, terms in presets:
        if needle in focus_topic:
            return terms
    return (
        "GNSS spoofing detection",
        "PNT integrity",
        "LiDAR-Inertial-Visual-GNSS",
        "degeneracy-aware odometry",
        "multimodal SLAM",
        "factor graph fusion",
    )


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
    return f"从题名与摘要看，论文主要关注 {domain}；技术线索包括 {method_terms}。阅读全文时建议重点看 {focus}，再判断是否适合迁移到自己的工程链路。"


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
    caption_html = (
        f'<p style="margin:8px 0 0;text-align:center;color:#7f9399;font-size:12px;">{html.escape(caption)}</p>'
        if caption
        else ""
    )
    return (
        '<section style="margin:16px 0 20px;">'
        f'<img src="{html.escape(src)}" alt="{html.escape(caption)}" style="display:block;width:100%;height:auto;border-radius:8px;"/>'
        f"{caption_html}"
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
                "abstract": paper.abstract,
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
