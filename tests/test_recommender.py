from __future__ import annotations

import unittest
from datetime import datetime, timezone

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


if __name__ == "__main__":
    unittest.main()
