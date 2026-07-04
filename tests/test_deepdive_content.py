from __future__ import annotations

import unittest
from pathlib import Path

from daily_gnss_slam_digest.deepdive import (
    DeepDiveFigure,
    PaperReading,
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


if __name__ == "__main__":
    unittest.main()
