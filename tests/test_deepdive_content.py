from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from daily_gnss_slam_digest.deepdive import (
    DeepDiveFigure,
    FigureCaptionAnchor,
    PaperReading,
    TextPolishResult,
    _clean_text_polish_payload,
    _crop_rendered_figure,
    _content_mode_label,
    _display_figure_caption,
    _draft_source_lines,
    _detail_tokens,
    _domain_profile,
    _evidence_summary,
    _extract_base64_image,
    _extract_ollama_message_text,
    _extract_openai_message_text,
    _figure_reading,
    _figure_section,
    _has_real_figure_caption,
    _file_url,
    _image_variants,
    _is_low_information_image,
    _parse_caption_anchors,
    _prepare_article_figures,
    _sentence_candidates,
    _text_polish_provider_order,
    _usable_detail_tokens,
    _usable_numbers,
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
            self.assertNotIn("线索落在", text)
            self.assertNotIn("数字线索", text)
            self.assertNotIn("短句线索", text)
            self.assertNotIn("可以重点看", text)
            self.assertNotIn("原文强调的是", text)
            self.assertNotIn("相关数字包括", text)
            self.assertNotIn("文中围绕", text)
            self.assertNotIn("文中给出了", text)

    def test_deepdive_filters_pdf_fragments_and_fake_terms(self) -> None:
        noisy_text = (
            "8,. 5,. These paragraphs mention Command Measured Entry, ISUAL, NFO, IDAR, ORM, and GPS-referenced Yas-region. "
            "The evaluation uses GNSS and UAV measurements across four scenarios at 10 m/s and 80 m. "
            "The result table reports localization error and recovery time."
        )

        self.assertNotIn("8,.", _sentence_candidates(noisy_text))
        self.assertNotIn("5,.", _sentence_candidates(noisy_text))
        self.assertNotIn("These", _detail_tokens(noisy_text))
        self.assertNotIn("Command Measured Entry", _detail_tokens(noisy_text))
        self.assertNotIn("GPS-referenced Yas-region", _detail_tokens(noisy_text))
        for fake_term in ("ISUAL", "NFO", "IDAR", "ORM"):
            self.assertNotIn(fake_term, _usable_detail_tokens(_detail_tokens(noisy_text)))
        self.assertNotIn("原文强调的是", _evidence_summary("8,."))
        self.assertEqual(_evidence_summary("8,."), "")
        self.assertEqual(_evidence_summary("This short line only mentions HILTI."), "")
        self.assertEqual(_evidence_summary("The model reports a 10s interval."), "")
        self.assertNotIn("4032 x", _usable_numbers(["4032 x", "10 m/s"]))
        self.assertIn("10 m/s", _usable_numbers(["4032 x", "10 m/s"]))

    def test_slam_papers_with_gps_reference_are_not_classified_as_gnss_security(self) -> None:
        paper = {
            "title": "FAST-LIVO trajectories with GPS reference",
            "abstract": "This SLAM paper evaluates LiDAR visual inertial odometry with GPS ground truth trajectories.",
            "matched_terms": ["slam", "lidar", "odometry"],
        }
        profile = _domain_profile(paper, PaperReading("", "", "", "", "", ()))

        self.assertNotIn("GNSS/PNT", profile["actor"])
        self.assertTrue("SLAM" in profile["engineering"] or "LIVO" in profile["engineering"])

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

        self.assertIn("概念图：授时欺骗与保护级的概念示意", markdown)
        self.assertIn("概念图为辅助示意图", markdown)
        self.assertIn("概念图为辅助示意图", html)
        self.assertNotIn("主图", markdown)

    def test_figure_caption_removes_duplicate_number_prefixes(self) -> None:
        caption = "图 1 . Fig. 1: System Overview. The proposed framework."
        self.assertEqual(_display_figure_caption(caption, 1), "论文图：系统总览")

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
            method = tmp_path / "method.jpg"
            result_a = tmp_path / "result-a.jpg"
            result_b = tmp_path / "result-b.jpg"
            _sample_figure(cover, "system")
            _sample_figure(method, "pipeline")
            _sample_figure(result_a, "map")
            _sample_figure(result_b, "trajectory")

            figures = [
                DeepDiveFigure(cover, "Fig. 1. Sensor platform and data collection scenario."),
                DeepDiveFigure(method, "Fig. 2. Proposed pipeline of the subspace-aware fusion module."),
                DeepDiveFigure(result_a, "Fig. 2. Representative mapping results of SA-LIVO across diverse environments."),
                DeepDiveFigure(result_b, "Fig. 3. Trajectory evaluation on campus sequences."),
            ]

            prepared = _prepare_article_figures(figures, tmp_path, 2)

            self.assertEqual([figure.source for figure in prepared], ["intro_group", "method_group", "experiment_group"])
            self.assertEqual(prepared[0].path, cover)
            self.assertEqual(prepared[1].path, method)
            self.assertTrue(prepared[2].path.exists())
            self.assertTrue(_display_figure_caption(prepared[2].caption, 3, prepared[2].source).startswith("Experiments 图组："))

    def test_black_figures_are_filtered_before_grouping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            black = tmp_path / "black.jpg"
            method = tmp_path / "method.jpg"
            Image.new("RGB", (900, 520), "black").save(black)
            _sample_figure(method, "pipeline")

            self.assertTrue(_is_low_information_image(Image.open(black).convert("RGB")))

            prepared = _prepare_article_figures(
                [
                    DeepDiveFigure(black, "Fig. 4. Evaluation of computation times per LiDAR scan."),
                    DeepDiveFigure(method, "Fig. 1. Proposed pipeline."),
                ],
                tmp_path,
                2,
            )

            self.assertEqual(len(prepared), 1)
            self.assertEqual(prepared[0].path, method)

    def test_reliable_captioned_figures_win_over_embedded_fallbacks_in_same_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reliable = tmp_path / "reliable.jpg"
            fallback = tmp_path / "fallback.jpg"
            _sample_figure(reliable, "trajectory")
            _sample_figure(fallback, "fallback")

            prepared = _prepare_article_figures(
                [
                    DeepDiveFigure(reliable, "Fig. 6. Trajectory comparisons across four datasets.", source="paper_render"),
                    DeepDiveFigure(fallback, "PDF 内嵌图片 3（未匹配到可靠图注）", source="paper_embedded"),
                ],
                tmp_path,
                2,
            )

            self.assertEqual(len(prepared), 1)
            self.assertEqual(prepared[0].source, "experiment_group")
            self.assertEqual(prepared[0].children, ("Fig. 6. Trajectory comparisons across four datasets.",))

    def test_bbox_caption_parser_finds_captions_not_text_references(self) -> None:
        bbox_text = """
        <html><body><doc>
          <page width="612.000000" height="792.000000">
            <flow><block><line xMin="323.000000" yMin="100.000000" xMax="558.000000" yMax="110.000000">
              <word xMin="323.000000" yMin="100.000000" xMax="338.000000" yMax="110.000000">Fig.</word>
              <word xMin="341.000000" yMin="100.000000" xMax="348.000000" yMax="110.000000">2</word>
              <word xMin="352.000000" yMin="100.000000" xMax="378.000000" yMax="110.000000">shows</word>
              <word xMin="382.000000" yMin="100.000000" xMax="410.000000" yMax="110.000000">the</word>
            </line></block></flow>
            <flow><block><line xMin="323.000000" yMin="150.000000" xMax="558.000000" yMax="160.000000">
              <word xMin="323.000000" yMin="150.000000" xMax="338.000000" yMax="160.000000">Fig.</word>
              <word xMin="341.000000" yMin="150.000000" xMax="352.000000" yMax="160.000000">2,</word>
              <word xMin="356.000000" yMin="150.000000" xMax="380.000000" yMax="160.000000">while</word>
              <word xMin="384.000000" yMin="150.000000" xMax="410.000000" yMax="160.000000">the</word>
            </line></block></flow>
            <flow><block><line xMin="54.000000" yMin="210.000000" xMax="558.000000" yMax="220.000000">
              <word xMin="54.000000" yMin="210.000000" xMax="70.000000" yMax="220.000000">Fig.</word>
              <word xMin="74.000000" yMin="210.000000" xMax="80.000000" yMax="220.000000">2.</word>
              <word xMin="86.000000" yMin="210.000000" xMax="160.000000" yMax="220.000000">Architecture</word>
              <word xMin="164.000000" yMin="210.000000" xMax="220.000000" yMax="220.000000">Overview</word>
            </line></block></flow>
            <flow><block><line xMin="54.000000" yMin="222.000000" xMax="250.000000" yMax="232.000000">
              <word xMin="54.000000" yMin="222.000000" xMax="80.000000" yMax="232.000000">of</word>
              <word xMin="84.000000" yMin="222.000000" xMax="130.000000" yMax="232.000000">FAR-LIO.</word>
            </line></block></flow>
          </page>
        </doc></body></html>
        """

        anchors = _parse_caption_anchors(bbox_text)

        self.assertEqual(len(anchors), 1)
        self.assertEqual(anchors[0].figure_number, "2")
        self.assertIn("Architecture Overview", anchors[0].caption)
        self.assertIn("FAR-LIO", anchors[0].caption)

    def test_rendered_figure_crop_prefers_visual_block_above_caption(self) -> None:
        page = Image.new("RGB", (850, 1100), "white")
        draw = ImageDraw.Draw(page)
        for row in range(8):
            y = 120 + row * 28
            draw.text((70, y), "This paragraph mentions Fig. 3 before the actual diagram.", fill=(0, 0, 0))
        # Diagram block below the paragraph.
        for index in range(5):
            x0 = 110 + index * 110
            y0 = 520 + (index % 2) * 70
            draw.rectangle((x0, y0, x0 + 80, y0 + 50), outline=(30, 90, 120), width=4)
            draw.line((x0 + 80, y0 + 25, min(x0 + 135, 760), y0 + 25), fill=(0, 140, 110), width=4)
        draw.text((160, 780), "Fig. 3. Structure of the CUDA-accelerated voxel map.", fill=(0, 0, 0))
        anchor = FigureCaptionAnchor(
            page_index=1,
            page_width=612,
            page_height=792,
            x_min=82,
            y_min=562,
            x_max=270,
            y_max=574,
            caption="Fig. 3. Structure of the CUDA-accelerated voxel map.",
            figure_number="3",
        )

        crop = _crop_rendered_figure(page, anchor)

        self.assertGreater(crop.width, 300)
        self.assertGreater(crop.height, 120)
        self.assertLess(crop.height, 420)
        self.assertEqual(_figure_section(DeepDiveFigure(Path("figure.jpg"), anchor.caption, source="paper_render")), "method")
        self.assertEqual(
            _figure_section(
                DeepDiveFigure(
                    Path("result.jpg"),
                    "Fig. 1. Point cloud maps of the Yas Marina Circuit and KITTI sequence.",
                    source="paper_render",
                )
            ),
            "experiment",
        )
        self.assertEqual(
            _figure_section(
                DeepDiveFigure(
                    Path("trajectory.jpg"),
                    "Fig. 2. Trajectories from FAST-LIVO (black), GPS (blue), and the proposed method.",
                    source="paper_render",
                )
            ),
            "experiment",
        )
        self.assertEqual(
            _figure_section(
                DeepDiveFigure(
                    Path("fusion.jpg"),
                    "Fig. 4. Subspace-Aware Information Fusion via the linear-clamp soft gate.",
                    source="paper_render",
                )
            ),
            "method",
        )
        self.assertEqual(
            _figure_section(
                DeepDiveFigure(
                    Path("spherical-results.jpg"),
                    "Fig. 5. Camera configurations and spherical triangulation results of four setups.",
                    source="paper_render",
                )
            ),
            "experiment",
        )
        self.assertEqual(
            _figure_section(
                DeepDiveFigure(
                    Path("sphere-overview.jpg"),
                    "Fig. 1. Overview of the Sphere-VIO framework for multi-camera-to-spherical mapping.",
                    source="paper_render",
                )
            ),
            "method",
        )
        self.assertEqual(
            _figure_section(
                DeepDiveFigure(
                    Path("forward-mapping.jpg"),
                    "Fig. 2. Forward mapping of the proposed USPM.",
                    source="paper_render",
                )
            ),
            "method",
        )

    def test_unmatched_embedded_figures_are_not_treated_as_captioned_figures(self) -> None:
        caption = "PDF 内嵌图片 7（未匹配到可靠图注）"

        self.assertFalse(_has_real_figure_caption(caption))
        self.assertEqual(
            _figure_section(DeepDiveFigure(Path("embedded.jpg"), caption, source="paper_embedded")),
            "experiment",
        )
        self.assertEqual(_display_figure_caption(caption, 1, source="paper_embedded"), "论文图：从 PDF 提取的论文原图")

    def test_polished_text_overrides_traditional_text(self) -> None:
        paper = {"title": "Example", "authors": [], "abstract": "GNSS spoofing risk.", "matched_terms": ["gnss"]}
        reading = PaperReading("GNSS spoofing risk.", "", "", "", "", ())
        figures: list[DeepDiveFigure] = []
        polish = TextPolishResult("api", "ok", {"one_sentence": "润色后的一句话。"})

        markdown = build_deepdive_markdown(paper, reading, figures, {}, text_polish=polish)

        self.assertIn("润色后的一句话。", markdown)
        self.assertEqual(_content_mode_label("api"), "AI 润色（Gemini）")
        self.assertEqual(_content_mode_label("gemini"), "AI 润色（Gemini）")
        self.assertEqual(_content_mode_label("siliconflow"), "AI 润色（SiliconFlow）")
        self.assertEqual(_content_mode_label("ollama"), "本地模型润色（Ollama）")
        self.assertEqual(_content_mode_label("fallback"), "传统模板（AI 不可用时回退）")

    def test_text_polish_provider_order_and_openai_payload(self) -> None:
        self.assertEqual(_text_polish_provider_order("api"), ("gemini", "siliconflow", "ollama"))
        self.assertEqual(_text_polish_provider_order("siliconflow"), ("siliconflow",))
        self.assertEqual(_text_polish_provider_order("ollama"), ("ollama",))

        payload = {"choices": [{"message": {"content": '{"one_sentence":"润色后的文本。"}'}}]}
        self.assertEqual(_extract_openai_message_text(payload), '{"one_sentence":"润色后的文本。"}')
        ollama_payload = {"message": {"content": '{"one_sentence":"本地润色后的文本。"}'}}
        self.assertEqual(_extract_ollama_message_text(ollama_payload), '{"one_sentence":"本地润色后的文本。"}')
        cleaned = _clean_text_polish_payload({"one_sentence": "润色后的文本。", "unknown": "忽略"}, {"one_sentence": "原文"})

        self.assertEqual(cleaned, {"one_sentence": "润色后的文本。"})

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
            self.assertIn("Introduction：研究背景与问题", text)
            self.assertIn("Method：方法与系统设计", text)
            self.assertIn("Experiments：实验设置与结果", text)
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


def _sample_figure(path: Path, label: str) -> None:
    image = Image.new("RGB", (900, 520), "white")
    draw = ImageDraw.Draw(image)
    for index in range(6):
        x0 = 60 + index * 130
        y0 = 80 + (index % 2) * 120
        draw.rectangle((x0, y0, x0 + 90, y0 + 70), outline=(18, 80, 92), width=5)
        draw.line((x0 + 90, y0 + 35, min(x0 + 150, 860), y0 + 35), fill=(0, 150, 130), width=4)
    draw.text((70, 430), label, fill=(20, 40, 45))
    image.save(path)


if __name__ == "__main__":
    unittest.main()
