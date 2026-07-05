# 每周 GNSS/融合/SLAM 热点汇总 | 2026-07-05

本周共聚合 12 篇日报候选论文，覆盖日期：2026-07-03, 2026-07-04, 2026-07-05。

## 热点方向

1. SLAM/里程计鲁棒性（8）
2. 可复现代码与开源实现（6）
3. 多模态融合与传感器退化处理（5）
4. GNSS 完整性与欺骗/干扰检测（4）
5. 数据集与 benchmark（4）

## 机器人领域热点雷达

1. 退化场景多模态融合与鲁棒里程计（8）
2. 韧性 PNT 与 GNSS 抗欺骗抗干扰（4）
3. 3DGS/NeRF 神经场 SLAM（4）
4. 多机器人协同 SLAM 与分布式建图（4）

## 高频主题

1. SLAM 与鲁棒里程计（4）
2. 退化场景多模态融合与鲁棒里程计（4）
3. 多模态/多传感器融合（3）
4. 韧性 PNT 与 GNSS 抗欺骗抗干扰（3）
5. GNSS 欺骗与干扰检测（1）

## 高频关键词

1. odometry（8）
2. gnss（6）
3. loop（4）
4. robust（4）
5. spoofing（3）
6. fusion（3）
7. visual（3）
8. slam（3）
9. localization（3）
10. visual-inertial（3）
11. gps（2）
12. interference（2）
13. integrity（2）
14. camera（2）
15. mapping（2）
16. degeneracy（2）

## 本周最值得追的论文

1. **AUSLUN: A Fixed-Hover UAV--USV System for GNSS-Denied Maritime Search and Navigation**
   - 质量分：14.0
   - 质量信号：质量分 14.0；venue NAVIGATION；代码开源；真实实验
   - 链接：http://arxiv.org/abs/2606.29875v1
2. **DL-VINS-Factory: A Modular Framework for Learned Visual Front-Ends in Visual-Inertial SLAM**
   - 质量分：8.5
   - 质量信号：质量分 8.5；代码开源；数据集/benchmark
   - 链接：http://arxiv.org/abs/2607.01757v1
3. **Efficient Network Inference via Hardware-Aware Architecture Search, Model Pruning & Quantization**
   - 质量分：8.5
   - 质量信号：质量分 8.5；venue NAVIGATION；数据集/benchmark
   - 链接：http://arxiv.org/abs/2606.23210v1
4. **LXD-SLAM: LiDAR+X Dense SLAM with $\sum_{i=0}^{5}C_5^i$ Configurable Sensor Combinations**
   - 质量分：8.0
   - 质量信号：质量分 8.0；代码开源；真实实验
   - 链接：http://arxiv.org/abs/2606.27811v1
5. **GNSS Spoofing Threat for V2X communications**
   - 质量分：8.0
   - 质量信号：质量分 8.0；venue NAVIGATION；真实实验
   - 链接：http://arxiv.org/abs/2606.20215v1
6. **FAR-LIO: Enabling High-Speed Autonomy through Fast, Accurate, and Robust LiDAR-Inertial Odometry**
   - 质量分：6.0
   - 质量信号：质量分 6.0；代码开源
   - 链接：http://arxiv.org/abs/2606.26010v1
7. **A Conditional Timing Protection Level: Holdover-Limited Undetected Time Error Under GNSS Spoofing**
   - 质量分：5.5
   - 质量信号：质量分 5.5；有代码线索；数据集/benchmark
   - 链接：http://arxiv.org/abs/2606.24210v1
8. **SA-LIVO: Efficient LiDAR-Inertial-Visual Odometry with Subspace-Aware Degeneracy Handling**
   - 质量分：3.0
   - 质量信号：质量分 3.0；有代码线索
   - 链接：http://arxiv.org/abs/2606.25699v1

## 有代码/复现线索

- **AUSLUN: A Fixed-Hover UAV--USV System for GNSS-Denied Maritime Search and Navigation**：质量分 14.0；venue NAVIGATION；代码开源；真实实验；http://arxiv.org/abs/2606.29875v1
- **DL-VINS-Factory: A Modular Framework for Learned Visual Front-Ends in Visual-Inertial SLAM**：质量分 8.5；代码开源；数据集/benchmark；http://arxiv.org/abs/2607.01757v1
- **LXD-SLAM: LiDAR+X Dense SLAM with $\sum_{i=0}^{5}C_5^i$ Configurable Sensor Combinations**：质量分 8.0；代码开源；真实实验；http://arxiv.org/abs/2606.27811v1
- **FAR-LIO: Enabling High-Speed Autonomy through Fast, Accurate, and Robust LiDAR-Inertial Odometry**：质量分 6.0；代码开源；http://arxiv.org/abs/2606.26010v1
- **A Conditional Timing Protection Level: Holdover-Limited Undetected Time Error Under GNSS Spoofing**：质量分 5.5；有代码线索；数据集/benchmark；http://arxiv.org/abs/2606.24210v1

## 有 venue / 引用线索

- **AUSLUN: A Fixed-Hover UAV--USV System for GNSS-Denied Maritime Search and Navigation**：质量分 14.0；venue NAVIGATION；代码开源；真实实验；http://arxiv.org/abs/2606.29875v1
- **Efficient Network Inference via Hardware-Aware Architecture Search, Model Pruning & Quantization**：质量分 8.5；venue NAVIGATION；数据集/benchmark；http://arxiv.org/abs/2606.23210v1
- **GNSS Spoofing Threat for V2X communications**：质量分 8.0；venue NAVIGATION；真实实验；http://arxiv.org/abs/2606.20215v1

## 编辑观察

本周最值得继续跟踪的是 SLAM/里程计鲁棒性、可复现代码与开源实现、多模态融合与传感器退化处理。放到更宽的机器人领域看，退化场景多模态融合与鲁棒里程计、韧性 PNT 与 GNSS 抗欺骗抗干扰、3DGS/NeRF 神经场 SLAM 的信号最强。关键词上，odometry、gnss、loop、robust、spoofing、fusion 出现频率较高；后续选题可以优先挑有代码、真实实验或明确 venue/引用信号的论文做深度解读。

> 正式引用实验结论前，建议回到原文核对数据集、指标和实验设置。
