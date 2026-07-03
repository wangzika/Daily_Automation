from __future__ import annotations

import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from .models import Paper


ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
ARXIV_API_URL = "https://export.arxiv.org/api/query"


class ArxivClientError(RuntimeError):
    pass


class ArxivClient:
    def __init__(self, user_agent: str = "daily-gnss-slam-digest/0.1", timeout: int = 30) -> None:
        self.user_agent = user_agent
        self.timeout = timeout

    def search(self, query: str, max_results: int = 25, start: int = 0) -> list[Paper]:
        params = {
            "search_query": query,
            "start": str(start),
            "max_results": str(max_results),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        url = f"{ARXIV_API_URL}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
        except OSError as exc:
            raise ArxivClientError(f"Failed to query arXiv: {exc}") from exc

        try:
            root = ET.fromstring(payload)
        except ET.ParseError as exc:
            raise ArxivClientError(f"Failed to parse arXiv response: {exc}") from exc

        return [self._parse_entry(entry) for entry in root.findall("atom:entry", ATOM_NS)]

    def search_many(self, queries: list[str], max_results_per_query: int = 25) -> list[Paper]:
        papers_by_id: dict[str, Paper] = {}
        for index, query in enumerate(queries):
            if index:
                time.sleep(3)
            for paper in self.search(query=query, max_results=max_results_per_query):
                key = paper.arxiv_id or paper.url
                papers_by_id.setdefault(key, paper)
        return list(papers_by_id.values())

    def _parse_entry(self, entry: ET.Element) -> Paper:
        title = _clean_text(_required_text(entry, "atom:title"))
        abstract = _clean_text(_required_text(entry, "atom:summary"))
        url = _required_text(entry, "atom:id").strip()
        authors = tuple(
            _clean_text(author.findtext("atom:name", default="", namespaces=ATOM_NS))
            for author in entry.findall("atom:author", ATOM_NS)
        )
        published = _parse_arxiv_datetime(_required_text(entry, "atom:published"))
        updated = _parse_arxiv_datetime(_required_text(entry, "atom:updated"))

        pdf_url = None
        for link in entry.findall("atom:link", ATOM_NS):
            if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                pdf_url = link.attrib.get("href")
                break

        categories = tuple(
            category.attrib["term"]
            for category in entry.findall("atom:category", ATOM_NS)
            if "term" in category.attrib
        )
        primary = entry.find("arxiv:primary_category", ATOM_NS)
        primary_category = primary.attrib.get("term") if primary is not None else None

        return Paper(
            title=title,
            authors=authors,
            abstract=abstract,
            url=url,
            pdf_url=pdf_url,
            published=published,
            updated=updated,
            categories=categories,
            primary_category=primary_category,
            arxiv_id=_extract_arxiv_id(url),
        )


def _required_text(entry: ET.Element, path: str) -> str:
    value = entry.findtext(path, namespaces=ATOM_NS)
    if value is None:
        raise ArxivClientError(f"Missing required arXiv field: {path}")
    return value


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _parse_arxiv_datetime(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    return parsed.astimezone(timezone.utc)


def _extract_arxiv_id(url: str) -> str | None:
    marker = "/abs/"
    if marker not in url:
        return None
    arxiv_id = url.rsplit(marker, 1)[-1]
    return arxiv_id.split("v", 1)[0]
