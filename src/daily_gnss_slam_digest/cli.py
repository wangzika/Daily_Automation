from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from .arxiv_client import ArxivClient, ArxivClientError
from .assets import ensure_article_assets
from .article import build_digest, build_html, build_title, write_outputs
from .config import (
    DEFAULT_OUTPUT_DIR,
    ROTATING_TOPICS,
    TOPICS,
    arxiv_query_from_keywords,
    parse_keyword_text,
    rotating_topic_for_date,
    topic_from_keywords,
)
from .crossref import CrossrefClient, CrossrefError
from .models import Paper, RecommendedPaper
from .notify import describe_notification_result, notify_draft_created, notify_publish_issue
from .openalex import OpenAlexClient, OpenAlexError
from .recommender import recommend
from .sample_data import SAMPLE_PAPERS
from .semantic_scholar import SemanticScholarClient, SemanticScholarError, enrich_papers
from .wechat import WeChatConfig, WeChatPublisher, WeChatPublisherError


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    issue_date = date.fromisoformat(args.issue_date) if args.issue_date else date.today()
    keywords = parse_keyword_text(args.keywords)
    focus_topic = ""
    next_focus_topic = ""
    fallback_queries: list[str] = []
    fallback_topics = ROTATING_TOPICS
    arxiv_failed = False
    fallback_sources = _fallback_sources(args.fallback_sources)
    if keywords:
        custom_topic = topic_from_keywords(keywords)
        search_queries = [custom_topic.query]
        scoring_topics = (custom_topic, *TOPICS)
        focus_topic = custom_topic.cn_name
        print(f"Using custom paper keywords: {', '.join(keywords)}")
        print(f"Custom arXiv query: {arxiv_query_from_keywords(keywords)}")
    elif args.topic_rotation == "on":
        rotating_topic = rotating_topic_for_date(issue_date)
        search_queries = [rotating_topic.query]
        scoring_topics = (rotating_topic,)
        fallback_queries = [topic.query for topic in ROTATING_TOPICS]
        focus_topic = rotating_topic.cn_name
        next_focus_topic = rotating_topic_for_date(issue_date + timedelta(days=1)).cn_name
        print(f"Using rotating daily topic: {rotating_topic.cn_name} ({rotating_topic.name})")
    else:
        search_queries = [topic.query for topic in TOPICS]
        scoring_topics = TOPICS
        focus_topic = "GNSS/融合/SLAM 综合方向"

    if args.from_json:
        loaded_recommendations = _load_recommendations_from_json(args.from_json)
        if not loaded_recommendations:
            print(f"No recommendations found in JSON: {args.from_json}", file=sys.stderr)
            return 2
        print(f"Using existing digest JSON: {args.from_json}")
        recommendations = _rerank_loaded_recommendations(
            loaded_recommendations,
            limit=args.limit,
            days_back=args.days_back,
            topics=scoring_topics,
            issue_date=issue_date,
        )
        if recommendations:
            print(f"Filtered existing digest JSON to current topic profile: {focus_topic}")
        else:
            recommendations = loaded_recommendations[: args.limit]
            focus_topic = "历史推荐综合补位"
            print("Existing digest JSON has no strong match for today's topic; using a neutral fallback title.")
        papers = []
    elif args.sample:
        papers = SAMPLE_PAPERS
    else:
        papers = []
        search_source = "arxiv"
        try:
            papers = _search_arxiv(args, search_queries)
        except ArxivClientError as exc:
            arxiv_failed = True
            print(f"arXiv search failed: {exc}", file=sys.stderr)
            search_source = "fallback"
            if "semantic-scholar" in fallback_sources:
                semantic_queries = _fallback_queries_for_topics(scoring_topics, keywords)
                try:
                    papers = _search_semantic_scholar(args, semantic_queries)
                    if papers:
                        search_source = "semantic-scholar"
                        print(f"Using Semantic Scholar fallback papers: {len(papers)}")
                except SemanticScholarError as semantic_exc:
                    print(f"Semantic Scholar fallback failed: {semantic_exc}", file=sys.stderr)
            if not papers and "openalex" in fallback_sources:
                try:
                    papers = _search_openalex(args, _fallback_queries_for_topics(scoring_topics, keywords))
                    if papers:
                        search_source = "openalex"
                        print(f"Using OpenAlex fallback papers: {len(papers)}")
                except OpenAlexError as openalex_exc:
                    print(f"OpenAlex fallback failed: {openalex_exc}", file=sys.stderr)
            if not papers and "crossref" in fallback_sources:
                try:
                    papers = _search_crossref(args, _fallback_queries_for_topics(scoring_topics, keywords))
                    if papers:
                        search_source = "crossref"
                        print(f"Using Crossref fallback papers: {len(papers)}")
                except CrossrefError as crossref_exc:
                    print(f"Crossref fallback failed: {crossref_exc}", file=sys.stderr)
            if not papers and "existing-json" in fallback_sources:
                existing_json = _digest_json_path(args.output_dir, issue_date)
                if existing_json.exists():
                    loaded_recommendations = _load_recommendations_from_json(existing_json)
                    recommendations = _rerank_loaded_recommendations(
                        loaded_recommendations,
                        limit=args.limit,
                        days_back=args.days_back,
                        topics=scoring_topics,
                        issue_date=issue_date,
                    )
                    if recommendations:
                        print(f"Using existing digest JSON fallback: {existing_json}")
                        papers = []
                        args.from_json = existing_json
                    else:
                        print(f"Existing digest JSON fallback had no topic match: {existing_json}", file=sys.stderr)

    if args.semantic_scholar == "on" and not args.sample and not args.from_json and papers and search_source != "semantic-scholar":
        print(f"Enriching up to {args.quality_enrich_limit} papers with Semantic Scholar metadata.")
        papers = enrich_papers(
            papers,
            client=SemanticScholarClient(),
            max_papers=args.quality_enrich_limit,
            delay_seconds=args.semantic_scholar_delay,
        )

    if not args.from_json:
        recommendations = recommend(papers, limit=args.limit, days_back=args.days_back, topics=scoring_topics)
    if not recommendations and arxiv_failed and not args.sample and not args.from_json:
        current_queries = _fallback_queries_for_topics(scoring_topics, keywords)
        for source in fallback_sources:
            if source in {search_source, "existing-json"}:
                continue
            try:
                papers = _search_named_fallback(args, source, current_queries)
            except (SemanticScholarError, OpenAlexError, CrossrefError) as exc:
                print(f"{source} fallback failed after topic scoring: {exc}", file=sys.stderr)
                continue
            recommendations = recommend(papers, limit=args.limit, days_back=args.days_back, topics=scoring_topics)
            if recommendations:
                search_source = source
                print(f"Using {source} fallback after topic scoring: {len(papers)}")
                break
        if not recommendations and "existing-json" in fallback_sources:
            existing_json = _digest_json_path(args.output_dir, issue_date)
            if existing_json.exists():
                recommendations = _rerank_loaded_recommendations(
                    _load_recommendations_from_json(existing_json),
                    limit=args.limit,
                    days_back=args.days_back,
                    topics=scoring_topics,
                    issue_date=issue_date,
                )
                if recommendations:
                    print(f"Using existing digest JSON fallback after topic scoring: {existing_json}")
                    args.from_json = existing_json
    if not recommendations and fallback_queries and not args.sample:
        print("No strong match for today's rotating topic. Falling back to all rotating hot topics.", file=sys.stderr)
        papers = []
        if not arxiv_failed:
            try:
                papers = _search_arxiv(args, fallback_queries, max_results=max(args.per_topic // 2, 10))
                search_source = "arxiv"
            except ArxivClientError as exc:
                arxiv_failed = True
                print(f"arXiv hot-topic fallback failed: {exc}", file=sys.stderr)
        if not papers and "semantic-scholar" in fallback_sources:
            try:
                papers = _search_semantic_scholar(args, _fallback_queries_for_topics(fallback_topics, ()))
                search_source = "semantic-scholar"
            except SemanticScholarError as exc:
                print(f"Semantic Scholar hot-topic fallback failed: {exc}", file=sys.stderr)
        if not papers and "openalex" in fallback_sources:
            try:
                papers = _search_openalex(args, _fallback_queries_for_topics(fallback_topics, ()))
                search_source = "openalex"
            except OpenAlexError as exc:
                print(f"OpenAlex hot-topic fallback failed: {exc}", file=sys.stderr)
        if not papers and "crossref" in fallback_sources:
            try:
                papers = _search_crossref(args, _fallback_queries_for_topics(fallback_topics, ()))
                search_source = "crossref"
            except CrossrefError as exc:
                print(f"Crossref hot-topic fallback failed: {exc}", file=sys.stderr)
        if args.semantic_scholar == "on" and papers and search_source != "semantic-scholar":
            papers = enrich_papers(
                papers,
                client=SemanticScholarClient(),
                max_papers=args.quality_enrich_limit,
                delay_seconds=args.semantic_scholar_delay,
            )
        recommendations = recommend(papers, limit=args.limit, days_back=args.days_back, topics=fallback_topics)
        focus_topic = "七日轮换热点综合补位"
    if not recommendations:
        print("No matching papers found.", file=sys.stderr)
        return 2

    asset_paths = ensure_article_assets(args.output_dir, issue_date, focus_topic=focus_topic)
    local_image_paths = {key: path.name for key, path in asset_paths.items()}
    paths = write_outputs(
        recommendations,
        issue_date=issue_date,
        output_dir=args.output_dir,
        image_paths=local_image_paths,
        focus_topic=focus_topic,
        next_focus_topic=next_focus_topic,
    )
    print(f"Wrote markdown: {paths['markdown']}")
    print(f"Wrote html: {paths['html']}")
    print(f"Wrote json: {paths['json']}")
    for key, path in asset_paths.items():
        print(f"Wrote image {key}: {path}")

    publish_mode = args.publish_mode or os.getenv("WECHAT_PUBLISH_MODE", "none")
    if publish_mode == "none":
        return 0

    title = build_title(issue_date)
    digest = build_digest(recommendations, focus_topic=focus_topic)
    source_url = recommendations[0].paper.url

    try:
        config = WeChatConfig.from_env()
        publisher = WeChatPublisher(config)
        access_token = publisher.get_access_token()
        article_image_urls = {
            key: publisher.upload_article_image(access_token, path)
            for key, path in asset_paths.items()
        }
        html_content = build_html(
            recommendations,
            issue_date,
            image_urls=article_image_urls,
            focus_topic=focus_topic,
            next_focus_topic=next_focus_topic,
        )
        media_id = publisher.add_draft(
            access_token=access_token,
            title=title,
            content_html=html_content,
            digest=digest,
            content_source_url=source_url,
        )
        print(f"Created WeChat draft media_id: {media_id}")
        print(
            describe_notification_result(
                notify_draft_created(
                    article_type="每日论文推荐",
                    title=title,
                    media_id=media_id,
                    publish_mode=publish_mode,
                    local_paths=(paths["html"], paths["markdown"], paths["json"]),
                    source_url=source_url,
                )
            )
        )
        if publish_mode == "publish":
            try:
                result = publisher.submit_publish(access_token=access_token, media_id=media_id)
                print(f"Submitted WeChat publish request: {result}")
            except WeChatPublisherError as exc:
                print(
                    describe_notification_result(
                        notify_publish_issue(
                            article_type="每日论文推荐",
                            title=title,
                            media_id=media_id,
                            reason=str(exc),
                        )
                    )
                )
                print(
                    "WeChat publish submit failed after draft creation. "
                    f"Draft media_id was kept: {media_id}. Error: {exc}",
                    file=sys.stderr,
                )
                return 4
    except WeChatPublisherError as exc:
        print(f"WeChat publish failed: {exc}", file=sys.stderr)
        return 3

    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a daily GNSS spoofing, multimodal fusion, and SLAM paper digest."
    )
    parser.add_argument("--output-dir", type=Path, default=Path(os.getenv("DIGEST_OUTPUT_DIR", DEFAULT_OUTPUT_DIR)))
    parser.add_argument("--limit", type=int, default=int(os.getenv("DIGEST_LIMIT", "5")))
    parser.add_argument("--days-back", type=int, default=int(os.getenv("DIGEST_DAYS_BACK", "180")))
    parser.add_argument("--per-topic", type=int, default=int(os.getenv("DIGEST_PER_TOPIC", "10")))
    parser.add_argument("--arxiv-retries", type=int, default=int(os.getenv("ARXIV_RETRIES", "3")))
    parser.add_argument(
        "--arxiv-retry-delay",
        type=float,
        default=float(os.getenv("ARXIV_RETRY_DELAY_SECONDS", "10.0")),
    )
    parser.add_argument(
        "--arxiv-min-delay",
        type=float,
        default=float(os.getenv("ARXIV_MIN_DELAY_SECONDS", "3.5")),
        help="Minimum delay between live arXiv requests.",
    )
    parser.add_argument(
        "--arxiv-cache-dir",
        type=Path,
        default=Path(os.getenv("ARXIV_CACHE_DIR", "outputs/cache/arxiv")),
        help="Local cache directory for raw arXiv API responses.",
    )
    parser.add_argument(
        "--arxiv-cache-ttl-hours",
        type=float,
        default=float(os.getenv("ARXIV_CACHE_TTL_HOURS", "26")),
        help="Fresh-cache window for arXiv API responses.",
    )
    parser.add_argument("--issue-date", help="Override issue date, format YYYY-MM-DD.")
    parser.add_argument("--publish-mode", choices=("none", "draft", "publish"), default=None)
    parser.add_argument(
        "--keywords",
        default=os.getenv("DIGEST_KEYWORDS", ""),
        help="Comma/semicolon separated paper keywords. When set, arXiv search is driven by these keywords.",
    )
    parser.add_argument("--sample", action="store_true", help="Use bundled sample papers instead of querying arXiv.")
    parser.add_argument(
        "--from-json",
        type=Path,
        help="Re-render and optionally publish an existing digest JSON without querying arXiv.",
    )
    parser.add_argument(
        "--semantic-scholar",
        choices=("off", "on"),
        default=os.getenv("SEMANTIC_SCHOLAR_ENRICH", "off"),
        help="Enrich arXiv papers with citation and venue metadata from Semantic Scholar.",
    )
    parser.add_argument(
        "--quality-enrich-limit",
        type=int,
        default=int(os.getenv("QUALITY_ENRICH_LIMIT", "30")),
        help="Maximum number of candidate papers to enrich with external quality metadata.",
    )
    parser.add_argument(
        "--semantic-scholar-delay",
        type=float,
        default=float(os.getenv("SEMANTIC_SCHOLAR_DELAY_SECONDS", "1.0")),
        help="Delay between Semantic Scholar requests, in seconds.",
    )
    parser.add_argument(
        "--semantic-scholar-search-limit",
        type=int,
        default=int(os.getenv("SEMANTIC_SCHOLAR_SEARCH_LIMIT", "25")),
        help="Maximum Semantic Scholar fallback papers per query.",
    )
    parser.add_argument(
        "--openalex-search-limit",
        type=int,
        default=int(os.getenv("OPENALEX_SEARCH_LIMIT", "25")),
        help="Maximum OpenAlex fallback papers per query.",
    )
    parser.add_argument(
        "--openalex-delay",
        type=float,
        default=float(os.getenv("OPENALEX_DELAY_SECONDS", "1.0")),
        help="Delay between OpenAlex fallback requests, in seconds.",
    )
    parser.add_argument(
        "--crossref-search-limit",
        type=int,
        default=int(os.getenv("CROSSREF_SEARCH_LIMIT", "25")),
        help="Maximum Crossref fallback papers per query.",
    )
    parser.add_argument(
        "--crossref-delay",
        type=float,
        default=float(os.getenv("CROSSREF_DELAY_SECONDS", "1.0")),
        help="Delay between Crossref fallback requests, in seconds.",
    )
    parser.add_argument(
        "--fallback-sources",
        default=os.getenv("PAPER_FALLBACK_SOURCES", "semantic-scholar,openalex,crossref,existing-json"),
        help="Comma separated fallback sources after arXiv failure: semantic-scholar, openalex, crossref, existing-json, or off.",
    )
    parser.add_argument(
        "--topic-rotation",
        choices=("on", "off"),
        default=os.getenv("TOPIC_ROTATION_ENABLED", "on"),
        help="Use a weekday rotating hot topic when no custom keywords are provided.",
    )
    return parser.parse_args(argv)


def _load_recommendations_from_json(path: Path) -> list[RecommendedPaper]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return []
    recommendations: list[RecommendedPaper] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        paper = Paper(
            title=str(item.get("title") or "Untitled"),
            authors=tuple(str(author) for author in _list_value(item.get("authors"))),
            abstract=str(item.get("abstract") or ""),
            url=str(item.get("url") or ""),
            pdf_url=_optional_str(item.get("pdf_url")),
            published=_datetime_value(item.get("published")),
            updated=_datetime_value(item.get("updated") or item.get("published")),
            categories=tuple(str(category) for category in _list_value(item.get("categories"))),
            primary_category=_optional_str(item.get("primary_category")),
            arxiv_id=_optional_str(item.get("arxiv_id")),
            comment=_optional_str(item.get("comment")),
            journal_ref=_optional_str(item.get("journal_ref")),
            doi=_optional_str(item.get("doi")),
            citation_count=_optional_int(item.get("citation_count")),
            influential_citation_count=_optional_int(item.get("influential_citation_count")),
            venue=_optional_str(item.get("venue")),
            code_url=_optional_str(item.get("code_url")),
        )
        recommendations.append(
            RecommendedPaper(
                paper=paper,
                score=float(item.get("score") or 0.0),
                topic_scores={str(key): float(value) for key, value in _dict_value(item.get("topic_scores")).items()},
                matched_terms=tuple(str(term) for term in _list_value(item.get("matched_terms"))),
                quality_score=float(item.get("quality_score") or 0.0),
                quality_signals=_dict_value(item.get("quality_signals")),
                reason=str(item.get("reason") or ""),
            )
        )
    return recommendations


def _search_arxiv(args: argparse.Namespace, queries: list[str], max_results: int | None = None) -> list[Paper]:
    client = ArxivClient(
        retries=args.arxiv_retries,
        retry_delay_seconds=args.arxiv_retry_delay,
        min_delay_seconds=args.arxiv_min_delay,
        cache_dir=args.arxiv_cache_dir,
        cache_ttl_hours=args.arxiv_cache_ttl_hours,
    )
    return client.search_many(queries, max_results_per_query=max_results or args.per_topic)


def _search_semantic_scholar(args: argparse.Namespace, queries: list[str]) -> list[Paper]:
    client = SemanticScholarClient()
    return client.search_many(
        queries,
        limit_per_query=args.semantic_scholar_search_limit,
        delay_seconds=args.semantic_scholar_delay,
    )


def _search_openalex(args: argparse.Namespace, queries: list[str]) -> list[Paper]:
    client = OpenAlexClient()
    return client.search_many(
        queries,
        limit_per_query=args.openalex_search_limit,
        delay_seconds=args.openalex_delay,
    )


def _search_crossref(args: argparse.Namespace, queries: list[str]) -> list[Paper]:
    client = CrossrefClient()
    return client.search_many(
        queries,
        limit_per_query=args.crossref_search_limit,
        delay_seconds=args.crossref_delay,
    )


def _search_named_fallback(args: argparse.Namespace, source: str, queries: list[str]) -> list[Paper]:
    if source == "semantic-scholar":
        return _search_semantic_scholar(args, queries)
    if source == "openalex":
        return _search_openalex(args, queries)
    if source == "crossref":
        return _search_crossref(args, queries)
    return []


def _fallback_queries_for_topics(topics: tuple[Any, ...], keywords: tuple[str, ...]) -> list[str]:
    if keywords:
        return [" ".join(keywords)]
    queries: list[str] = []
    for topic in topics:
        topic_keywords = getattr(topic, "keywords", {})
        if not isinstance(topic_keywords, dict):
            continue
        terms = [
            str(term)
            for term, _weight in sorted(topic_keywords.items(), key=lambda item: float(item[1]), reverse=True)[:7]
        ]
        if terms:
            queries.append(" ".join(terms))
    return queries


def _semantic_queries_for_topics(topics: tuple[Any, ...], keywords: tuple[str, ...]) -> list[str]:
    return _fallback_queries_for_topics(topics, keywords)


def _fallback_sources(value: str) -> tuple[str, ...]:
    values = parse_keyword_text(value.lower().replace("off", ""))
    allowed = {"semantic-scholar", "openalex", "crossref", "existing-json"}
    return tuple(source for source in values if source in allowed)


def _digest_json_path(output_dir: Path, issue_date: date) -> Path:
    return output_dir / f"{issue_date.isoformat()}-gnss-slam-digest.json"


def _rerank_loaded_recommendations(
    recommendations: list[RecommendedPaper],
    *,
    limit: int,
    days_back: int,
    topics: tuple[Any, ...],
    issue_date: date,
) -> list[RecommendedPaper]:
    papers = [item.paper for item in recommendations]
    now = datetime.combine(issue_date, time.max, tzinfo=timezone.utc)
    return recommend(papers, limit=limit, days_back=days_back, now=now, topics=topics)


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _datetime_value(value: Any) -> datetime:
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value)
    return datetime.now(timezone.utc)
