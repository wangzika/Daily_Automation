# 每日 GNSS 欺骗检测 / 多模态融合 / SLAM 论文推荐 | 2026-07-05

![退化场景多模态融合与鲁棒里程计](2026-07-05-topic-header.jpg)

今天这期看 **退化场景多模态融合与鲁棒里程计**。

我挑了 5 篇最近值得看的论文，重点看视觉、激光、惯导和 GNSS 在退化场景里的互相补位。鲁棒里程计的关键不是传感器堆得多，而是知道什么时候该相信谁。

## 今日速览

1. **SA-LIVO: Efficient LiDAR-Inertial-Visual Odometry with Subspace-Aware Degeneracy Handling**
   - 作者：Yinong Cao, Xin He, Yuwei Chen, Shijie Liu 等
   - 日期：2026-06-24
   - 链接：http://arxiv.org/abs/2606.25699v1
   - 质量信号：质量分 3.0；有代码线索
   - 推荐理由：主题贴合 退化场景多模态融合与鲁棒里程计，关键词集中在 odometry、lidar-inertial、visual-inertial、livo、fusion、degeneracy、degradation。质量信号：有代码线索，适合作为今日跟踪论文。
2. **AUSLUN: A Fixed-Hover UAV--USV System for GNSS-Denied Maritime Search and Navigation**
   - 作者：Siyuan Yang, Zikai Jia, Hailiang Kuang, Xiaoyu He 等
   - 日期：2026-06-29
   - 链接：http://arxiv.org/abs/2606.29875v1
   - 质量信号：质量分 14.0；venue NAVIGATION；代码开源；真实实验
   - 推荐理由：主题贴合 退化场景多模态融合与鲁棒里程计，关键词集中在 odometry、visual-inertial、vio、gnss。质量信号：venue NAVIGATION、代码开源、强调真实实验，适合作为今日跟踪论文。
3. **FAR-LIO: Enabling High-Speed Autonomy through Fast, Accurate, and Robust LiDAR-Inertial Odometry**
   - 作者：Maximilian Leitenstern, Marcel Weinmann, Patrick Haft, Tobias Lasser 等
   - 日期：2026-06-24
   - 链接：http://arxiv.org/abs/2606.26010v1
   - 质量信号：质量分 6.0；代码开源
   - 推荐理由：主题贴合 退化场景多模态融合与鲁棒里程计，关键词集中在 robust、odometry、lidar-inertial、lio。质量信号：代码开源，适合作为今日跟踪论文。
4. **Cross-Session 3D LiDAR and Camera Fusion for Robust Localization of Unmanned Aerial Vehicles in GPS-Denied Environments**
   - 作者：Cong Hoang Quach, Chi Thanh Vo, Dong LT. Tran, Truong Son Nguyen 等
   - 日期：2026-06-27
   - 链接：http://arxiv.org/abs/2606.28951v1
   - 质量信号：质量分 2.0；真实实验
   - 推荐理由：主题贴合 退化场景多模态融合与鲁棒里程计，关键词集中在 robust、odometry、visual-inertial、fusion。质量信号：强调真实实验，适合作为今日跟踪论文。
5. **Sphere-VIO: Fast and Robust Visual-Inertial Odometry via Unified Spherical Representation for Heterogeneous Multi-Camera Systems**
   - 作者：Yueteng Yang, Yusen Xie, Hao Wei, Qianhao Wang 等
   - 日期：2026-06-29
   - 链接：http://arxiv.org/abs/2606.29910v1
   - 质量信号：质量分 2.5；数据集/benchmark
   - 推荐理由：主题贴合 退化场景多模态融合与鲁棒里程计，关键词集中在 robust、odometry、visual-inertial、vio。质量信号：有数据集/benchmark 线索，适合作为今日跟踪论文。

## 重点推荐

### 1. SA-LIVO: Efficient LiDAR-Inertial-Visual Odometry with Subspace-Aware Degeneracy Handling

- **论文信息**：Yinong Cao, Xin He, Yuwei Chen, Shijie Liu 等；2026-06-24；cs.RO
- **原文链接**：http://arxiv.org/abs/2606.25699v1
- **关键词**：odometry、lidar-inertial、visual-inertial、livo、fusion、degeneracy、degradation
- **质量信号**：质量分 3.0；有代码线索
- **为什么值得读**：这篇论文同时覆盖 退化场景多模态融合与鲁棒里程计，并在标题/摘要中出现 odometry、lidar-inertial、visual-inertial、livo、fusion、degeneracy、degradation 等信号；质量侧还有 质量分 3.0；有代码线索。它适合用来观察该方向近期如何处理鲁棒性、异常检测或融合估计问题。
- **对 GNSS/融合/SLAM 系统的启发**：适合关注传感器时空同步、退化场景切换和外点剔除策略，这些通常决定系统能否从实验室走向实车/无人机部署。
- **摘要要点**：从题名与摘要看，论文主要关注 多传感器融合定位中的一致性、同步和退化处理；技术线索包括 odometry、lidar-inertial、visual-inertial、livo、fusion、degeneracy。阅读全文时建议重点看 融合框架、传感器缺失时的降级策略、外点剔除和实时性，再判断是否适合迁移到自己的工程链路。

### 2. AUSLUN: A Fixed-Hover UAV--USV System for GNSS-Denied Maritime Search and Navigation

