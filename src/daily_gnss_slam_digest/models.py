from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Paper:
    title: str
    authors: tuple[str, ...]
    abstract: str
    url: str
    pdf_url: str | None
    published: datetime
    updated: datetime
    categories: tuple[str, ...] = ()
    primary_category: str | None = None
    arxiv_id: str | None = None


@dataclass
class RecommendedPaper:
    paper: Paper
    score: float
    topic_scores: dict[str, float] = field(default_factory=dict)
    matched_terms: tuple[str, ...] = ()
    reason: str = ""
