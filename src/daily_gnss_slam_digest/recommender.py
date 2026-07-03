from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from .config import TOPICS, TopicProfile
from .models import Paper, RecommendedPaper


def recommend(
    papers: list[Paper],
    limit: int,
    days_back: int,
    now: datetime | None = None,
) -> list[RecommendedPaper]:
    now = now or datetime.now(timezone.utc)
    recent = [paper for paper in papers if _age_days(paper, now) <= days_back]
    candidates = recent or papers
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
    score = sum(topic_scores.values()) + recency_bonus + diversity_bonus

    terms_tuple = tuple(dict.fromkeys(matched_terms))
    return RecommendedPaper(
        paper=paper,
        score=round(score, 2),
        topic_scores=topic_scores,
        matched_terms=terms_tuple,
        reason=_build_reason(topic_scores, terms_tuple),
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


def _build_reason(topic_scores: dict[str, float], terms: tuple[str, ...]) -> str:
    topic_names = "、".join(topic_scores.keys()) if topic_scores else "相关方向"
    visible_terms = "、".join(terms[:8]) if terms else "方法和实验设置"
    return f"主题贴合 {topic_names}，关键词集中在 {visible_terms}，适合作为今日跟踪论文。"


def _paper_key(paper: Paper) -> str:
    return paper.arxiv_id or paper.url
