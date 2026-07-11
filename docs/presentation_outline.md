# 答辩 PPT 提纲

## 1. 项目背景

传染病数据来源分散、更新频繁，课程项目希望用大数据技术完成趋势分析和可视化。

## 2. 需求分析

多源采集、HDFS 存储、Spark 清洗、机器学习预测、Flask API、ECharts 大屏。

## 3. 系统架构

展示 raw/silver/gold/serving 分层，以及 Flask 不启动 Spark 的离线计算架构。

## 4. 数据来源

OWID、Open-Meteo、World Bank、WHO、中国疾控公开页面、demo 数据。

## 5. Hadoop 分层存储

展示 `/disease_platform/raw`、`silver`、`gold`、`serving`、`checkpoints`。

## 6. Spark 清洗

字段标准化、去重、负数修订、缺失处理、异常标记、数据质量报告。

## 7. 特征工程

lag、rolling、growth_rate、气象、人口、每百万人病例，目标 `lead(target, 7)`。

## 8. 模型设计

朴素基线、Spark GBT、ARIMA、可选 LSTM。强调按日期切分，禁止随机打乱。

## 9. 预测结果

展示预测曲线、误差图、模型指标和基线对比。

## 10. 可视化大屏

展示筛选、趋势、风险地图、排行榜、数据质量和模型图表。

## 11. 项目创新与不足

创新：完整链路、质量报告、风险解释、demo/real 双模式。  
不足：真实公共卫生预测需要更严格数据审核、专家规则和持续监测。

## 12. 总结

本项目展示 Hadoop、Spark、机器学习和 Web 可视化如何协同完成传染病趋势分析课程系统。

答辩重点展示：

- 原始数据如何进入 HDFS；
- Spark 作业如何处理数据；
- silver 和 gold Parquet；
- 模型与基线的对比；
- Flask API；
- ECharts 大屏交互。
