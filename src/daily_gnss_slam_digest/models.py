from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


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
    comment: str | None = None
    journal_ref: str | None = None
    doi: str | None = None
    citation_count: int | None = None
    influential_citation_count: int | None = None
    venue: str | None = None
    code_url: str | None = None


@dataclass
class RecommendedPaper:
    paper: Paper
    score: float
    topic_scores: dict[str, float] = field(default_factory=dict)
    matched_terms: tuple[str, ...] = ()
    quality_score: float = 0.0
    quality_signals: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
