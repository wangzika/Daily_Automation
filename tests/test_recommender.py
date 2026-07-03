from __future__ import annotations

import unittest
from datetime import datetime, timezone

from daily_gnss_slam_digest.models import Paper
from daily_gnss_slam_digest.recommender import recommend
from daily_gnss_slam_digest.sample_data import SAMPLE_PAPERS


class RecommenderTest(unittest.TestCase):
    def test_scores_relevant_papers(self) -> None:
        ranked = recommend(
            SAMPLE_PAPERS,
            limit=3,
            days_back=800,
            now=datetime(2026, 7, 3, tzinfo=timezone.utc),
        )

        self.assertEqual(len(ranked), 3)
        self.assertTrue(all(item.matched_terms for item in ranked))
        covered_topics = {topic for item in ranked for topic in item.topic_scores}
        self.assertIn("GNSS 欺骗与干扰检测", covered_topics)
        self.assertIn("多模态/多传感器融合", covered_topics)
        self.assertIn("SLAM 与鲁棒里程计", covered_topics)

    def test_deduplicates_by_normalized_title(self) -> None:
        now = datetime(2026, 7, 3, tzinfo=timezone.utc)
        first = _paper(
            title="Robust GNSS Spoofing Detection for Receiver Integrity",
            arxiv_id="2601.00001",
            published=now,
        )
        duplicate = _paper(
            title="Robust GNSS Spoofing Detection: For Receiver Integrity!",
            arxiv_id=None,
            published=now,
            citation_count=12,
        )

        ranked = recommend([first, duplicate], limit=5, days_back=30, now=now)

        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].paper.citation_count, 12)

    def test_quality_signals_boost_code_venue_and_citations(self) -> None:
        now = datetime(2026, 7, 3, tzinfo=timezone.utc)
        basic = _paper(
            title="GNSS Spoofing Detection with Receiver Anomaly Monitoring",
            arxiv_id="2601.00002",
            published=now,
        )
        high_quality = _paper(
            title="GNSS Spoofing Detection with Open Benchmark and Field Experiment",
            arxiv_id="2601.00003",
            published=now,
            abstract_suffix="Code is available at https://github.com/example/gnss-spoofing and includes a real-world benchmark dataset.",
            citation_count=24,
            venue="ION GNSS+",
        )

        ranked = recommend([basic, high_quality], limit=2, days_back=30, now=now)

        self.assertEqual(ranked[0].paper.arxiv_id, "2601.00003")
        self.assertGreater(ranked[0].quality_score, ranked[1].quality_score)
        self.assertIn("code_url", ranked[0].quality_signals)


def _paper(
    *,
    title: str,
    arxiv_id: str | None,
    published: datetime,
    abstract_suffix: str = "",
    citation_count: int | None = None,
    venue: str | None = None,
) -> Paper:
    abstract = (
        "This paper studies GNSS spoofing detection and receiver integrity "
        "with anomaly detection for robust positioning. "
        + abstract_suffix
    )
    return Paper(
        title=title,
        authors=("A. Author",),
        abstract=abstract,
        url=f"https://arxiv.org/abs/{arxiv_id or title}",
        pdf_url=None,
        published=published,
        updated=published,
        categories=("eess.SP",),
        primary_category="eess.SP",
        arxiv_id=arxiv_id,
        citation_count=citation_count,
        venue=venue,
    )


if __name__ == "__main__":
    unittest.main()
