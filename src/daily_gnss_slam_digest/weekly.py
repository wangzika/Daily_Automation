from __future__ import annotations

import argparse
import html
import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .config import ROBOTICS_TREND_TOPICS, TopicProfile


@dataclass(frozen=True)
class WeeklyPaper:
    title: str
    url: str
    published: str
    score: float
    topic_scores: dict[str, float]
    matched_terms: tuple[str, ...]
    quality_score: float
    quality_signals: dict[str, Any]
    source_date: date


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    end_date = date.fromisoformat(args.end_date) if args.end_date else date.today()
    papers = load_weekly_papers(args.input_dir, end_date=end_date, days=args.days)
    if not papers:
        print("No weekly digest papers found.")
        return 2

    paths = write_weekly_outputs(papers, end_date=end_date, output_dir=args.output_dir)
    print(f"Wrote weekly markdown: {paths['markdown']}")
    print(f"Wrote weekly html: {paths['html']}")
    print(f"Wrote weekly json: {paths['json']}")
    return 0


def load_weekly_papers(input_dir: Path, *, end_date: date, days: int = 7) -> list[WeeklyPaper]:
    start_date = end_date - timedelta(days=days - 1)
    papers: list[WeeklyPaper] = []
    for path in sorted(input_dir.glob("*-gnss-slam-digest.json")):
        source_date = _date_from_digest_filename(path)
        if source_date is None or source_date < start_date or source_date > end_date:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, list):
            continue
        for item in payload:
            if isinstance(item, dict):
                papers.append(_paper_from_item(item, source_date))
    return _deduplicate_weekly_papers(papers)


def write_weekly_outputs(
    papers: list[WeeklyPaper],
    *,
    end_date: date,
    output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    year, week, _weekday = end_date.isocalendar()
    stem = f"{year}-W{week:02d}-gnss-slam-weekly"
    markdown_path = output_dir / f"{stem}.md"
    html_path = output_dir / f"{stem}.html"
    json_path = output_dir / f"{stem}.json"

    summary = build_weekly_summary(papers)
    markdown_path.write_text(build_markdown(summary, end_date), encoding="utf-8")
    html_path.write_text(build_html(summary, end_date), encoding="utf-8")
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"markdown": markdown_path, "html": html_path, "json": json_path}


def build_weekly_summary(papers: list[WeeklyPaper]) -> dict[str, Any]:
    topic_counter: Counter[str] = Counter()
    term_counter: Counter[str] = Counter()
    direction_counter: Counter[str] = Counter()
    robotics_trend_counter: Counter[str] = Counter()
    for paper in papers:
        topic_counter.update(paper.topic_scores.keys())
        term_counter.update(term for term in paper.matched_terms if len(term) > 2)
        direction_counter.update(_directions_for(paper))
        robotics_trend_counter.update(_robotics_trends_for(paper))

    top_papers = sorted(papers, key=lambda item: (item.quality_score, item.score), reverse=True)[:8]
    code_papers = [paper for paper in top_papers if paper.quality_signals.get("code_url") or paper.quality_signals.get("code_signal")]
    venue_papers = [paper for paper in top_papers if paper.quality_signals.get("venue")]

    return {
        "paper_count": len(papers),
        "source_dates": sorted({paper.source_date.isoformat() for paper in papers}),
        "hot_topics": topic_counter.most_common(8),
        "hot_terms": term_counter.most_common(16),
        "hot_directions": direction_counter.most_common(8),
        "hot_robotics_trends": robotics_trend_counter.most_common(10),
        "top_papers": [_paper_to_json(paper) for paper in top_papers],
        "code_papers": [_paper_to_json(paper) for paper in code_papers[:5]],
        "venue_papers": [_paper_to_json(paper) for paper in venue_papers[:5]],
    }


