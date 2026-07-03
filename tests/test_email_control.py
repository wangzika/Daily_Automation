from __future__ import annotations

import unittest
from email.message import EmailMessage
from pathlib import Path

from daily_gnss_slam_digest.config import arxiv_query_from_keywords, parse_keyword_text, topic_from_keywords
from daily_gnss_slam_digest.email_control import (
    EmailCommandConfig,
    _deepdive_command,
    _newest_message_ids,
    command_from_message,
)
from daily_gnss_slam_digest.models import Paper
from daily_gnss_slam_digest.recommender import recommend

from datetime import datetime, timezone


class KeywordCommandTest(unittest.TestCase):
    def test_keyword_text_builds_arxiv_query(self) -> None:
        keywords = parse_keyword_text("GNSS jamming, robust localization；visual inertial SLAM")

        self.assertEqual(keywords, ("GNSS jamming", "robust localization", "visual inertial SLAM"))
        self.assertEqual(
            arxiv_query_from_keywords(keywords),
            '(all:"GNSS jamming" OR all:"robust localization" OR all:"visual inertial SLAM")',
        )

    def test_custom_keywords_participate_in_recommendation(self) -> None:
        now = datetime(2026, 7, 3, tzinfo=timezone.utc)
        topic = topic_from_keywords(("neural implicit slam",))
        ranked = recommend(
            [
                _paper("A Survey of Robotics", "This paper surveys robotics."),
                _paper("Neural Implicit SLAM for Large-Scale Mapping", "We propose neural implicit SLAM."),
            ],
            limit=1,
            days_back=30,
            now=now,
            topics=(topic,),
        )

        self.assertEqual(ranked[0].paper.title, "Neural Implicit SLAM for Large-Scale Mapping")
        self.assertIn("邮件指定关键词", ranked[0].topic_scores)

    def test_email_message_parses_to_command(self) -> None:
        message = EmailMessage()
        message["From"] = "reader@qq.com"
        message["Subject"] = "论文指令：GNSS 干扰"
        message.set_content(
            "\n".join(
                [
                    "关键词：GNSS jamming, spoofing detection",
                    "任务：digest, deepdive",
                    "模式：draft",
                    "数量：4",
                    "解读数量：2",
                ]
            )
        )
        config = EmailCommandConfig(
            imap_host="imap.qq.com",
            imap_port=993,
            username="reader@qq.com",
            password="auth",
            folder="INBOX",
            allowed_senders=("reader@qq.com",),
            subject_keyword="论文指令",
            max_messages=5,
            mark_seen=True,
            default_mode="draft",
            default_tasks=("digest", "deepdive"),
        )

        command = command_from_message(message, config)

        self.assertIsNotNone(command)
        assert command is not None
        self.assertEqual(command.keywords, "GNSS jamming, spoofing detection")
        self.assertEqual(command.tasks, ("digest", "deepdive"))
        self.assertEqual(command.mode, "draft")
        self.assertEqual(command.digest_limit, 4)
        self.assertEqual(command.deepdive_limit, 2)

    def test_newest_unread_messages_are_checked_first(self) -> None:
        ids = [b"1", b"2", b"3", b"4", b"5", b"6"]

        self.assertEqual(_newest_message_ids(ids, 3), [b"6", b"5", b"4"])

    def test_deepdive_command_honors_email_limit(self) -> None:
        command = PaperCommandForTest(deepdive_limit=1)

        args = _deepdive_command(command, Path("digest.json"), Path("run"), "python", {"DEEPDIVE_LIMIT": "3"})

        limit_index = args.index("--limit")
        self.assertEqual(args[limit_index + 1], "1")


def _paper(title: str, abstract: str) -> Paper:
    published = datetime(2026, 7, 3, tzinfo=timezone.utc)
    return Paper(
        title=title,
        authors=("A. Author",),
        abstract=abstract,
        url=f"https://arxiv.org/abs/{title}",
        pdf_url=None,
        published=published,
        updated=published,
        categories=("cs.RO",),
        primary_category="cs.RO",
    )


class PaperCommandForTest:
    keywords = "GNSS jamming"
    tasks = ("digest", "deepdive")
    mode = "draft"
    digest_limit = 3
    days_back = 180
    source_subject = "论文指令"
    source_sender = "reader@qq.com"

    def __init__(self, *, deepdive_limit: int | None) -> None:
        self.deepdive_limit = deepdive_limit


if __name__ == "__main__":
    unittest.main()
