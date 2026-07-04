from __future__ import annotations

import tempfile
import unittest
import urllib.request
from datetime import timezone
from pathlib import Path

from daily_gnss_slam_digest.arxiv_client import ArxivClient, ArxivClientError
from daily_gnss_slam_digest.cli import _fallback_sources, _semantic_queries_for_topics
from daily_gnss_slam_digest.config import rotating_topic_for_date
from daily_gnss_slam_digest.crossref import _paper_from_item as _crossref_paper_from_item
from daily_gnss_slam_digest.openalex import _paper_from_work as _openalex_paper_from_work
from daily_gnss_slam_digest.semantic_scholar import _paper_from_search_item


class FallbackSourceTest(unittest.TestCase):
    def test_parses_enabled_fallback_sources(self) -> None:
        self.assertEqual(
            _fallback_sources("semantic-scholar, openalex, crossref, existing-json"),
            ("semantic-scholar", "openalex", "crossref", "existing-json"),
        )
        self.assertEqual(_fallback_sources("off"), ())

    def test_builds_semantic_scholar_query_from_topic_keywords(self) -> None:
        topic = rotating_topic_for_date(__import__("datetime").date(2026, 7, 4))

        queries = _semantic_queries_for_topics((topic,), ())

        self.assertEqual(len(queries), 1)
        self.assertIn("spoofing", queries[0])
        self.assertIn("jamming", queries[0])

    def test_semantic_scholar_search_item_maps_to_paper(self) -> None:
        paper = _paper_from_search_item(
            {
                "title": "GNSS Jamming Detection",
                "abstract": "Detects GNSS jamming with receiver observables.",
                "authors": [{"name": "A. Author"}],
                "publicationDate": "2026-02-13",
                "externalIds": {"ArXiv": "2602.12688", "DOI": "10.123/test"},
                "citationCount": 7,
                "venue": "NAVIGATION",
            }
        )

        self.assertEqual(paper.arxiv_id, "2602.12688")
        self.assertEqual(paper.url, "https://arxiv.org/abs/2602.12688")
        self.assertEqual(paper.pdf_url, "https://arxiv.org/pdf/2602.12688")
        self.assertEqual(paper.published.tzinfo, timezone.utc)
        self.assertEqual(paper.citation_count, 7)

    def test_openalex_work_maps_to_paper(self) -> None:
        paper = _openalex_paper_from_work(
            {
                "title": "Open Vocabulary Mapping for Robot Navigation",
                "publication_date": "2026-07-01",
                "authorships": [{"author": {"display_name": "A. Author"}}],
                "abstract_inverted_index": {"Robot": [0], "navigation": [1]},
                "ids": {"doi": "https://doi.org/10.123/openalex"},
                "primary_location": {
                    "landing_page_url": "https://example.org/paper",
                    "pdf_url": "https://example.org/paper.pdf",
                    "source": {"display_name": "Robotics Journal"},
                },
                "cited_by_count": 9,
            }
        )

        self.assertEqual(paper.title, "Open Vocabulary Mapping for Robot Navigation")
        self.assertEqual(paper.abstract, "Robot navigation")
        self.assertEqual(paper.doi, "10.123/openalex")
        self.assertEqual(paper.venue, "Robotics Journal")
        self.assertEqual(paper.citation_count, 9)

    def test_crossref_item_maps_to_paper(self) -> None:
        paper = _crossref_paper_from_item(
            {
                "title": ["GNSS Spoofing Detection"],
                "author": [{"given": "A.", "family": "Author"}],
                "published-online": {"date-parts": [[2026, 2, 13]]},
                "DOI": "10.123/crossref",
                "URL": "https://example.org/crossref",
                "container-title": ["NAVIGATION"],
                "is-referenced-by-count": 3,
            }
        )

        self.assertEqual(paper.title, "GNSS Spoofing Detection")
        self.assertEqual(paper.authors, ("A. Author",))
        self.assertEqual(paper.doi, "10.123/crossref")
        self.assertEqual(paper.venue, "NAVIGATION")
        self.assertEqual(paper.citation_count, 3)

    def test_arxiv_uses_stale_cache_after_live_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _FailingCachedArxivClient(cache_dir=Path(tmp), cache_ttl_hours=0)
            request = urllib.request.Request("https://export.arxiv.org/api/query?search_query=all%3AGNSS")
            cache_path = client._cache_path(request.full_url)
            assert cache_path is not None
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(b"<feed />")

            self.assertEqual(client._open_with_cache(request), b"<feed />")


class _FailingCachedArxivClient(ArxivClient):
    def _open_with_retries(self, request: urllib.request.Request) -> bytes:
        raise ArxivClientError("simulated live failure")


if __name__ == "__main__":
    unittest.main()