def build_markdown(summary: dict[str, Any], end_date: date) -> str:
    lines = [
        f"# 每周 GNSS/融合/SLAM 热点汇总 | {end_date.isoformat()}",
        "",
        f"本周共聚合 {summary['paper_count']} 篇日报候选论文，覆盖日期：{', '.join(summary['source_dates'])}。",
        "",
        "## 热点方向",
        "",
        *_markdown_ranked(summary["hot_directions"]),
        "",
        "## 机器人领域热点雷达",
        "",
        *_markdown_ranked(summary["hot_robotics_trends"]),
        "",
        "## 高频主题",
        "",
        *_markdown_ranked(summary["hot_topics"]),
        "",
        "## 高频关键词",
        "",
        *_markdown_ranked(summary["hot_terms"]),
        "",
        "## 本周最值得追的论文",
        "",
    ]
    for index, paper in enumerate(summary["top_papers"], start=1):
        lines.extend(
            [
                f"{index}. **{paper['title']}**",
                f"   - 质量分：{paper['quality_score']}",
                f"   - 质量信号：{paper['quality_summary']}",
                f"   - 链接：{paper['url']}",
            ]
        )

    if summary["code_papers"]:
        lines.extend(["", "## 有代码/复现线索", ""])
        for paper in summary["code_papers"]:
            lines.append(f"- **{paper['title']}**：{paper['quality_summary']}；{paper['url']}")

    if summary["venue_papers"]:
        lines.extend(["", "## 有 venue / 引用线索", ""])
        for paper in summary["venue_papers"]:
            lines.append(f"- **{paper['title']}**：{paper['quality_summary']}；{paper['url']}")

    lines.extend(
        [
            "",
            "## 编辑观察",
            "",
            _editor_note(summary),
            "",
            "> 正式引用实验结论前，建议回到原文核对数据集、指标和实验设置。",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def build_html(summary: dict[str, Any], end_date: date) -> str:
    parts = [
        '<section style="max-width:677px;margin:0 auto;color:#24343a;font-family:-apple-system,BlinkMacSystemFont,Helvetica Neue,Arial,sans-serif;">',
        f'<h1 style="margin:0 0 14px;color:#10272f;font-size:24px;line-height:1.38;font-weight:800;">每周 GNSS/融合/SLAM 热点汇总 | {html.escape(end_date.isoformat())}</h1>',
        _paragraph(f"本周共聚合 {summary['paper_count']} 篇日报候选论文，覆盖日期：{', '.join(summary['source_dates'])}。"),
        _section_title("热点方向"),
        _ranked_cards(summary["hot_directions"]),
        _section_title("机器人领域热点雷达"),
        _ranked_cards(summary["hot_robotics_trends"]),
        _section_title("高频主题"),
        _ranked_cards(summary["hot_topics"]),
        _section_title("高频关键词"),
        _tag_line([term for term, _count in summary["hot_terms"][:14]]),
        _section_title("本周最值得追的论文"),
    ]
    for index, paper in enumerate(summary["top_papers"], start=1):
        parts.append(_paper_card(index, paper))
    if summary["code_papers"]:
        parts.extend([_section_title("有代码/复现线索"), _compact_paper_list(summary["code_papers"])])
    if summary["venue_papers"]:
        parts.extend([_section_title("有 venue / 引用线索"), _compact_paper_list(summary["venue_papers"])])
    parts.extend(
        [
            _section_title("编辑观察"),
            _callout(_editor_note(summary)),
            '<p style="margin:22px 0 0;color:#8a9da3;font-size:12px;line-height:1.8;">正式引用实验结论前，建议回到原文核对数据集、指标和实验设置。</p>',
            "</section>",
        ]
    )
    return "".join(parts)


def _paper_from_item(item: dict[str, Any], source_date: date) -> WeeklyPaper:
    return WeeklyPaper(
        title=str(item.get("title", "")),
        url=str(item.get("url", "")),
        published=str(item.get("published", ""))[:10],
        score=_float(item.get("score")),
        topic_scores={str(key): _float(value) for key, value in (item.get("topic_scores") or {}).items()},
        matched_terms=tuple(str(term) for term in item.get("matched_terms") or ()),
        quality_score=_float(item.get("quality_score")),
        quality_signals=item.get("quality_signals") if isinstance(item.get("quality_signals"), dict) else {},
        source_date=source_date,
    )


def _paper_to_json(paper: WeeklyPaper) -> dict[str, Any]:
    return {
        "title": paper.title,
        "url": paper.url,
        "published": paper.published,
        "score": paper.score,
        "quality_score": paper.quality_score,
        "quality_signals": paper.quality_signals,
        "quality_summary": _quality_summary(paper),
        "topics": list(paper.topic_scores.keys()),
        "matched_terms": list(paper.matched_terms),
        "source_date": paper.source_date.isoformat(),
    }


def _quality_summary(paper: WeeklyPaper) -> str:
    signals = paper.quality_signals
    parts = [f"质量分 {paper.quality_score:.1f}"]
    if isinstance(signals.get("citation_count"), int):
        parts.append(f"引用 {signals['citation_count']}")
    if isinstance(signals.get("influential_citation_count"), int) and signals["influential_citation_count"] > 0:
        parts.append(f"高影响引用 {signals['influential_citation_count']}")
    if signals.get("venue"):
        parts.append(f"venue {signals['venue']}")
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


def _directions_for(paper: WeeklyPaper) -> list[str]:
    terms = set(paper.matched_terms)
    directions = []
    gnss_platform_terms = {"gnss", "gps", "pnt", "receiver", "ais", "resilient pnt", "gnss denied", "osnma", "leo pnt"}
    gnss_risk_terms = {"spoofing", "jamming", "integrity", "interference", "attack", "anomaly", "c/n0", "agc"}
    if (gnss_platform_terms & terms) and (gnss_risk_terms & terms):
        directions.append("GNSS 完整性与欺骗/干扰检测")
    if {"fusion", "multi-sensor", "multimodal", "lidar", "visual", "inertial", "imu"} & terms:
        directions.append("多模态融合与传感器退化处理")
    if {"slam", "odometry", "mapping", "loop", "place recognition", "degeneracy"} & terms:
        directions.append("SLAM/里程计鲁棒性")
    if paper.quality_signals.get("code_url") or paper.quality_signals.get("code_signal"):
        directions.append("可复现代码与开源实现")
    if paper.quality_signals.get("dataset_signal"):
        directions.append("数据集与 benchmark")
    return directions or ["其他定位感知方向"]


def _robotics_trends_for(paper: WeeklyPaper) -> list[str]:
    text = _trend_text(paper)
    matches: list[tuple[str, float]] = []
    for topic in ROBOTICS_TREND_TOPICS:
        score = _trend_score(text, topic)
        if score >= _trend_threshold(topic) and _passes_trend_gate(text, topic):
            matches.append((topic.cn_name, score))
    matches.sort(key=lambda item: item[1], reverse=True)
    return [name for name, _score in matches[:3]]


def _trend_text(paper: WeeklyPaper) -> str:
    pieces = [
        paper.title,
        " ".join(paper.topic_scores.keys()),
        " ".join(paper.matched_terms),
        str(paper.quality_signals.get("venue") or ""),
    ]
    return " ".join(pieces).lower()


def _trend_score(text: str, topic: TopicProfile) -> float:
    score = 0.0
    for term, weight in topic.keywords.items():
        if _contains_term(text, term):
            score += weight
    return score


def _trend_threshold(topic: TopicProfile) -> float:
    if topic.name in {"embodied_nav_foundation_models", "robot_world_models", "humanoid_navigation", "robot_policy_learning"}:
        return 9.0
    return 8.0


def _passes_trend_gate(text: str, topic: TopicProfile) -> bool:
    if topic.name == "resilient_pnt_gnss_denied":
        platform_terms = ("gnss", "gps", "pnt", "receiver", "ais", "resilient pnt", "gnss denied", "osnma", "leo pnt")
        risk_terms = ("spoofing", "jamming", "integrity", "interference", "attack", "anomaly", "c/n0", "agc")
        return any(_contains_term(text, term) for term in platform_terms) and any(
            _contains_term(text, term) for term in risk_terms
        )
    return True


def _contains_term(text: str, term: str) -> bool:
    lowered = term.lower()
    if " " in lowered or "-" in lowered or "/" in lowered:
        return lowered in text
    return re.search(rf"\b{re.escape(lowered)}\b", text) is not None


def _editor_note(summary: dict[str, Any]) -> str:
    directions = [name for name, _count in summary["hot_directions"][:3]]
    robotics_trends = [name for name, _count in summary.get("hot_robotics_trends", [])[:3]]
    terms = [name for name, _count in summary["hot_terms"][:6]]
    direction_text = "、".join(directions) if directions else "GNSS/融合/SLAM 交叉方向"
    robotics_text = "、".join(robotics_trends) if robotics_trends else "机器人导航、定位与具身智能"
    term_text = "、".join(terms) if terms else "鲁棒定位、传感器融合、异常检测"
    return (
        f"本周最值得继续跟踪的是 {direction_text}。放到更宽的机器人领域看，{robotics_text} 的信号最强。"
        f"关键词上，{term_text} 出现频率较高；"
        "后续选题可以优先挑有代码、真实实验或明确 venue/引用信号的论文做深度解读。"
    )


def _deduplicate_weekly_papers(papers: list[WeeklyPaper]) -> list[WeeklyPaper]:
    best: dict[str, WeeklyPaper] = {}
    for paper in papers:
        key = _normalized_title(paper.title) or paper.url
        current = best.get(key)
        if current is None or (paper.quality_score, paper.score, paper.source_date) > (
            current.quality_score,
            current.score,
            current.source_date,
        ):
            best[key] = paper
    return list(best.values())


def _date_from_digest_filename(path: Path) -> date | None:
    prefix = path.name[:10]
    try:
        return date.fromisoformat(prefix)
    except ValueError:
        return None


def _normalized_title(title: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in title).split())


def _float(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _markdown_ranked(items: list[list[Any]] | list[tuple[Any, Any]]) -> list[str]:
    if not items:
        return ["- 暂无足够数据。"]
    return [f"{index}. {name}（{count}）" for index, (name, count) in enumerate(items, start=1)]


def _section_title(text: str) -> str:
    return (
        '<section style="margin:28px 0 14px;">'
        '<p style="margin:0 0 7px;width:42px;height:4px;background:#25d8b8;border-radius:2px;"></p>'
        f'<h2 style="margin:0;color:#122b34;font-size:21px;line-height:1.45;font-weight:800;">{html.escape(text)}</h2>'
        "</section>"
    )


def _paragraph(text: str) -> str:
    return f'<p style="margin:0 0 16px;color:#43565d;font-size:15px;line-height:1.9;">{html.escape(text)}</p>'


def _ranked_cards(items: list[list[Any]] | list[tuple[Any, Any]]) -> str:
    if not items:
        return _paragraph("暂无足够数据。")
    cards = []
    for index, (name, count) in enumerate(items, start=1):
        cards.append(
            '<section style="margin:0 0 10px;padding:13px 14px;background:#f7fbfb;'
            'border:1px solid #e0eeee;border-radius:8px;">'
            f'<p style="margin:0;color:#40545c;font-size:14px;line-height:1.85;"><strong style="color:#0b9984;">{index}.</strong> {html.escape(str(name))} <span style="color:#8a9da3;">({html.escape(str(count))})</span></p>'
            "</section>"
        )
    return "".join(cards)


def _paper_card(index: int, paper: dict[str, Any]) -> str:
    return (
        '<section style="margin:0 0 18px;padding:16px;border:1px solid #dce9eb;border-radius:8px;background:#ffffff;">'
        f'<p style="margin:0 0 8px;color:#0b9984;font-size:13px;font-weight:700;">{index:02d} · {html.escape(str(paper["published"]))}</p>'
        f'<h3 style="margin:0 0 10px;color:#10272f;font-size:17px;line-height:1.5;">{html.escape(str(paper["title"]))}</h3>'
        f'<p style="margin:0 0 10px;color:#40545c;font-size:14px;line-height:1.8;">{html.escape(str(paper["quality_summary"]))}</p>'
        f'<p style="margin:0;font-size:14px;line-height:1.8;">原文：<a href="{html.escape(str(paper["url"]))}" style="color:#0b9984;text-decoration:none;">{html.escape(str(paper["url"]))}</a></p>'
        "</section>"
    )


def _compact_paper_list(papers: list[dict[str, Any]]) -> str:
    return "".join(
        '<section style="margin:0 0 10px;padding:12px 13px;background:#f7fbfb;border:1px solid #e0eeee;border-radius:8px;">'
        f'<p style="margin:0 0 4px;color:#17272d;font-size:14px;line-height:1.65;font-weight:700;">{html.escape(str(paper["title"]))}</p>'
        f'<p style="margin:0;color:#51676f;font-size:13px;line-height:1.7;">{html.escape(str(paper["quality_summary"]))}</p>'
        "</section>"
        for paper in papers
    )


def _tag_line(tags: list[str]) -> str:
    return "".join(
        f'<span style="display:inline-block;margin:0 8px 8px 0;padding:5px 9px;'
        f'border-radius:14px;background:#eef8f7;color:#0b8275;font-size:12px;">{html.escape(tag)}</span>'
        for tag in tags
    )


def _callout(text: str) -> str:
    return (
        '<section style="margin:0 0 18px;padding:16px;background:#f4fbf9;'
        'border-left:4px solid #25d8b8;color:#34484f;font-size:15px;line-height:1.9;">'
        f"{html.escape(text)}"
        "</section>"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate weekly hot-topic summaries from daily digest JSON files.")
    parser.add_argument("--input-dir", type=Path, default=Path(os.getenv("DIGEST_OUTPUT_DIR", "outputs")))
    parser.add_argument("--output-dir", type=Path, default=Path(os.getenv("WEEKLY_OUTPUT_DIR", "outputs/weekly")))
    parser.add_argument("--end-date")
    parser.add_argument("--days", type=int, default=int(os.getenv("WEEKLY_SUMMARY_DAYS", "7")))
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
