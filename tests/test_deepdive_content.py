from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from PIL import Image

from daily_gnss_slam_digest.deepdive import (
    DeepDiveFigure,
    PaperReading,
    TextPolishResult,
    _content_mode_label,
    _display_figure_caption,
    _draft_source_lines,
    _extract_base64_image,
    _figure_reading,
    _file_url,
    _image_variants,
    _prepare_article_figures,
    build_deepdive_html,
    build_deepdive_markdown,
)


class DeepDiveContentTest(unittest.TestCase):
    def test_deepdive_uses_current_paper_evidence_without_old_case_copy(self) -> None:
        paper = {
            "title": "GNSS Spoofing Threat for V2X communications",
            "authors": ["A. Reader", "B. Writer"],
            "abstract": (
                "Global Navigation Satellite Systems constitute a core technology for Vehicle-to-Everything services. "
                "This work presents a methodology for conducting physical spoofing with inexpensive Software Defined Radio. "
                "The proposed attack is experimentally validated on Commsignia OBU and RSU devices using a HackRF One. "
                "The contribution is the demonstration that V2X communications are susceptible to GNSS spoofing attacks."
            ),
            "published": "2026-06-18T13:30:04+00:00",
            "url": "http://arxiv.org/abs/2606.20215v1",
            "matched_terms": ["gnss", "spoofing", "v2x"],
            "quality_signals": {"real_world_signal": True},
        }
        reading = PaperReading(
            abstract=str(paper["abstract"]),
            introduction=(
                "Vehicle-to-Everything systems rely on GNSS positions to generate cooperative awareness messages. "
                "Spoofing is an advanced attack that misleads the receiver into computing a false position."
            ),
            method=(
                "This work presents a coordinate generation pipeline with Haversine distance calculations, temporal discretization, "
                "linear interpolation, and GPS baseband signal generation with SDR hardware."
            ),
            experiments=(
                "The attack is experimentally validated on real Commsignia OnBoard Unit and RoadSide Unit devices using a HackRF One "
                "across three scenarios at 90 km/h, 145 km/h, and 200 km/h."
            ),
            conclusion="The demonstration shows service degradation without being detected by the V2X devices.",
            captions=("Fig. 1. Spoofing attack setup with SDR, OBU, RSU, and synthetic trajectory.",),
        )
        figures = [DeepDiveFigure(Path("figure-1.jpg"), reading.captions[0])]

        markdown = build_deepdive_markdown(paper, reading, figures, {"figure_1": "figure-1.jpg"})
        html = build_deepdive_html(paper, reading, figures, {"figure_1": "figure-1.jpg"})

        for text in (markdown, html):
            self.assertIn("HackRF One", text)
            self.assertIn("V2X", text)
            self.assertIn("90 km/h", text)
            self.assertNotIn("LXD-SLAM 盯住", text)
            self.assertNotIn("Septentrio AsteRx", text)
            self.assertNotIn("KITTI Sequence", text)
            self.assertNotIn("引言部分", text)
            self.assertNotIn("通常", text)
            self.assertNotIn("一般", text)

    def test_ai_figure_is_labeled_as_auxiliary_illustration(self) -> None:
        paper = {
            "title": "GNSS Timing Spoofing Protection Level",
            "authors": ["A. Reader"],
            "abstract": "This paper studies timing spoofing protection levels for GNSS receivers.",
            "published": "2026-07-01T00:00:00+00:00",
            "url": "http://arxiv.org/abs/2607.00001v1",
            "matched_terms": ["gnss", "timing", "spoofing"],
        }
        reading = PaperReading(
            abstract=str(paper["abstract"]),
            introduction="GNSS timing users need a bound on undetected spoofing.",
            method="The method builds a timing protection level from receiver observables.",
            experiments="The evaluation uses recorded spoofing data and timing error metrics.",
            conclusion="The protection level gives a conservative timing-risk budget.",
            captions=(),
        )
        figures = [DeepDiveFigure(Path("ai-cover.jpg"), "授时欺骗与保护级的概念示意", source="ai")]

        markdown = build_deepdive_markdown(paper, reading, figures, {"figure_1": "ai-cover.jpg"})
        html = build_deepdive_html(paper, reading, figures, {"figure_1": "ai-cover.jpg"})

        self.assertIn("主图：授时欺骗与保护级的概念示意", markdown)
        self.assertIn("主图为辅助示意图", markdown)
        self.assertIn("主图为辅助示意图", html)

    def test_figure_caption_removes_duplicate_number_prefixes(self) -> None:
        caption = "图 1 . Fig. 1: System Overview. The proposed framework."
        self.assertEqual(_display_figure_caption(caption, 1), "主图：系统总览")

    def test_figure_reading_translates_caption_without_keyword_template(self) -> None:
        paper = {
            "title": "SA-LIVO: Subspace-Aware LiDAR-Inertial-Visual Odometry",
            "authors": ["A. Reader"],
            "abstract": "SA-LIVO fuses LiDAR, camera, and IMU measurements for robust odometry and mapping.",
            "matched_terms": ["slam", "lidar", "imu"],
        }
        reading = PaperReading(
            abstract=str(paper["abstract"]),
            introduction="Robust odometry needs stable fusion in diverse environments.",
            method="The system uses subspace-aware fusion and unified state update.",
            experiments="Representative mapping results are shown across diverse environments.",
            conclusion="The method improves mapping robustness.",
            captions=("Fig. 1. System overview of SA-LIVO.",),
        )
        figure = DeepDiveFigure(Path("figure-1.jpg"), reading.captions[0])

        text = _figure_reading(paper, reading, figure, 1)

        self.assertIn("原文图注可以译为：“SA-LIVO 系统总览”", text)
        self.assertNotIn("关键词是", text)
        self.assertNotIn("输入 ->", text)

    def test_image_variants_support_both_modes(self) -> None:
        self.assertEqual(_image_variants("both"), ("paper", "ai"))
        self.assertEqual(_image_variants("paper"), ("paper",))

    def test_extract_base64_image_from_gemini_payload(self) -> None:
        payload = {
            "output": [
                {
                    "content": [
                        {"inlineData": {"mimeType": "image/png", "data": "YWJj"}},
                    ]
                }
            ]
        }
        self.assertEqual(_extract_base64_image(payload), "YWJj")

    def test_experiment_figures_are_combined_before_article_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cover = tmp_path / "cover.jpg"
            result_a = tmp_path / "result-a.jpg"
            result_b = tmp_path / "result-b.jpg"
            Image.new("RGB", (800, 360), "white").save(cover)
            Image.new("RGB", (800, 360), "gray").save(result_a)
            Image.new("RGB", (800, 360), "silver").save(result_b)

            figures = [
                DeepDiveFigure(cover, "Fig. 1. System overview of SA-LIVO."),
                DeepDiveFigure(result_a, "Fig. 2. Representative mapping results of SA-LIVO across diverse environments."),
                DeepDiveFigure(result_b, "Fig. 3. Trajectory evaluation on campus sequences."),
            ]

            prepared = _prepare_article_figures(figures, tmp_path, 2)

            self.assertEqual(prepared[0].path, cover)
            self.assertEqual(prepared[1].source, "paper_composite")
            self.assertTrue(prepared[1].path.exists())
            self.assertTrue(_display_figure_caption(prepared[1].caption, 2, prepared[1].source).startswith("实验图："))

    def test_polished_text_overrides_traditional_text(self) -> None:
        paper = {"title": "Example", "authors": [], "abstract": "GNSS spoofing risk.", "matched_terms": ["gnss"]}
        reading = PaperReading("GNSS spoofing risk.", "", "", "", "", ())
        figures: list[DeepDiveFigure] = []
        polish = TextPolishResult("api", "ok", {"one_sentence": "润色后的一句话。"})

        markdown = build_deepdive_markdown(paper, reading, figures, {}, text_polish=polish)

        self.assertIn("润色后的一句话。", markdown)
        self.assertEqual(_content_mode_label("api"), "API 润色")

    def test_article_includes_read_original_links(self) -> None:
        paper = {
            "title": "GNSS Timing Spoofing Protection Level",
            "authors": ["A. Reader"],
            "abstract": "This paper studies timing protection levels for GNSS spoofing.",
            "published": "2026-07-01T00:00:00+00:00",
            "url": "https://arxiv.org/abs/2607.00001",
            "pdf_url": "https://arxiv.org/pdf/2607.00001",
            "quality_signals": {"code_url": "https://github.com/example/tpl"},
            "matched_terms": ["gnss", "spoofing"],
        }
        reading = PaperReading(str(paper["abstract"]), "", "", "", "", ())

        markdown = build_deepdive_markdown(paper, reading, [], {})
        html = build_deepdive_html(paper, reading, [], {})

        for text in (markdown, html):
            self.assertIn("阅读原文", text)
            self.assertIn("原文页面", text)
            self.assertIn("PDF下载", text)
            self.assertIn("代码/项目", text)
            self.assertIn("https://arxiv.org/pdf/2607.00001", text)
            self.assertIn("https://github.com/example/tpl", text)

    def test_draft_email_links_include_outputs_and_source_downloads(self) -> None:
        source_lines = _draft_source_lines(
            {
                "source_url": "https://arxiv.org/abs/2607.00001",
                "pdf_url": "https://arxiv.org/pdf/2607.00001",
                "code_url": "https://github.com/example/tpl",
            }
        )

        self.assertEqual(
            source_lines,
            [
                "原文页面：https://arxiv.org/abs/2607.00001",
                "PDF下载：https://arxiv.org/pdf/2607.00001",
                "代码/项目：https://github.com/example/tpl",
            ],
        )
        self.assertTrue(_file_url("outputs/deepdives/example/article.html").startswith("file://"))


if __name__ == "__main__":
    unittest.main()
