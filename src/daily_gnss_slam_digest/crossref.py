from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .models import Paper


CROSSREF_WORKS_URL = "https://api.crossref.org/works"


class CrossrefError(RuntimeError):
    pass


class CrossrefClient:
    def __init__(
        self,
        timeout: int = 20,
        base_url: str = CROSSREF_WORKS_URL,
        mailto: str | None = None,
    ) -> None:
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self.mailto = mailto or os.getenv("CROSSREF_MAILTO") or os.getenv("OPENALEX_MAILTO")

    def search(self, query: str, limit: int = 25) -> list[Paper]:
        params = {
            "query.title": query,
            "rows": str(max(min(limit, 100), 1)),
            "sort": "published",
            "order": "desc",
        }
        if self.mailto:
            params["mailto"] = self.mailto
        url = f"{self.base_url}?{urllib.parse.urlencode(params)}"
        data = self._get_json(url)
        message = data.get("message")
        items = message.get("items") if isinstance(message, dict) else None
        if not isinstance(items, list):
            return []
        return [_paper_from_item(item) for item in items if isinstance(item, dict)]

    def search_many(self, queries: list[str], limit_per_query: int = 25, delay_seconds: float = 1.0) -> list[Paper]:
        papers_by_id: dict[str, Paper] = {}
        for index, query in enumerate(queries):
            if index:
                time.sleep(max(delay_seconds, 0.0))
            for paper in self.search(query, limit=limit_per_query):
                key = paper.doi or paper.url or paper.title
                papers_by_id.setdefault(key, paper)
        return list(papers_by_id.values())

    def _get_json(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(url, headers={"User-Agent": "daily-gnss-slam-digest/0.1"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return _decode_json(response.read())
        except urllib.error.HTTPError as exc:
            raise CrossrefError(f"Crossref API returned HTTP {exc.code}") from exc
        except OSError as exc:
            raise CrossrefError(f"Crossref API failed: {exc}") from exc


def _paper_from_item(item: dict[str, Any]) -> Paper:
    title = _first_string(item.get("title")) or "Untitled"
    doi = _optional_str(item.get("DOI"))
    arxiv_id = _arxiv_id_from_item(item)
    published = _published_datetime(item)
    return Paper(
        title=title,
        authors=_authors_from_item(item),
        abstract=_clean_abstract(_optional_str(item.get("abstract")) or ""),
        url=_paper_url(item, doi, arxiv_id),
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else None,
        published=published,
        updated=published,
        categories=("crossref",),
        primary_category="Crossref",
        arxiv_id=arxiv_id,
        doi=doi,
        citation_count=_int_or_none(item.get("is-referenced-by-count")),
        venue=_venue_from_item(item),
    )


def _authors_from_item(item: dict[str, Any]) -> tuple[str, ...]:
    authors = item.get("author")
    if not isinstance(authors, list):
        return ()
    names: list[str] = []
    for author in authors:
        if not isinstance(author, dict):
            continue
        given = str(author.get("given") or "").strip()
        family = str(author.get("family") or "").strip()
        literal = str(author.get("name") or "").strip()
        name = " ".join(part for part in (given, family) if part) or literal
        if name:
            names.append(name)
    return tuple(names)


def _published_datetime(item: dict[str, Any]) -> datetime:
    for key in ("published-print", "published-online", "published", "issued", "created"):
        date_parts = item.get(key)
        parsed = _date_parts_datetime(date_parts)
        if parsed:
            return parsed
    return datetime.now(timezone.utc)


def _date_parts_datetime(value: Any) -> datetime | None:
    if not isinstance(value, dict):
        return None
    date_parts = value.get("date-parts")
    if not isinstance(date_parts, list) or not date_parts:
        return None
    first = date_parts[0]
    if not isinstance(first, list) or not first:
        return None
    year = _int_or_none(first[0])
    if not year:
        return None
    month = _int_or_none(first[1]) if len(first) > 1 else 1
    day = _int_or_none(first[2]) if len(first) > 2 else 1
    try:
        return datetime(year, month or 1, day or 1, tzinfo=timezone.utc)
    except ValueError:
        return datetime(year, 1, 1, tzinfo=timezone.utc)


def _paper_url(item: dict[str, Any], doi: str | None, arxiv_id: str | None) -> str:
    if arxiv_id:
        return f"https://arxiv.org/abs/{arxiv_id}"
    url = _optional_str(item.get("URL"))
    if url:
        return url
    if doi:
        return f"https://doi.org/{doi}"
    return ""


def _venue_from_item(item: dict[str, Any]) -> str | None:
    return _first_string(item.get("container-title")) or _first_string(item.get("short-container-title"))


def _arxiv_id_from_item(item: dict[str, Any]) -> str | None:
    values = [item.get("URL"), item.get("DOI"), item.get("title")]
    relation = item.get("relation")
    relation_iterable = (relation or {}).values() if isinstance(relation, dict) else ()
    for relation_values in relation_iterable:
        values.append(relation_values)
    haystack = " ".join(_flatten_strings(values))
    match = re.search(r"arxiv[:/ ]+([0-9]{4}\.[0-9]{4,5})(?:v[0-9]+)?", haystack, flags=re.I)
    if match:
        return match.group(1)
    return None


def _flatten_strings(values: list[Any]) -> list[str]:
    flattened: list[str] = []
    for value in values:
        if isinstance(value, str):
            flattened.append(value)
        elif isinstance(value, list):
            flattened.extend(_flatten_strings(value))
        elif isinstance(value, dict):
            flattened.extend(_flatten_strings(list(value.values())))
    return flattened


def _first_string(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _clean_abstract(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value).replace("\n", " ").strip()


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
        raise CrossrefError(f"Crossref response is not JSON: {raw[:200]!r}") from exc
    if not isinstance(data, dict):
        raise CrossrefError(f"Crossref response is not an object: {data!r}")
    return data