- **论文信息**：Siyuan Yang, Zikai Jia, Hailiang Kuang, Xiaoyu He 等；2026-06-29；cs.RO
- **原文链接**：http://arxiv.org/abs/2606.29875v1
- **关键词**：odometry、visual-inertial、vio、gnss
- **质量信号**：质量分 14.0；venue NAVIGATION；代码开源；真实实验
- **为什么值得读**：这篇论文同时覆盖 退化场景多模态融合与鲁棒里程计，并在标题/摘要中出现 odometry、visual-inertial、vio、gnss 等信号；质量侧还有 质量分 14.0；venue NAVIGATION；代码开源；真实实验。它适合用来观察该方向近期如何处理鲁棒性、异常检测或融合估计问题。
- **对 GNSS/融合/SLAM 系统的启发**：可以从前端观测选择、后端约束建模和回环恢复三个角度拆解，判断它是否适合迁移到自己的 SLAM 栈。
- **摘要要点**：从题名与摘要看，论文主要关注 SLAM/里程计在复杂环境中的鲁棒状态估计；技术线索包括 odometry、visual-inertial、vio、gnss。阅读全文时建议重点看 前端几何建模、后端约束、回环或地图表达对鲁棒性的贡献，再判断是否适合迁移到自己的工程链路。

### 3. FAR-LIO: Enabling High-Speed Autonomy through Fast, Accurate, and Robust LiDAR-Inertial Odometry

- **论文信息**：Maximilian Leitenstern, Marcel Weinmann, Patrick Haft, Tobias Lasser 等；2026-06-24；cs.RO
- **原文链接**：http://arxiv.org/abs/2606.26010v1
- **关键词**：robust、odometry、lidar-inertial、lio
- **质量信号**：质量分 6.0；代码开源
- **为什么值得读**：这篇论文同时覆盖 退化场景多模态融合与鲁棒里程计，并在标题/摘要中出现 robust、odometry、lidar-inertial、lio 等信号；质量侧还有 质量分 6.0；代码开源。它适合用来观察该方向近期如何处理鲁棒性、异常检测或融合估计问题。
- **对 GNSS/融合/SLAM 系统的启发**：可以从前端观测选择、后端约束建模和回环恢复三个角度拆解，判断它是否适合迁移到自己的 SLAM 栈。
- **摘要要点**：从题名与摘要看，论文主要关注 SLAM/里程计在复杂环境中的鲁棒状态估计；技术线索包括 robust、odometry、lidar-inertial、lio。阅读全文时建议重点看 前端几何建模、后端约束、回环或地图表达对鲁棒性的贡献，再判断是否适合迁移到自己的工程链路。

### 4. Cross-Session 3D LiDAR and Camera Fusion for Robust Localization of Unmanned Aerial Vehicles in GPS-Denied Environments

- **论文信息**：Cong Hoang Quach, Chi Thanh Vo, Dong LT. Tran, Truong Son Nguyen 等；2026-06-27；cs.RO
- **原文链接**：http://arxiv.org/abs/2606.28951v1
- **关键词**：robust、odometry、visual-inertial、fusion
- **质量信号**：质量分 2.0；真实实验
- **为什么值得读**：这篇论文同时覆盖 退化场景多模态融合与鲁棒里程计，并在标题/摘要中出现 robust、odometry、visual-inertial、fusion 等信号；质量侧还有 质量分 2.0；真实实验。它适合用来观察该方向近期如何处理鲁棒性、异常检测或融合估计问题。
- **对 GNSS/融合/SLAM 系统的启发**：适合关注传感器时空同步、退化场景切换和外点剔除策略，这些通常决定系统能否从实验室走向实车/无人机部署。
- **摘要要点**：从题名与摘要看，论文主要关注 多传感器融合定位中的一致性、同步和退化处理；技术线索包括 robust、odometry、visual-inertial、fusion。阅读全文时建议重点看 融合框架、传感器缺失时的降级策略、外点剔除和实时性，再判断是否适合迁移到自己的工程链路。

### 5. Sphere-VIO: Fast and Robust Visual-Inertial Odometry via Unified Spherical Representation for Heterogeneous Multi-Camera Systems

- **论文信息**：Yueteng Yang, Yusen Xie, Hao Wei, Qianhao Wang 等；2026-06-29；cs.RO
- **原文链接**：http://arxiv.org/abs/2606.29910v1
- **关键词**：robust、odometry、visual-inertial、vio
- **质量信号**：质量分 2.5；数据集/benchmark
- **为什么值得读**：这篇论文同时覆盖 退化场景多模态融合与鲁棒里程计，并在标题/摘要中出现 robust、odometry、visual-inertial、vio 等信号；质量侧还有 质量分 2.5；数据集/benchmark。它适合用来观察该方向近期如何处理鲁棒性、异常检测或融合估计问题。
- **对 GNSS/融合/SLAM 系统的启发**：可以从前端观测选择、后端约束建模和回环恢复三个角度拆解，判断它是否适合迁移到自己的 SLAM 栈。
- **摘要要点**：从题名与摘要看，论文主要关注 SLAM/里程计在复杂环境中的鲁棒状态估计；技术线索包括 robust、odometry、visual-inertial、vio。阅读全文时建议重点看 前端几何建模、后端约束、回环或地图表达对鲁棒性的贡献，再判断是否适合迁移到自己的工程链路。

## 今日观察

鲁棒里程计最怕的是系统不知道自己已经不可靠。最近的趋势是把退化检测、传感器可信度和因子图约束放在一起，让系统在弱纹理、强动态、空旷或遮挡场景下有更平滑的降级能力。

## 明日检索关键词

`embodied navigation`、`vision-language navigation`、`object navigation`、`navigation foundation model`、`mobile robot policy`、`VLM navigation`。

> 具体实验结论建议回到原文核对后再引用。
