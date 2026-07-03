from __future__ import annotations

from datetime import datetime, timezone

from .models import Paper


SAMPLE_PAPERS: list[Paper] = [
    Paper(
        title="FAST-LIVGO: A Degeneracy-Robust LiDAR-Inertial-Visual-GNSS Fusion Odometry",
        authors=("Zhiyu Chen", "Chunran Zheng", "Jiayu Wen", "XiaoLei Zhang", "Jiaming Xu", "Feng Pan", "Yukang Cui"),
        abstract="Robust state estimation and mapping in long-term, large-scale, and highly dynamic environments remains a key challenge in robotics. The paper proposes a tightly coupled LiDAR-Inertial-Visual-GNSS fusion framework based on an Error-State Iterated Kalman Filter, with online spatiotemporal alignment, Doppler and carrier-phase constraints, and degeneracy-aware outlier rejection.",
        url="https://arxiv.org/abs/2606.19190",
        pdf_url="https://arxiv.org/pdf/2606.19190",
        published=datetime(2026, 6, 17, 15, 33, 11, tzinfo=timezone.utc),
        updated=datetime(2026, 6, 17, 15, 33, 11, tzinfo=timezone.utc),
        categories=("cs.RO",),
        primary_category="cs.RO",
        arxiv_id="2606.19190",
    ),
    Paper(
        title="Wide-Area GNSS Spoofing and Jamming Detection Using AIS-Derived Spatiotemporal Integrity Monitoring",
        authors=("Sanghyeon Park", "DeukJae Cho", "Pyo-Woong Son"),
        abstract="GNSS spoofing and jamming threaten maritime navigation by corrupting AIS positions. The paper proposes a three-stage AIS-based framework with rule-based filtering, interacting multiple model filtering, interval analysis, and spatiotemporal DBSCAN to classify sensor faults, spoofing, and jamming.",
        url="https://arxiv.org/abs/2603.11055",
        pdf_url="https://arxiv.org/pdf/2603.11055",
        published=datetime(2026, 2, 27, 16, 32, 1, tzinfo=timezone.utc),
        updated=datetime(2026, 2, 27, 16, 32, 1, tzinfo=timezone.utc),
        categories=("cs.CY", "eess.SP"),
        primary_category="cs.CY",
        arxiv_id="2603.11055",
    ),
    Paper(
        title="Quantum-Classical Hybrid Framework for Zero-Day Time-Push GNSS Spoofing Detection",
        authors=("Abyad Enan", "Mashrur Chowdhury", "Sagar Dasgupta", "Mizanur Rahman"),
        abstract="The paper studies zero-day GNSS time-push spoofing detection using a hybrid quantum-classical autoencoder trained only on authentic tracking-stage features. It targets proactive detection before PNT solutions are computed and evaluates unseen spoofing attacks.",
        url="https://arxiv.org/abs/2508.18085",
        pdf_url="https://arxiv.org/pdf/2508.18085",
        published=datetime(2025, 8, 25, 14, 46, 22, tzinfo=timezone.utc),
        updated=datetime(2025, 8, 25, 14, 46, 22, tzinfo=timezone.utc),
        categories=("cs.LG", "eess.SP"),
        primary_category="cs.LG",
        arxiv_id="2508.18085",
    ),
    Paper(
        title="GS-LIVO: Real-Time LiDAR, Inertial, and Visual Multi-sensor Fused Odometry with Gaussian Mapping",
        authors=("Sheng Hong", "Chunran Zheng", "Yishu Shen", "Changze Li", "Fu Zhang", "Tong Qin", "Shaojie Shen"),
        abstract="The paper proposes a real-time Gaussian-based SLAM system with LiDAR-Inertial-Visual sensor fusion. It combines an IESKF odometry module with an adaptive Gaussian map for resource-constrained embedded systems.",
        url="https://arxiv.org/abs/2501.08672",
        pdf_url="https://arxiv.org/pdf/2501.08672",
        published=datetime(2025, 1, 15, 9, 4, 56, tzinfo=timezone.utc),
        updated=datetime(2025, 1, 15, 9, 4, 56, tzinfo=timezone.utc),
        categories=("cs.RO",),
        primary_category="cs.RO",
        arxiv_id="2501.08672",
    ),
]
