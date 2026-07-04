from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from daily_gnss_slam_digest.article import build_html, build_markdown
from daily_gnss_slam_digest.config import ROTATING_TOPICS, rotating_topic_for_date
from daily_gnss_slam_digest.recommender import recommend
from daily_gnss_slam_digest.sample_data import SAMPLE_PAPERS


class TopicRotationTest(unittest.TestCase):
    def test_seven_day_rotation_has_distinct_topics(self) -> None:
        monday = date(2026, 7, 6)
        topics = [rotating_topic_for_date(monday + timedelta(days=offset)) for offset in range(7)]

        self.assertEqual(len(ROTATING_TOPICS), 7)
        self.assertEqual(len({topic.name for topic in topics}), 7)
        self.assertEqual(rotating_topic_for_date(monday + timedelta(days=7)).name, topics[0].name)

    def test_digest_uses_topic_header_without_process_language(self) -> None:
        ranked = recommend(
            SAMPLE_PAPERS,
            limit=3,
            days_back=800,
            now=datetime(2026, 7, 4, tzinfo=timezone.utc),
        )

        markdown = build_markdown(
            ranked,
            date(2026, 7, 4),
            image_paths={"header": "topic-header.jpg"},
            focus_topic="韧性 PNT 与 GNSS 抗欺骗抗干扰",
        )
        html = build_html(
            ranked,
            date(2026, 7, 4),
            image_urls={"header": "topic-header.jpg"},
            focus_topic="韧性 PNT 与 GNSS 抗欺骗抗干扰",
        )

        self.assertIn("topic-header.jpg", markdown)
        self.assertIn("topic-header.jpg", html)
        self.assertNotIn("筛选方法论", markdown)
        self.assertNotIn("筛选方法论", html)
        self.assertNotIn("基于公开论文元数据生成", markdown)
        self.assertNotIn("基于公开论文元数据生成", html)


if __name__ == "__main__":
    unittest.main()
