# 五人分工

## 成员 1：组长、数据源和采集

主任务：需求拆解、数据源确认、采集器维护、采集日志检查。

输入：公开数据源 URL、`config/settings.yaml`、`config/locations.csv`。

输出：`data/raw` 原始文件、元信息、`docs/data_sources.md`。

每周工作：确认数据源可用性，运行采集脚本，抽查原始文件，记录失败原因。

验收标准：每个 raw 文件有来源 URL、采集时间和字段说明。

接口：向成员 2 提供 raw 数据路径和字段说明。

备用任务：维护 demo 数据和数据真实性声明。

答辩讲解：数据来源、合规采集、网络不可用时的 demo 方案。

## 成员 2：Hadoop、HDFS、Spark ETL

主任务：HDFS 分层、Spark 清洗、silver/gold 表。

输入：成员 1 的 raw 数据。

输出：silver Parquet、gold Parquet、数据质量报告。

每周工作：运行 `init_hdfs.sh`、`upload_raw_to_hdfs.sh`、`run_spark_pipeline.sh`，修复字段兼容问题。

验收标准：Spark 作业可重复运行，输出行数和质量报告可解释。

接口：向成员 3 提供 gold 特征表。

备用任务：维护 Hive 外部表。

答辩讲解：HDFS raw/silver/gold、Spark 去重、负数修订、异常标记。

## 成员 3：特征工程、模型训练和评估

主任务：时间序列特征、朴素基线、GBT、ARIMA、指标。

输入：成员 2 的 gold 特征表。

输出：模型、预测结果、`model_metrics.json`、`model_comparison.json`。

每周工作：检查数据泄漏，按时间切分训练/验证/测试，比较基线和复杂模型。

验收标准：输出 MAE、RMSE、R2、MAPE、SMAPE；复杂模型差于基线时如实显示。

接口：向成员 4 提供 serving JSON。

备用任务：维护可选 LSTM。

答辩讲解：特征、目标 `target_t_plus_7`、模型对比和局限。

## 成员 4：Flask 后端、部署和脚本

主任务：API、统一错误处理、部署脚本。

输入：成员 3 的 serving JSON。

输出：`src/web/app.py`、API 文档、启动脚本。

每周工作：跑 API 测试，维护 `scripts`，排查服务器端口和 SSH 隧道问题。

验收标准：所有 API 返回统一 JSON，文件缺失时有友好错误。

接口：向成员 5 提供 API 字段和样例。

备用任务：补充 pytest。

答辩讲解：Flask 为什么不实时启动 Spark、API 结构和部署方式。

## 成员 5：ECharts 前端、文档和答辩

主任务：大屏页面、交互、README、答辩材料。

输入：成员 4 的 API。

输出：ECharts 大屏、README、答辩提纲。

每周工作：检查图表显示、筛选联动、错误状态、移动端基本布局。

验收标准：页面能展示趋势、风险、模型、质量、来源状态，并明确显示演示数据标识。

接口：向全组反馈 API 字段缺口。

备用任务：录制演示视频和截图。

答辩讲解：大屏交互、展示顺序、项目创新和不足。
