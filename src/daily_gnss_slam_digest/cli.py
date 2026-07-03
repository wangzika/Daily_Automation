from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from .arxiv_client import ArxivClient
from .assets import ensure_article_assets
from .article import build_digest, build_html, build_title, write_outputs
from .config import DEFAULT_OUTPUT_DIR, TOPICS
from .notify import describe_notification_result, notify_draft_created, notify_publish_issue
from .recommender import recommend
from .sample_data import SAMPLE_PAPERS
from .wechat import WeChatConfig, WeChatPublisher, WeChatPublisherError


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    issue_date = date.fromisoformat(args.issue_date) if args.issue_date else date.today()

    if args.sample:
        papers = SAMPLE_PAPERS
    else:
        client = ArxivClient()
        papers = client.search_many([topic.query for topic in TOPICS], max_results_per_query=args.per_topic)

    recommendations = recommend(papers, limit=args.limit, days_back=args.days_back)
    if not recommendations:
        print("No matching papers found.", file=sys.stderr)
        return 2

    asset_paths = ensure_article_assets(args.output_dir, issue_date)
    local_image_paths = {key: path.name for key, path in asset_paths.items()}
    paths = write_outputs(
        recommendations,
        issue_date=issue_date,
        output_dir=args.output_dir,
        image_paths=local_image_paths,
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
    digest = build_digest(recommendations)
    source_url = recommendations[0].paper.url

    try:
        config = WeChatConfig.from_env()
        publisher = WeChatPublisher(config)
        access_token = publisher.get_access_token()
        article_image_urls = {
            key: publisher.upload_article_image(access_token, path)
            for key, path in asset_paths.items()
        }
        html_content = build_html(recommendations, issue_date, image_urls=article_image_urls)
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
    parser.add_argument("--per-topic", type=int, default=int(os.getenv("DIGEST_PER_TOPIC", "25")))
    parser.add_argument("--issue-date", help="Override issue date, format YYYY-MM-DD.")
    parser.add_argument("--publish-mode", choices=("none", "draft", "publish"), default=None)
    parser.add_argument("--sample", action="store_true", help="Use bundled sample papers instead of querying arXiv.")
    return parser.parse_args(argv)
