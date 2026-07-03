from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from .config import TOPICS, TopicProfile
from .models import Paper, RecommendedPaper


TOP_VENUE_PATTERNS: tuple[tuple[str, float], ...] = (
    ("IEEE Transactions on Robotics", 9.0),
    ("T-RO", 9.0),
    ("TRO", 9.0),
    ("Robotics: Science and Systems", 8.0),
    ("RSS", 8.0),
    ("ICRA", 7.5),
    ("IROS", 7.0),
    ("RA-L", 7.0),
    ("Robotics and Automation Letters", 7.0),
    ("CVPR", 7.0),
    ("ICCV", 7.0),
    ("ECCV", 6.5),
    ("NeurIPS", 6.5),
    ("ICML", 6.5),
    ("ION GNSS", 7.0),
    ("IEEE/ION PLANS", 7.0),
    ("PLANS", 6.5),
    ("NAVIGATION", 6.0),
    ("ITSC", 5.5),
    ("Intelligent Vehicles", 5.5),
    ("IEEE Transactions on Intelligent Transportation Systems", 6.0),
    ("IEEE Transactions on Intelligent Vehicles", 6.0),
)

CODE_URL_RE = re.compile(r"https?://(?:www\.)?(?:github\.com|gitlab\.com|bitbucket\.org|code\.ocean)/[^\s),.;]+", re.I)


def recommend(
    papers: list[Paper],
    limit: int,
    days_back: int,
    now: datetime | None = None,
) -> list[RecommendedPaper]:
    now = now or datetime.now(timezone.utc)
    recent = [paper for paper in papers if _age_days(paper, now) <= days_back]
    candidates = _deduplicate_papers(recent or papers)
    ranked = [_score_paper(paper, now) for paper in candidates]
    ranked.sort(key=lambda item: (item.score, item.paper.published), reverse=True)

    selected: list[RecommendedPaper] = []
    selected_ids: set[str] = set()

    for topic in TOPICS:
        topic_candidates = [
            item
            for item in ranked
            if item.topic_scores.get(topic.cn_name, 0.0) > 0
            and _paper_key(item.paper) not in selected_ids
        ]
        topic_candidates.sort(
            key=lambda item: (
                item.topic_scores.get(topic.cn_name, 0.0),
                item.score,
                item.paper.published,
            ),
            reverse=True,
        )
        if topic_candidates and len(selected) < limit:
            selected.append(topic_candidates[0])
            selected_ids.add(_paper_key(topic_candidates[0].paper))

    for item in ranked:
        if len(selected) >= limit:
            break
        key = _paper_key(item.paper)
        if key not in selected_ids:
            selected.append(item)
            selected_ids.add(key)

    return selected


def _score_paper(paper: Paper, now: datetime) -> RecommendedPaper:
    haystack = f"{paper.title} {paper.abstract}".lower()
    topic_scores: dict[str, float] = {}
    matched_terms: list[str] = []

    for topic in TOPICS:
        score, terms = _score_topic(haystack, topic)
        if score:
            topic_scores[topic.cn_name] = score
            matched_terms.extend(terms)

    age = max(_age_days(paper, now), 0.0)
    recency_bonus = 16.0 * math.exp(-age / 60.0)
    diversity_bonus = min(len(topic_scores), 3) * 2.5
    quality_score, quality_signals = _score_quality(paper)
    score = sum(topic_scores.values()) + recency_bonus + diversity_bonus + quality_score

    terms_tuple = tuple(dict.fromkeys(matched_terms))
    return RecommendedPaper(
        paper=paper,
        score=round(score, 2),
        topic_scores=topic_scores,
        matched_terms=terms_tuple,
        quality_score=round(quality_score, 2),
        quality_signals=quality_signals,
        reason=_build_reason(topic_scores, terms_tuple, quality_signals),
    )


def _score_topic(haystack: str, topic: TopicProfile) -> tuple[float, list[str]]:
    score = 0.0
    matched_terms: list[str] = []
    for term, weight in topic.keywords.items():
        if _contains_term(haystack, term):
            score += weight
            matched_terms.append(term)
    if not _passes_topic_gate(topic, matched_terms, score):
        return 0.0, []
    return score, matched_terms


def _passes_topic_gate(topic: TopicProfile, matched_terms: list[str], score: float) -> bool:
    terms = set(matched_terms)
    if topic.name == "gnss_security":
        platform_terms = {"gnss", "gps", "pnt", "receiver", "ais"}
        security_terms = {"spoofing", "jamming", "interference", "integrity", "attack", "anomaly"}
        return bool(terms & platform_terms) and bool(terms & security_terms) and score >= 12.0
    if topic.name == "multimodal_fusion":
        return score >= 10.0
    if topic.name == "slam_odometry":
        return score >= 9.0
    return score > 0


def _contains_term(haystack: str, term: str) -> bool:
    escaped = re.escape(term.lower())
    if " " in term or "-" in term:
        return term.lower() in haystack
    return re.search(rf"\b{escaped}\b", haystack) is not None


def _age_days(paper: Paper, now: datetime) -> float:
    published = paper.published
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return (now - published).total_seconds() / 86400


def _paper_key(paper: Paper) -> str:
    return paper.arxiv_id or _normalized_title(paper.title) or paper.url


