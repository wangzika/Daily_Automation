from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from daily_gnss_slam_digest.article import build_html, build_markdown
from daily_gnss_slam_digest.cli import (
    _rerank_loaded_recommendations,
    _upload_daily_theme_thumb,
    _wechat_daily_theme_cover_enabled,
)
from daily_gnss_slam_digest.config import ROTATING_TOPICS, rotating_topic_for_date
from daily_gnss_slam_digest.models import Paper, RecommendedPaper
from daily_gnss_slam_digest.recommender import recommend
from daily_gnss_slam_digest.sample_data import SAMPLE_PAPERS
from daily_gnss_slam_digest.wechat import WeChatPublisherError


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

    def test_tomorrow_keywords_use_next_rotation_topic(self) -> None:
        ranked = recommend(
            SAMPLE_PAPERS,
            limit=3,
            days_back=800,
            now=datetime(2026, 7, 6, tzinfo=timezone.utc),
        )
        monday_topic = rotating_topic_for_date(date(2026, 7, 6))
        tuesday_topic = rotating_topic_for_date(date(2026, 7, 7))

        markdown = build_markdown(
            ranked,
            date(2026, 7, 6),
            focus_topic=monday_topic.cn_name,
            next_focus_topic=tuesday_topic.cn_name,
        )
        html = build_html(
            ranked,
            date(2026, 7, 6),
            focus_topic=monday_topic.cn_name,
            next_focus_topic=tuesday_topic.cn_name,
        )

        self.assertIn("今天这期看 **具身导航与机器人基础模型**", markdown)
        self.assertIn("`Gaussian Splatting SLAM`", markdown)
        self.assertIn("`3D Gaussian Splatting mapping`", markdown)
        self.assertNotIn("`embodied navigation`", markdown)
        self.assertIn("Gaussian Splatting SLAM", html)
        self.assertIn("3D Gaussian Splatting mapping", html)

    def test_from_json_rerender_keeps_only_current_topic_matches(self) -> None:
        published = datetime(2026, 7, 4, tzinfo=timezone.utc)
        loaded = [
            _recommendation(
                "GNSS Jamming Detection with AGC and CNO Observables",
                "This work detects GNSS jamming and interference with receiver integrity signals.",
                published,
            ),
            _recommendation(
                "LiDAR Visual Inertial SLAM for Dense Mapping",
                "This work studies SLAM, odometry, LiDAR, visual and inertial fusion.",
                published,
            ),
        ]
        pnt_topic = rotating_topic_for_date(date(2026, 7, 4))

        reranked = _rerank_loaded_recommendations(
            loaded,
            limit=5,
            days_back=30,
            topics=(pnt_topic,),
            issue_date=date(2026, 7, 4),
        )

        self.assertEqual([item.paper.title for item in reranked], ["GNSS Jamming Detection with AGC and CNO Observables"])

    def test_daily_theme_cover_is_enabled_by_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertTrue(_wechat_daily_theme_cover_enabled())
        with patch.dict("os.environ", {"WECHAT_DAILY_THEME_COVER": "0"}, clear=True):
            self.assertFalse(_wechat_daily_theme_cover_enabled())

    def test_daily_theme_cover_upload_uses_topic_header_media_id(self) -> None:
        publisher = _FakePublisher(thumb_media_id="fixed-thumb", upload_result={"media_id": "theme-thumb"})

        media_id = _upload_daily_theme_thumb(publisher, "token", {"header": Path("topic-header.jpg")})

        self.assertEqual(media_id, "theme-thumb")
        self.assertEqual(publisher.uploaded_paths, [Path("topic-header.jpg")])

    def test_daily_theme_cover_falls_back_to_static_thumb_on_upload_error(self) -> None:
        publisher = _FakePublisher(thumb_media_id="fixed-thumb", upload_error=WeChatPublisherError("blocked"))

        media_id = _upload_daily_theme_thumb(publisher, "token", {"header": Path("topic-header.jpg")})

        self.assertIsNone(media_id)
        self.assertEqual(publisher.uploaded_paths, [Path("topic-header.jpg")])

    def test_daily_theme_cover_requires_some_thumb_when_upload_fails(self) -> None:
        publisher = _FakePublisher(thumb_media_id="", upload_error=WeChatPublisherError("blocked"))

        with self.assertRaisesRegex(WeChatPublisherError, "WECHAT_THUMB_MEDIA_ID"):
            _upload_daily_theme_thumb(publisher, "token", {"header": Path("topic-header.jpg")})


def _recommendation(title: str, abstract: str, published: datetime) -> RecommendedPaper:
    return RecommendedPaper(
        paper=Paper(
            title=title,
            authors=("A. Author",),
            abstract=abstract,
            url="https://arxiv.org/abs/test",
            pdf_url=None,
            published=published,
            updated=published,
            categories=("cs.RO",),
            primary_category="cs.RO",
        ),
        score=0.0,
    )


class _FakePublisher:
    def __init__(
        self,
        thumb_media_id: str,
        upload_result: dict[str, str] | None = None,
        upload_error: WeChatPublisherError | None = None,
    ) -> None:
        self.config = SimpleNamespace(thumb_media_id=thumb_media_id)
        self.upload_result = upload_result or {}
        self.upload_error = upload_error
        self.uploaded_paths: list[Path] = []

    def upload_permanent_image(self, access_token: str, image_path: Path) -> dict[str, str]:
        self.uploaded_paths.append(image_path)
        if self.upload_error:
            raise self.upload_error
        return self.upload_result


if __name__ == "__main__":
    unittest.main()
