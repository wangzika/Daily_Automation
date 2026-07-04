# 每日 GNSS 欺骗检测 / 多模态融合 / SLAM 论文推荐 | 2026-07-04

![韧性 PNT 与 GNSS 抗欺骗抗干扰](2026-07-04-topic-header.jpg)

今天这期看 **韧性 PNT 与 GNSS 抗欺骗抗干扰**。

我挑了 3 篇最近值得看的论文，重点看 GNSS 异常、PNT 完整性和抗欺骗抗干扰。真正有用的工作不只报告检测率，还会说明误报从哪里来，以及定位系统怎样在告警后继续工作。

## 今日速览

1. **GNSS Spoofing Threat for V2X communications**
   - 作者：Adolfo P. Jimenez, Juan Arquero-Gallego, Mario P. Luna, Jose E. Naranjo 等
   - 日期：2026-06-18
   - 链接：http://arxiv.org/abs/2606.20215v1
   - 质量信号：质量分 8.0；venue NAVIGATION；真实实验
   - 推荐理由：主题贴合 韧性 PNT 与 GNSS 抗欺骗抗干扰，关键词集中在 pnt、gnss、gps、spoofing。质量信号：venue NAVIGATION、强调真实实验，适合作为今日跟踪论文。
2. **A Conditional Timing Protection Level: Holdover-Limited Undetected Time Error Under GNSS Spoofing**
   - 作者：Chakshu Baweja
   - 日期：2026-06-23
   - 链接：http://arxiv.org/abs/2606.24210v1
   - 质量信号：质量分 5.5；有代码线索；数据集/benchmark
   - 推荐理由：主题贴合 韧性 PNT 与 GNSS 抗欺骗抗干扰，关键词集中在 gnss、spoofing、integrity。质量信号：有代码线索、有数据集/benchmark 线索，适合作为今日跟踪论文。
3. **Efficient Network Inference via Hardware-Aware Architecture Search, Model Pruning & Quantization**
   - 作者：Lucas Heublein, Mark Deutel, Axel Plinge, Felix Ott
   - 日期：2026-06-22
   - 链接：http://arxiv.org/abs/2606.23210v1
   - 质量信号：质量分 8.5；venue NAVIGATION；数据集/benchmark
   - 推荐理由：主题贴合 韧性 PNT 与 GNSS 抗欺骗抗干扰，关键词集中在 gnss、interference。质量信号：venue NAVIGATION、有数据集/benchmark 线索，适合作为今日跟踪论文。

## 重点推荐

### 1. GNSS Spoofing Threat for V2X communications

- **论文信息**：Adolfo P. Jimenez, Juan Arquero-Gallego, Mario P. Luna, Jose E. Naranjo 等；2026-06-18；cs.CR
- **原文链接**：http://arxiv.org/abs/2606.20215v1
- **关键词**：pnt、gnss、gps、spoofing
- **质量信号**：质量分 8.0；venue NAVIGATION；真实实验
- **为什么值得读**：这篇论文同时覆盖 韧性 PNT 与 GNSS 抗欺骗抗干扰，并在标题/摘要中出现 pnt、gnss、gps、spoofing 等信号；质量侧还有 质量分 8.0；venue NAVIGATION；真实实验。它适合用来观察该方向近期如何处理鲁棒性、异常检测或融合估计问题。
- **对 GNSS/融合/SLAM 系统的启发**：可借鉴其异常定义和误报抑制思路，把 GNSS 可信度作为状态估计输入的一部分，而不是孤立阈值。
- **摘要要点**：从题名与摘要看，论文主要关注 GNSS 欺骗/干扰场景下的异常识别与完整性监测；技术线索包括 pnt、gnss、gps、spoofing。阅读全文时建议重点看 可观测量设计、误报控制、攻击与非攻击故障的区分方式，再判断是否适合迁移到自己的工程链路。

### 2. A Conditional Timing Protection Level: Holdover-Limited Undetected Time Error Under GNSS Spoofing

- **论文信息**：Chakshu Baweja；2026-06-23；eess.SP
- **原文链接**：http://arxiv.org/abs/2606.24210v1
- **关键词**：gnss、spoofing、integrity
- **质量信号**：质量分 5.5；有代码线索；数据集/benchmark
- **为什么值得读**：这篇论文同时覆盖 韧性 PNT 与 GNSS 抗欺骗抗干扰，并在标题/摘要中出现 gnss、spoofing、integrity 等信号；质量侧还有 质量分 5.5；有代码线索；数据集/benchmark。它适合用来观察该方向近期如何处理鲁棒性、异常检测或融合估计问题。
- **对 GNSS/融合/SLAM 系统的启发**：可借鉴其异常定义和误报抑制思路，把 GNSS 可信度作为状态估计输入的一部分，而不是孤立阈值。
- **摘要要点**：从题名与摘要看，论文主要关注 GNSS 欺骗/干扰场景下的异常识别与完整性监测；技术线索包括 gnss、spoofing、integrity。阅读全文时建议重点看 可观测量设计、误报控制、攻击与非攻击故障的区分方式，再判断是否适合迁移到自己的工程链路。

### 3. Efficient Network Inference via Hardware-Aware Architecture Search, Model Pruning & Quantization

- **论文信息**：Lucas Heublein, Mark Deutel, Axel Plinge, Felix Ott；2026-06-22；cs.LG
- **原文链接**：http://arxiv.org/abs/2606.23210v1
- **关键词**：gnss、interference
- **质量信号**：质量分 8.5；venue NAVIGATION；数据集/benchmark
- **为什么值得读**：这篇论文同时覆盖 韧性 PNT 与 GNSS 抗欺骗抗干扰，并在标题/摘要中出现 gnss、interference 等信号；质量侧还有 质量分 8.5；venue NAVIGATION；数据集/benchmark。它适合用来观察该方向近期如何处理鲁棒性、异常检测或融合估计问题。
- **对 GNSS/融合/SLAM 系统的启发**：可借鉴其异常定义和误报抑制思路，把 GNSS 可信度作为状态估计输入的一部分，而不是孤立阈值。
- **摘要要点**：从题名与摘要看，论文主要关注 GNSS 欺骗/干扰场景下的异常识别与完整性监测；技术线索包括 gnss、interference。阅读全文时建议重点看 可观测量设计、误报控制、攻击与非攻击故障的区分方式，再判断是否适合迁移到自己的工程链路。

## 今日观察

PNT 韧性正在从单一 GNSS 接收机指标，走向多源一致性判断。对机器人和无人系统来说，更可靠的做法是把欺骗、干扰、遮挡和传感器退化一起放进状态估计链路里处理。

## 明日检索关键词

`resilient PNT`、`GNSS spoofing detection`、`GNSS jamming detection`、`PNT integrity`、`OSNMA`、`GNSS denied localization`。

> 具体实验结论建议回到原文核对后再引用。
