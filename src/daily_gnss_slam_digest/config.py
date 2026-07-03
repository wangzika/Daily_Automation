from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


PROJECT_TITLE = "每日 GNSS 欺骗检测 / 多模态融合 / SLAM 论文推荐"


@dataclass(frozen=True)
class TopicProfile:
    name: str
    cn_name: str
    query: str
    keywords: dict[str, float]


TOPICS: tuple[TopicProfile, ...] = (
    TopicProfile(
        name="gnss_security",
        cn_name="GNSS 欺骗与干扰检测",
        query='(all:"GNSS spoofing" OR all:"GPS spoofing" OR all:"GNSS interference" OR all:"GNSS jamming" OR all:"PNT integrity")',
        keywords={
            "gnss": 8.0,
            "gps": 5.0,
            "spoofing": 10.0,
            "jamming": 8.0,
            "interference": 7.0,
            "pnt": 5.0,
            "integrity": 5.0,
            "anomaly": 4.0,
            "attack": 4.0,
            "detection": 6.0,
            "ais": 3.0,
            "receiver": 3.0,
        },
    ),
    TopicProfile(
        name="multimodal_fusion",
        cn_name="多模态/多传感器融合",
        query='(all:"sensor fusion" OR all:"multi-sensor" OR all:"multimodal fusion" OR all:"LiDAR-Inertial-Visual" OR all:"visual-inertial" OR all:"GNSS fusion")',
        keywords={
            "fusion": 9.0,
            "multi-sensor": 7.0,
            "multimodal": 7.0,
            "lidar": 5.0,
            "visual": 4.0,
            "camera": 4.0,
            "inertial": 5.0,
            "imu": 5.0,
            "gnss": 5.0,
            "tightly coupled": 5.0,
            "kalman": 4.0,
            "factor graph": 4.0,
        },
    ),
    TopicProfile(
        name="slam_odometry",
        cn_name="SLAM 与鲁棒里程计",
        query='(all:SLAM OR all:"simultaneous localization and mapping" OR all:odometry OR all:"loop closure" OR all:"place recognition")',
        keywords={
            "slam": 9.0,
            "odometry": 8.0,
            "localization": 5.0,
            "mapping": 5.0,
            "loop": 4.0,
            "place recognition": 4.0,
            "lio": 4.0,
            "vio": 4.0,
            "livo": 5.0,
            "degeneracy": 5.0,
            "robust": 3.0,
            "gaussian": 3.0,
        },
    ),
)


DEFAULT_OUTPUT_DIR = Path("outputs")


def parse_keyword_text(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    parts = re.split(r"[,;，；\n]+", value)
    return tuple(dict.fromkeys(part.strip() for part in parts if part.strip()))


def arxiv_query_from_keywords(keywords: tuple[str, ...]) -> str:
    terms = [_arxiv_all_term(keyword) for keyword in keywords if keyword.strip()]
    if not terms:
        return ""
    return "(" + " OR ".join(terms) + ")"


def topic_from_keywords(keywords: tuple[str, ...]) -> TopicProfile:
    weights: dict[str, float] = {}
    for keyword in keywords:
        keyword = " ".join(keyword.lower().split())
        if keyword:
            weights[keyword] = 9.0 if " " in keyword or "-" in keyword else 6.0
    return TopicProfile(
        name="custom_keywords",
        cn_name="邮件指定关键词",
        query=arxiv_query_from_keywords(keywords),
        keywords=weights,
    )


def _arxiv_all_term(keyword: str) -> str:
    cleaned = " ".join(keyword.replace('"', " ").split())
    if not cleaned:
        return ""
    if " " in cleaned or "-" in cleaned:
        return f'all:"{cleaned}"'
    return f"all:{cleaned}"
