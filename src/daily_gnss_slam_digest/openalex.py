from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .models import Paper


OPENALEX_WORKS_URL = "https://api.openalex.org/works"
OPENALEX_FIELDS = (
    "id,doi,title,display_name,publication_date,publication_year,authorships,abstract_inverted_index,"
    "primary_location,open_access,cited_by_count,ids,primary_topic,locations"
)


class OpenAlexError(RuntimeError):
    pass


class OpenAlexClient:
    def __init__(
        self,
        timeout: int = 20,
        base_url: str = OPENALEX_WORKS_URL,
        api_key: str | None = None,
        mailto: str | None = None,
    ) -> None:
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.getenv("OPENALEX_API_KEY")
        self.mailto = mailto or os.getenv("OPENALEX_MAILTO")

    def search(self, query: str, limit: int = 25) -> list[Paper]:
        params = {
            "search": query,
            "per-page": str(max(min(limit, 200), 1)),
            "sort": "publication_date:desc",
            "select": OPENALEX_FIELDS,
        }
        if self.api_key:
            params["api_key"] = self.api_key
        if self.mailto:
            params["mailto"] = self.mailto
        url = f"{self.base_url}?{urllib.parse.urlencode(params)}"
        data = self._get_json(url)
        results = data.get("results")
        if not isinstance(results, list):
            return []
        return [_paper_from_work(work) for work in results if isinstance(work, dict)]

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
        request = urllib.request.Request(url, headers={"User-Agent": "daily-gnss-slam-digest/0.1"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return _decode_json(response.read())
        except urllib.error.HTTPError as exc:
            raise OpenAlexError(f"OpenAlex API returned HTTP {exc.code}") from exc
        except OSError as exc:
            raise OpenAlexError(f"OpenAlex API failed: {exc}") from exc


def _paper_from_work(work: dict[str, Any]) -> Paper:
    title = str(work.get("title") or work.get("display_name") or "Untitled")
    ids = work.get("ids") if isinstance(work.get("ids"), dict) else {}
    doi = _doi_from_work(work, ids)
    arxiv_id = _arxiv_id_from_work(work, ids)
    published = _publication_datetime(work)
    return Paper(
        title=title,
        authors=_authors_from_work(work),
        abstract=_abstract_from_inverted_index(work.get("abstract_inverted_index")),
        url=_paper_url(work, doi, arxiv_id),
        pdf_url=_pdf_url(work, arxiv_id),
        published=published,
        updated=published,
        categories=("openalex",),
        primary_category="OpenAlex",
        arxiv_id=arxiv_id,
        doi=doi,
        citation_count=_int_or_none(work.get("cited_by_count")),
        venue=_venue_from_work(work),
    )


def _authors_from_work(work: dict[str, Any]) -> tuple[str, ...]:
    authorships = work.get("authorships")
    if not isinstance(authorships, list):
        return ()
    names: list[str] = []
    for authorship in authorships:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author")
        if isinstance(author, dict) and isinstance(author.get("display_name"), str):
            name = author["display_name"].strip()
            if name:
                names.append(name)
    return tuple(names)


def _abstract_from_inverted_index(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    words: list[tuple[int, str]] = []
    for word, positions in value.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int):
                words.append((position, word))
    return " ".join(word for _position, word in sorted(words))


def _publication_datetime(work: dict[str, Any]) -> datetime:
    publication_date = work.get("publication_date")
    if isinstance(publication_date, str) and publication_date:
        try:
            return datetime.fromisoformat(publication_date).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    year = _int_or_none(work.get("publication_year"))
    if year:
        return datetime(year, 1, 1, tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _paper_url(work: dict[str, Any], doi: str | None, arxiv_id: str | None) -> str:
    if arxiv_id:
        return f"https://arxiv.org/abs/{arxiv_id}"
    landing_page_url = _primary_location_value(work, "landing_page_url")
    if landing_page_url:
        return landing_page_url
    if doi:
        return f"https://doi.org/{doi}"
    identifier = work.get("id")
    return str(identifier or "")


def _pdf_url(work: dict[str, Any], arxiv_id: str | None) -> str | None:
    if arxiv_id:
        return f"https://arxiv.org/pdf/{arxiv_id}"
    return _primary_location_value(work, "pdf_url")


def _venue_from_work(work: dict[str, Any]) -> str | None:
    source = _primary_location_value(work, "source")
    if isinstance(source, dict):
        display_name = source.get("display_name")
        if isinstance(display_name, str) and display_name.strip():
            return display_name.strip()
    primary_topic = work.get("primary_topic")
    if isinstance(primary_topic, dict):
        display_name = primary_topic.get("display_name")
        if isinstance(display_name, str) and display_name.strip():
            return display_name.strip()
    return None


def _primary_location_value(work: dict[str, Any], key: str) -> Any:
    primary_location = work.get("primary_location")
    if isinstance(primary_location, dict):
        return primary_location.get(key)
    return None


def _doi_from_work(work: dict[str, Any], ids: dict[str, Any]) -> str | None:
    value = work.get("doi") or ids.get("doi")
    if isinstance(value, str) and value:
        return value.removeprefix("https://doi.org/").strip() or None
    return None


def _arxiv_id_from_work(work: dict[str, Any], ids: dict[str, Any]) -> str | None:
    for value in (ids.get("arxiv"), ids.get("arxiv_id")):
        if isinstance(value, str) and value.strip():
            return value.rsplit("/", 1)[-1].replace("arXiv:", "").strip()
    for location in _locations(work):
        url = ""
        if isinstance(location, dict):
            url = " ".join(str(location.get(key) or "") for key in ("landing_page_url", "pdf_url"))
        marker = "arxiv.org/"
        if marker in url:
            return _extract_arxiv_id(url)
    return None


def _locations(work: dict[str, Any]) -> list[Any]:
    locations = work.get("locations")
    return locations if isinstance(locations, list) else []


def _extract_arxiv_id(url: str) -> str | None:
    if "/abs/" in url:
        return url.rsplit("/abs/", 1)[-1].split("?", 1)[0].split("v", 1)[0]
    if "/pdf/" in url:
        return url.rsplit("/pdf/", 1)[-1].split("?", 1)[0].removesuffix(".pdf").split("v", 1)[0]
    return None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _decode_json(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise OpenAlexError(f"OpenAlex response is not JSON: {raw[:200]!r}") from exc
    if not isinstance(data, dict):
        raise OpenAlexError(f"OpenAlex response is not an object: {data!r}")
    return data
