from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import replace
from typing import Any

from .models import Paper


SEMANTIC_SCHOLAR_GRAPH_URL = "https://api.semanticscholar.org/graph/v1/paper"
DEFAULT_FIELDS = "citationCount,influentialCitationCount,venue,publicationVenue,url,externalIds"


class SemanticScholarError(RuntimeError):
    pass


class SemanticScholarClient:
    def __init__(
        self,
        api_key: str | None = None,
        timeout: int = 20,
        base_url: str = SEMANTIC_SCHOLAR_GRAPH_URL,
    ) -> None:
        self.api_key = api_key or os.getenv("SEMANTIC_SCHOLAR_API_KEY")
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")

    def paper_metadata(self, paper: Paper) -> dict[str, Any] | None:
        paper_id = _semantic_scholar_paper_id(paper)
        if not paper_id:
            return None

        params = {"fields": DEFAULT_FIELDS}
        url = f"{self.base_url}/{urllib.parse.quote(paper_id, safe=':')}?{urllib.parse.urlencode(params)}"
        headers = {"User-Agent": "daily-gnss-slam-digest/0.1"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return _decode_json(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise SemanticScholarError(f"Semantic Scholar API returned HTTP {exc.code}") from exc
        except OSError as exc:
            raise SemanticScholarError(f"Semantic Scholar API failed: {exc}") from exc


def enrich_papers(
    papers: list[Paper],
    client: SemanticScholarClient | None = None,
    max_papers: int = 30,
    delay_seconds: float = 1.0,
) -> list[Paper]:
    client = client or SemanticScholarClient()
    enriched: list[Paper] = []
    for index, paper in enumerate(papers):
        if index >= max_papers:
            enriched.append(paper)
            continue
        if index:
            time.sleep(max(delay_seconds, 0.0))
        try:
            metadata = client.paper_metadata(paper)
        except SemanticScholarError as exc:
            print(f"Semantic Scholar enrichment skipped for {paper.title}: {exc}")
            enriched.append(paper)
            continue
        if not metadata:
            enriched.append(paper)
            continue
        enriched.append(_apply_metadata(paper, metadata))
    return enriched


def _apply_metadata(paper: Paper, metadata: dict[str, Any]) -> Paper:
    venue = _venue_from_metadata(metadata) or paper.venue
    return replace(
        paper,
        citation_count=_int_or_none(metadata.get("citationCount")),
        influential_citation_count=_int_or_none(metadata.get("influentialCitationCount")),
        venue=venue,
    )


def _semantic_scholar_paper_id(paper: Paper) -> str | None:
    if paper.arxiv_id:
        return f"arXiv:{paper.arxiv_id}"
    if paper.doi:
        return f"DOI:{paper.doi}"
    return None


def _venue_from_metadata(metadata: dict[str, Any]) -> str | None:
    publication_venue = metadata.get("publicationVenue")
    if isinstance(publication_venue, dict):
        name = publication_venue.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    venue = metadata.get("venue")
    if isinstance(venue, str) and venue.strip():
        return venue.strip()
    return None


def _decode_json(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise SemanticScholarError(f"Semantic Scholar response is not JSON: {raw[:200]!r}") from exc
    if not isinstance(data, dict):
        raise SemanticScholarError(f"Semantic Scholar response is not an object: {data!r}")
    return data


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