def _build_reason(
    topic_scores: dict[str, float],
    terms: tuple[str, ...],
    quality_signals: dict[str, Any],
) -> str:
    topic_names = "、".join(topic_scores.keys()) if topic_scores else "相关方向"
    visible_terms = "、".join(terms[:8]) if terms else "方法和实验设置"
    quality = _quality_reason(quality_signals)
    return f"主题贴合 {topic_names}，关键词集中在 {visible_terms}。{quality}，适合作为今日跟踪论文。"


def _quality_reason(signals: dict[str, Any]) -> str:
    parts: list[str] = []
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
        parts.append("有数据集/benchmark 线索")
    if signals.get("real_world_signal"):
        parts.append("强调真实实验")
    if not parts:
        return "质量信号以主题相关和新近度为主"
    return "质量信号：" + "、".join(parts[:5])


def _score_quality(paper: Paper) -> tuple[float, dict[str, Any]]:
    text = _metadata_text(paper)
    signals: dict[str, Any] = {}
    score = 0.0

    if paper.citation_count is not None:
        signals["citation_count"] = paper.citation_count
        score += min(math.log1p(max(paper.citation_count, 0)) * 2.3, 12.0)
    if paper.influential_citation_count is not None:
        signals["influential_citation_count"] = paper.influential_citation_count
        score += min(math.log1p(max(paper.influential_citation_count, 0)) * 2.0, 6.0)

    venue = paper.venue or paper.journal_ref or _venue_from_text(text)
    venue_bonus = _venue_bonus(venue or text)
    if venue:
        signals["venue"] = _compact_signal_text(venue)
    if venue_bonus:
        signals["venue_bonus"] = round(venue_bonus, 2)
        score += venue_bonus

    code_url = paper.code_url or _code_url(text)
    if code_url:
        signals["code_url"] = code_url
        score += 6.0
    elif _has_code_signal(text):
        signals["code_signal"] = True
        score += 3.0

    if _has_dataset_signal(text):
        signals["dataset_signal"] = True
        score += 2.5
    if _has_real_world_signal(text):
        signals["real_world_signal"] = True
        score += 2.0
    if _is_survey(text):
        signals["survey_penalty"] = True
        score -= 3.0

    return max(score, -4.0), signals


def _metadata_text(paper: Paper) -> str:
    return " ".join(
        part
        for part in (
            paper.title,
            paper.abstract,
            paper.comment or "",
            paper.journal_ref or "",
            paper.venue or "",
        )
        if part
    )


def _venue_from_text(text: str) -> str | None:
    for pattern, _weight in TOP_VENUE_PATTERNS:
        if re.search(rf"\b{re.escape(pattern)}\b", text, flags=re.I):
            return pattern
    return None


def _venue_bonus(text: str) -> float:
    for pattern, weight in TOP_VENUE_PATTERNS:
        if re.search(rf"\b{re.escape(pattern)}\b", text, flags=re.I):
            return weight
    return 0.0


def _code_url(text: str) -> str | None:
    match = CODE_URL_RE.search(text)
    if not match:
        return None
    return match.group(0).rstrip("/")


def _has_code_signal(text: str) -> bool:
    return bool(re.search(r"\b(code|implementation|repository|github|open-source|open source)\b", text, flags=re.I))


def _has_dataset_signal(text: str) -> bool:
    return bool(re.search(r"\b(dataset|benchmark|leaderboard|real-world data|open dataset)\b", text, flags=re.I))


def _has_real_world_signal(text: str) -> bool:
    return bool(re.search(r"\b(real-world|field experiment|field test|outdoor experiment|vehicle|uav|robot platform)\b", text, flags=re.I))


def _is_survey(text: str) -> bool:
    return bool(re.search(r"\b(survey|review|benchmarking study)\b", text, flags=re.I))


def _compact_signal_text(value: str) -> str:
    return " ".join(value.split())[:80]


def _deduplicate_papers(papers: list[Paper]) -> list[Paper]:
    selected: list[Paper] = []
    key_to_index: dict[str, int] = {}
    for paper in papers:
        keys = [key for key in _paper_keys(paper) if key]
        existing_index = next((key_to_index[key] for key in keys if key in key_to_index), None)
        if existing_index is None:
            key_to_index.update({key: len(selected) for key in keys})
            selected.append(paper)
            continue

        current = selected[existing_index]
        if _duplicate_preference(paper) > _duplicate_preference(current):
            selected[existing_index] = paper
            key_to_index.update({key: existing_index for key in keys})
    return selected


def _paper_keys(paper: Paper) -> tuple[str, ...]:
    keys = []
    if paper.arxiv_id:
        keys.append(f"arxiv:{paper.arxiv_id.lower()}")
    normalized = _normalized_title(paper.title)
    if normalized:
        keys.append(f"title:{normalized}")
    return tuple(keys)


def _normalized_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _duplicate_preference(paper: Paper) -> tuple[int, datetime, datetime]:
    metadata_count = sum(
        1
        for value in (
            paper.comment,
            paper.journal_ref,
            paper.doi,
            paper.citation_count,
            paper.venue,
            paper.code_url,
        )
        if value
    )
    return metadata_count, paper.updated, paper.published
