from __future__ import annotations

import unittest
from datetime import date, timedelta

from daily_gnss_slam_digest.config import ROTATING_TOPICS, rotating_topic_for_date


class TopicRotationTest(unittest.TestCase):
    def test_seven_day_rotation_has_distinct_topics(self) -> None:
        monday = date(2026, 7, 6)
        topics = [rotating_topic_for_date(monday + timedelta(days=offset)) for offset in range(7)]

        self.assertEqual(len(ROTATING_TOPICS), 7)
        self.assertEqual(len({topic.name for topic in topics}), 7)
        self.assertEqual(rotating_topic_for_date(monday + timedelta(days=7)).name, topics[0].name)


if __name__ == "__main__":
    unittest.main()
