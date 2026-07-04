from __future__ import annotations

from dataclasses import dataclass
from datetime import date
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


ROTATING_TOPICS: tuple[TopicProfile, ...] = (
    TopicProfile(
        name="embodied_nav_foundation_models",
        cn_name="具身导航与机器人基础模型",
        query='(all:"embodied navigation" OR all:"vision-language navigation" OR all:"robot navigation" OR all:"navigation foundation model" OR all:"object navigation" OR all:"VLM navigation")',
        keywords={
            "embodied": 8.0,
            "navigation": 7.0,
            "vision-language": 8.0,
            "vlm": 6.0,
            "vla": 6.0,
            "foundation model": 8.0,
            "instruction": 4.0,
            "object navigation": 7.0,
            "goal-conditioned": 5.0,
            "mobile robot": 4.0,
            "policy": 4.0,
        },
    ),
    TopicProfile(
        name="neural_3d_slam",
        cn_name="3DGS/NeRF 神经场 SLAM",
        query='(all:"3D Gaussian Splatting" OR all:"Gaussian Splatting SLAM" OR all:"NeRF SLAM" OR all:"neural radiance field" OR all:"neural implicit SLAM" OR all:"dense visual SLAM")',
        keywords={
            "3d gaussian splatting": 10.0,
            "gaussian": 6.0,
            "splatting": 8.0,
            "nerf": 8.0,
            "neural radiance field": 9.0,
            "neural implicit": 8.0,
            "dense": 4.0,
            "slam": 8.0,
            "mapping": 5.0,
            "reconstruction": 5.0,
            "real-time": 4.0,
        },
    ),
    TopicProfile(
        name="open_vocabulary_semantic_mapping",
        cn_name="开放词汇语义地图与语言导航",
        query='(all:"open vocabulary" OR all:"semantic mapping" OR all:"language-guided navigation" OR all:"object goal navigation" OR all:"scene graph" OR all:"3D semantic map")',
        keywords={
            "open vocabulary": 10.0,
            "semantic": 7.0,
            "mapping": 5.0,
            "language-guided": 7.0,
            "object goal": 7.0,
            "scene graph": 7.0,
            "3d semantic": 7.0,
            "affordance": 5.0,
            "vlm": 5.0,
            "navigation": 5.0,
        },
    ),
    TopicProfile(
        name="place_recognition_long_term_localization",
        cn_name="地点识别与长期定位",
        query='(all:"visual place recognition" OR all:"LiDAR place recognition" OR all:"loop closure" OR all:"cross-modal place recognition" OR all:"long-term localization" OR all:"re-localization")',
        keywords={
            "place recognition": 10.0,
            "visual place recognition": 10.0,
            "lidar place recognition": 9.0,
            "loop closure": 8.0,
            "localization": 5.0,
            "re-localization": 6.0,
            "long-term": 6.0,
            "cross-modal": 6.0,
            "retrieval": 4.0,
            "descriptor": 4.0,
        },
    ),
    TopicProfile(
        name="collaborative_multi_robot_slam",
        cn_name="多机器人协同 SLAM 与分布式建图",
        query='(all:"multi-robot SLAM" OR all:"collaborative SLAM" OR all:"multi-agent localization" OR all:"distributed mapping" OR all:"cooperative localization" OR all:"communication-efficient SLAM")',
        keywords={
            "multi-robot": 9.0,
            "collaborative": 7.0,
            "multi-agent": 7.0,
            "distributed": 6.0,
            "cooperative localization": 8.0,
            "communication-efficient": 7.0,
            "slam": 8.0,
            "mapping": 5.0,
            "relative pose": 5.0,
            "decentralized": 6.0,
        },
    ),
    TopicProfile(
        name="resilient_pnt_gnss_denied",
        cn_name="韧性 PNT 与 GNSS 抗欺骗抗干扰",
        query='(all:"resilient PNT" OR all:"GNSS spoofing" OR all:"GNSS jamming" OR all:"GNSS interference" OR all:"PNT integrity" OR all:OSNMA OR all:"LEO PNT" OR all:"GNSS denied")',
        keywords={
            "resilient pnt": 10.0,
            "pnt": 6.0,
            "gnss": 8.0,
            "gps": 5.0,
            "spoofing": 10.0,
            "jamming": 9.0,
            "interference": 8.0,
            "integrity": 7.0,
            "osnma": 7.0,
            "leo pnt": 7.0,
            "gnss denied": 7.0,
            "c/n0": 5.0,
            "agc": 5.0,
        },
    ),
    TopicProfile(
        name="robust_multimodal_odometry",
        cn_name="退化场景多模态融合与鲁棒里程计",
        query='(all:"robust odometry" OR all:"LiDAR-inertial" OR all:"visual-inertial" OR all:"LiDAR visual inertial" OR all:"factor graph fusion" OR all:"degeneracy-aware" OR all:"sensor degradation")',
        keywords={
            "robust": 5.0,
            "odometry": 8.0,
            "lidar-inertial": 8.0,
            "visual-inertial": 8.0,
            "livo": 7.0,
            "lio": 6.0,
            "vio": 6.0,
            "factor graph": 6.0,
            "fusion": 8.0,
            "degeneracy": 7.0,
            "degradation": 6.0,
            "gnss": 4.0,
        },
    ),
)


ROBOTICS_TREND_TOPICS: tuple[TopicProfile, ...] = ROTATING_TOPICS + (
    TopicProfile(
        name="robot_world_models",
        cn_name="机器人 World Model 与长程规划",
        query='(all:"robot world model" OR all:"world model" OR all:"long-horizon planning" OR all:"model-based robot learning")',
        keywords={
            "world model": 10.0,
            "long-horizon": 7.0,
            "planning": 5.0,
            "model-based": 5.0,
            "robot learning": 6.0,
            "simulation": 4.0,
        },
    ),
    TopicProfile(
        name="humanoid_navigation",
        cn_name="人形机器人移动与全身导航",
        query='(all:humanoid OR all:"whole-body navigation" OR all:"legged navigation" OR all:"locomotion planning")',
        keywords={
            "humanoid": 9.0,
            "whole-body": 7.0,
            "legged": 6.0,
            "locomotion": 6.0,
            "navigation": 5.0,
            "planning": 4.0,
        },
    ),
    TopicProfile(
        name="robot_policy_learning",
        cn_name="机器人策略学习与 Sim2Real",
        query='(all:"robot policy" OR all:"imitation learning" OR all:"reinforcement learning" OR all:"sim-to-real" OR all:"diffusion policy")',
        keywords={
            "policy": 7.0,
            "imitation learning": 7.0,
            "reinforcement learning": 6.0,
            "sim-to-real": 7.0,
            "diffusion policy": 8.0,
            "robot learning": 6.0,
        },
    ),
)


def rotating_topic_for_date(issue_date: date) -> TopicProfile:
    return ROTATING_TOPICS[issue_date.weekday() % len(ROTATING_TOPICS)]


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
        cn_name="自定义研究主题",
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
