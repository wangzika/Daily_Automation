from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from daily_gnss_slam_digest.weekly import build_weekly_summary, load_weekly_papers, write_weekly_outputs


class WeeklySummaryTest(unittest.TestCase):
    def test_loads_daily_json_and_builds_hot_topics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp)
            _write_daily_json(input_dir / "2026-07-03-gnss-slam-digest.json")

            papers = load_weekly_papers(input_dir, end_date=date(2026, 7, 3), days=7)
            summary = build_weekly_summary(papers)
            paths = write_weekly_outputs(papers, end_date=date(2026, 7, 3), output_dir=input_dir / "weekly")

        self.assertEqual(len(papers), 2)
        self.assertEqual(summary["paper_count"], 2)
        self.assertTrue(summary["hot_directions"])
        self.assertTrue(summary["hot_robotics_trends"])
        self.assertTrue(summary["code_papers"])
        self.assertTrue(paths["markdown"].name.endswith("gnss-slam-weekly.md"))


def _write_daily_json(path: Path) -> None:
    payload = [
        {
            "title": "GNSS Spoofing Detection with Open Benchmark",
            "url": "https://arxiv.org/abs/2601.00001",
            "published": "2026-07-01T00:00:00+00:00",
            "score": 42.0,
            "topic_scores": {"GNSS 欺骗与干扰检测": 31.0},
            "matched_terms": ["gnss", "spoofing", "detection", "benchmark"],
            "quality_score": 12.5,
            "quality_signals": {
                "citation_count": 8,
                "code_url": "https://github.com/example/gnss",
                "dataset_signal": True,
            },
        },
        {
            "title": "Robust LiDAR Inertial SLAM",
            "url": "https://arxiv.org/abs/2601.00002",
            "published": "2026-07-02T00:00:00+00:00",
            "score": 38.0,
            "topic_scores": {"SLAM 与鲁棒里程计": 28.0},
            "matched_terms": ["slam", "odometry", "lidar", "inertial"],
            "quality_score": 8.0,
            "quality_signals": {"venue": "ICRA"},
        },
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
