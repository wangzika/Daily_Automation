from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from .models import Paper


SEMANTIC_SCHOLAR_GRAPH_URL = "https://api.semanticscholar.org/graph/v1/paper"
DEFAULT_FIELDS = "citationCount,influentialCitationCount,venue,publicationVenue,url,externalIds"
SEARCH_FIELDS = (
    "paperId,title,abstract,authors,year,publicationDate,externalIds,url,openAccessPdf,"
    "citationCount,influentialCitationCount,venue,publicationVenue"
)


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

    def search(self, query: str, limit: int = 25) -> list[Paper]:
        params = {
            "query": query,
            "limit": str(max(min(limit, 100), 1)),
            "fields": SEARCH_FIELDS,
        }
        url = f"{self.base_url}/search?{urllib.parse.urlencode(params)}"
        data = self._get_json(url)
        items = data.get("data")
        if not isinstance(items, list):
            return []
        return [_paper_from_search_item(item) for item in items if isinstance(item, dict)]

    def search_many(self, queries: list[str], limit_per_query: int = 25, delay_seconds: float = 1.0) -> list[Paper]:
        papers_by_id: dict[str, Paper] = {}
        for index, query in enumerate(queries):
            if index:
                time.sleep(max(delay_seconds, 0.0))
            for paper in self.search(query, limit=limit_per_query):
                key = paper.arxiv_id or paper.doi or paper.url or paper.title
                papers_by_id.setdefault(key, paper)
        return list(papers_by_id.values())

    def _get_json(self, url: str) -> dict[str, Any]:
        headers = {"User-Agent": "daily-gnss-slam-digest/0.1"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return _decode_json(response.read())
        except urllib.error.HTTPError as exc:
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


def _paper_from_search_item(item: dict[str, Any]) -> Paper:
    external_ids = item.get("externalIds") if isinstance(item.get("externalIds"), dict) else {}
    arxiv_id = _external_id(external_ids, ("ArXiv", "arXiv"))
    doi = _external_id(external_ids, ("DOI", "doi"))
    published = _publication_datetime(item)
    url = _paper_url(item, arxiv_id)
    return Paper(
        title=str(item.get("title") or "Untitled"),
        authors=_authors_from_item(item),
        abstract=str(item.get("abstract") or ""),
        url=url,
        pdf_url=_pdf_url(item, arxiv_id),
        published=published,
        updated=published,
        categories=("semantic-scholar",),
        primary_category="Semantic Scholar",
        arxiv_id=arxiv_id,
        doi=doi,
        citation_count=_int_or_none(item.get("citationCount")),
        influential_citation_count=_int_or_none(item.get("influentialCitationCount")),
        venue=_venue_from_metadata(item),
    )


def _authors_from_item(item: dict[str, Any]) -> tuple[str, ...]:
    authors = item.get("authors")
    if not isinstance(authors, list):
        return ()
    names: list[str] = []
    for author in authors:
        if isinstance(author, dict) and isinstance(author.get("name"), str) and author["name"].strip():
            names.append(author["name"].strip())
    return tuple(names)


def _publication_datetime(item: dict[str, Any]) -> datetime:
    publication_date = item.get("publicationDate")
    if isinstance(publication_date, str) and publication_date:
        try:
            return datetime.fromisoformat(publication_date).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    year = _int_or_none(item.get("year"))
    if year:
        return datetime(year, 1, 1, tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _paper_url(item: dict[str, Any], arxiv_id: str | None) -> str:
    if arxiv_id:
        return f"https://arxiv.org/abs/{arxiv_id}"
    url = item.get("url")
    if isinstance(url, str) and url:
        return url
    paper_id = item.get("paperId")
    if isinstance(paper_id, str) and paper_id:
        return f"https://www.semanticscholar.org/paper/{paper_id}"
    return ""


def _pdf_url(item: dict[str, Any], arxiv_id: str | None) -> str | None:
    if arxiv_id:
        return f"https://arxiv.org/pdf/{arxiv_id}"
    open_access_pdf = item.get("openAccessPdf")
    if isinstance(open_access_pdf, dict):
        url = open_access_pdf.get("url")
        if isinstance(url, str) and url:
            return url
    return None


def _external_id(external_ids: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = external_ids.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
