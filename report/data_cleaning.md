# 实验报告（二）：数据清洗、Silver 与 Gold 数据流

## 1. 清洗目标

数据清洗的目标不是简单删掉空值，而是把来源不同、频率不同、统计口径不同的数据转换成可追溯的规范观测，并尽量保留可解释信息。当前项目遵循以下原则：

1. Raw 原文件只读，不在原地覆盖。
2. 每条疾病观测必须明确疾病、地区、日期、频率、指标、数值、单位和来源。
3. 国家统一为 ISO3，日期统一为 `YYYY-MM-DD`。
4. 累计值与新增值分开；累计值只能通过国家内按日期差分转换成新增值。
5. 负数修订保留质量标记，展示/模型目标按具体规则处理，不悄悄删除整行。
6. 不同来源的同一疾病不相加。OWID 是 COVID 主表，Kaggle COVID 只交叉核验。
7. 不强行关联日期不重叠的数据；2012-2017 天气不拼到 2020 年后的 COVID。
8. 缺失天气不能导致疫情观测被删除，使用 `has_weather` 标记区分真实匹配和后备填充值。
9. 插值只用于短缺口的模型输入历史，不生成虚假的训练标签。
10. 时间序列训练、验证、测试按时间先后切分，禁止未来数据泄漏。

## 2. 两条清洗路线

项目目前存在两条明确分工的路线。

### 2.1 Windows 本地真实多源路线（当前网页主路线）

入口：`scripts/run_local_real_pipeline.ps1`，核心实现：`scripts/build_local_serving_from_raw.py`。

```text
data/raw/*
  -> Pandas 多源清洗
  -> data/silver/local/*.csv
  -> 频率统一、天气/人口辅助关联、特征工程
  -> data/gold/local/forecast_features.csv
  -> 基线/GBDT/LSTM
  -> data/gold/local/*predictions.csv + data/models/local/*
  -> data/serving/*.json
  -> Flask API -> ECharts
```

它不要求 Windows 安装 Hadoop、Spark 或 Java，当前六类疾病和完整网页输出均由这条路线生成。

### 2.2 Ubuntu HDFS + Spark Silver 路线

当前较新的远程入口是 `scripts/remote_pipeline.py`，它通过 SSH/SFTP 控制 Ubuntu，在虚拟机中运行：

```text
Windows Raw
  -> SFTP 同步项目/数据
  -> Ubuntu 本地项目目录
  -> scripts/upload_raw_to_hdfs.py
  -> HDFS /disease_platform/raw
  -> spark-submit 清洗作业
  -> HDFS /disease_platform/silver（Parquet）
  -> Silver 运行/质量 JSON 下载回 Windows
```

这条较新的一键远程控制链目前只正式覆盖 Kaggle COVID、Kaggle Population 和 Open-Meteo 三类 Silver 输入。仓库中虽然还存在 Spark Gold、GBT 和 Serving 导出作业，但它们尚未接入 `remote_pipeline.py all`。因此不能写成“远程 all 已经训练六种疾病并更新网页”。

## 3. 本地清洗核心代码

`scripts/build_local_serving_from_raw.py` 是当前最重要的编排器，主要函数如下：

| 函数 | 作用 |
|---|---|
| `clean_owid` | 清洗 OWID COVID 主表 |
| `clean_kaggle_covid_validation` | 清洗 Kaggle COVID 并生成交叉核验表 |
| `compare_covid_sources` | 比较重叠期，不合并病例 |
| `clean_tuberculosis` | 清洗六个 TB 年度 CSV |
| `clean_respiratory` | 清洗 USA 周频住院呼吸数据 |
| `clean_population` | 合并 World Bank 与 Kaggle 人口 |
| `clean_weather` | 清洗 Open-Meteo 日频天气 |
| `clean_historical_weather` | 小时城市天气转国家日频和年度天气 |
| `clean_china_cdc_metadata` | URL 去重、附件和摘要质量检查 |
| `clean_who` | WHO 多文件规范化、跨主题去重和用途分类 |
| `build_features` | 生成统一疾病观测及模型特征 |
| `complete_model_training` | 基线、GBDT、各疾病 LSTM 编排 |
| `export_serving` | 导出 Flask JSON |

公共支持代码包括：

- `src/common/config.py`：加载 YAML 配置并解析项目路径；
- `src/common/paths.py`：项目根目录定位和跨平台路径处理；
- `src/common/logger.py`：统一日志；
- `config/country_name_mapping.csv`：国家名规范化；
- `config/weather_locations.csv`：代表城市和经纬度。

## 4. 各数据集清洗过程

### 4.1 OWID COVID 主表

1. 读取最新 `owid*.csv`。
2. 解析日期并过滤配置的十国、起止日期。
3. 统一 ISO3 为 `location_code`，国家名为 `location_name`。
4. 将新增病例、平滑新增病例、死亡和人口字段转成数值。
5. 对国家和日期排序；检查重复 `location_code + date`。
6. 保留来源中的批次报告和零值，生成报告稀疏性标记。
7. 输出 `data/silver/local/owid_covid_daily_clean.csv` 和兼容文件 `epidemic_daily_clean.csv`。

结果：591,522 原始行中，十国日期范围内 21,920 行进入主表。减少主要来自国家筛选，不是丢弃十国有效日期。

### 4.2 Kaggle COVID 核验表

1. 将 `ObservationDate` 解析为标准日期。
2. 通过国家映射表统一 `Country/Region`。
3. 将 `Confirmed`、`Deaths` 等累计字段转换为数值。
4. 同一国家、日期的省级累计值先求和。
5. 在国家内部按日期差分，得到日新增估计。
6. 记录负数病例/死亡修订、重复键、未映射地区。
7. 与 OWID 的重叠日期对比趋势和数量级，但不追加到主表。

输出：`data/silver/local/kaggle_covid_validation_clean.csv`，十国 4,879 行。

### 4.3 Tuberculosis 六表

1. 识别各文件的国家、ISO、年份和值字段。
2. 主表采用 `incidence-of-tuberculosis-sdgs` 的估计发病率，统一为每 10 万人。
3. 以 `location_code + year` 为主键，把死亡、病例发现率、治疗成功率、HIV 占比等作为辅助字段左连接。
4. 年度日期统一为当年 `12-31`，但 `frequency` 明确标为 `annual`。
5. 同一国家年度多维数据先核对指标、年龄或病例类型，不把不同口径直接相加。
6. WHO 的 18 个 TB 辅助指标也按国家年度左连接，并保留估计上下界。

输出：`data/silver/local/tuberculosis_annual_clean.csv`，230 行。六个原始文件中的其他年龄或辅助记录仍留在 Raw；主表 230 行代表可比较的十国年度主序列，不代表其余行被无理由删除。

### 4.4 周频呼吸疾病

1. 读取最新 respiratory CSV。
2. 标准化日期、病原体、地理层级、指标名和数值。
3. 优先选择文件中已存在的 USA 全国记录，避免将州级行再汇总后与全国行重复。
4. 将 0-1 形式的比例值转换为 0-100，并保留单位。
5. 把流感、RSV、COVID 住院拆成三个疾病序列。
6. 日期对齐至周六，频率标为 `weekly`，不伪装成真实日观测。

输出：

- `respiratory_weekly_clean.csv`：来源规范周表；
- `respiratory_observations_clean.csv`：统一疾病观测结构；
- 共 507 条可建模观测。

### 4.5 Open-Meteo 日频天气

1. 递归读取国家/年份 CSV，并读取旁路 `.meta.json`。
2. 统一日期、ISO3、代表城市和经纬度。
3. 将温度、湿度、降水、风速转换为数值并保留单位。
4. 检查国家日期重复、日期范围、未来日期和缺失率。
5. 日频疾病按 `location_code + date` 精确连接。
6. 周频疾病按同一周聚合到周六；年度疾病只在相同年份存在合理数据时聚合。

输出：`data/silver/local/weather_daily_clean.csv`，8,600 行。

### 4.6 Kaggle 历史小时天气

1. 读取 `city_attributes.csv` 建立 27 个城市和经纬度目录。
2. 对温度、湿度、气压、风速等宽表分块读取，避免一次把所有城市指标载入内存。
3. 每个小时跨美国城市聚合时忽略缺失值，并记录有效城市观测数。
4. 再按自然日聚合，输出 1,887 条 USA 日记录。
5. 依据每个日值的有效观测数计算年度加权统计，输出 6 个年度记录。
6. 只与 2012-2017 同年的 USA TB 做探索性关联，不与 COVID 强行关联。

输出：`historical_weather_daily_clean.csv` 和 `historical_weather_annual_clean.csv`。原始 45,253 个小时变成 1,887 天是降频聚合，不是异常删行。

### 4.7 人口与社会经济

1. World Bank API 长表统一为 `location_code + year + indicator`。
2. Kaggle 人口宽表将 `2022 Population` 等列拆成长表。
3. 同一国家同一年优先采用 World Bank，缺失时采用 Kaggle。
4. 人口只在两个已知年份之间线性插值，写入插值标记；不做无边界外推。
5. 计算或保留人口密度、城市化率、人均 GDP，检查人口非正数和单位。
6. 日/周疾病通过观测日期的年份关联，年度疾病按同年关联。

输出：`population_yearly_clean.csv`，560 行，当前缺失人口数为 0。

### 4.8 WHO GHO

1. 递归读取 105 个 CSV，并附加来源文件和采集主题。
2. 从列和 `raw_json` 中解析指标代码、WHO 记录 ID、ISO3、年份、年龄、性别、来源维度、估计值和区间。
3. `No data` 保留为空值，不转换成 0。
4. 以 `indicator_code + who_record_id` 识别跨主题重复；记录全部来源文件、出现次数和内容版本数。
5. 本批 4,677 个重复键内容完全相同，冲突为 0，因此合并为唯一记录；Raw 中仍保留两份采集文件。
6. 按用途分类为主序列、TB 辅助、目录展示或维度化保留，不把年龄/性别口径混成国家总量。
7. HIV 主序列按 `location_code + year` 生成；TB 指标转为年度宽表并保留上下界。

输出：

- `who_indicators_clean.csv`：117,492 条唯一记录；
- `who_duplicate_audit.csv`：重复来源和冲突审计；
- `who_indicator_summary.csv`：80 个指标覆盖摘要；
- `who_hiv_annual_clean.csv`：96 条 HIV 主序列；
- `who_tuberculosis_auxiliary_clean.csv`：18 个 TB 辅助指标宽表。

### 4.9 中国疾控资料

1. 读取 `page_metadata.jsonl`，规范 URL、标题、发布日期和本地路径。
2. 按规范 URL 去重。
3. 从 URL/标题解析报告类别、年份、周次或月份。
4. 校验 HTML/PDF 是否存在、文件大小是否合理。
5. 只提取高置信正文摘要；复杂 PDF 表格标记为人工复核，不猜测字段。

输出：`china_cdc_metadata_clean.csv`，27 行。`info` 状态表示可作为资料目录，但尚未形成可靠模型标签。

## 5. 统一 Silver 观测模式

不同疾病转换到统一长表时至少包含：

| 字段 | 含义 |
|---|---|
| `disease` | 疾病名称 |
| `location_code` | ISO3 或规范地区代码 |
| `location_name` | 地区显示名 |
| `date` | 观测日期 |
| `year` | 关联年度 |
| `frequency` | `daily`、`weekly` 或 `annual` |
| `metric` / `metric_label` | 指标代码和中文含义 |
| `value` | 保持来源口径的观测值 |
| `unit` | 人数、百分比、每 10 万人等 |
| `source` | 数据来源 |
| `is_observed` | 是否真实观测而非内部补齐点 |

频率字段非常重要：年发病率的数值 3 表示“每 10 万人约 3 例”，不是“只有 3 个病人”。

## 6. Gold 特征工程

Gold 主文件为 `data/gold/local/forecast_features.csv`。数据推进过程为：

1. 合并 COVID、流感、RSV、COVID 住院、TB 和 HIV 的规范观测。
2. 按疾病、地区、真实频率建立连续频率索引。
3. 只对短缺口补齐模型输入历史，保留 `is_observed`；训练标签必须来自真实观测。
4. 生成滞后值、滚动均值/标准差、增长率、日历字段。
5. 关联天气、人口、城市化和 GDP；缺天气保留记录并标记。
6. 按目标频率生成未来一步或未来 7 日标签和 `forecast_target_date`。
7. 严格按时间排序，之后才划分 train/validation/test。

主要质量风险及控制：

- **数据泄漏**：Scaler 只在训练集拟合；滚动窗口只看当前及过去；目标日期晚于特征日期。
- **负数修订**：保留原始质量统计，建模目标按非负疾病计数规则处理。
- **单位不一致**：人数、百分比、每 10 万人不放进同一目标列比较。
- **日期不连续**：区分真正缺失日期和来源报告值为 0。
- **国家名不一致**：先映射 ISO3，再连接人口和天气。

## 7. Serving 导出

`export_serving` 将 Gold 和模型结果转换为 Flask 易读的 JSON：

- `metadata.json`：生成时间和数据模式；
- `options.json`：疾病、地区、模型、频率和各自日期范围；
- `overview.json`：顶部指标；
- `trend.json`：观测、移动平均、预测和置信区间；
- `predictions.json`：测试/预测误差明细；
- `model_metrics.json`、`model_comparison.json`：模型指标；
- `weather_correlation.json`：同地区同期天气关联点；
- `risk_map.json`、`rankings.json`：风险地图和排行榜；
- `data_quality_report.json`、`source_status.json`：质量和来源状态；
- `disease_share.json`、`who_indicator_summary.json`、`model_data_coverage.json`：辅助面板。

Flask 不读取 Raw 或 Silver。只运行 `app.py` 不会触发清洗；必须先运行流水线更新这些 JSON。

## 8. Spark Silver 作业

远程 Spark 清洗文件为：

- `src/spark_jobs/clean_epidemic.py`：Kaggle COVID 清洗；
- `src/spark_jobs/clean_population.py`：人口清洗；
- `src/spark_jobs/clean_weather.py`：Open-Meteo 清洗；
- `src/spark_jobs/data_quality_report.py`：质量检查；
- `src/spark_jobs/schemas.py`：显式 Schema；
- `src/spark_jobs/spark_session.py`：SparkSession 配置。

编排和上传文件为：

- `scripts/upload_raw_to_hdfs.py`：发现本地三类文件，上传、可选 SHA256/大小校验，输出上传清单；
- `scripts/run_silver_pipeline.py`：依次 `spark-submit`，输出 `silver_pipeline_run.json`；
- `scripts/remote_pipeline.py`：Windows 通过 SSH/SFTP 控制 Ubuntu。

HDFS 典型路径：

```text
/disease_platform/raw/kaggle/epidemic/
/disease_platform/raw/kaggle/population/
/disease_platform/raw/open_meteo/
/disease_platform/silver/epidemic/
/disease_platform/silver/population/
/disease_platform/silver/weather/
```

Silver 使用 Parquet，原因是列类型明确、压缩较好、Spark 可按列读取。当前远程一键 Silver 尚未覆盖 OWID、WHO、TB、呼吸系统和中国疾控全量接入，这是后续扩展项，不应与本地完整路线混淆。

## 9. 清洗结果如何验证

建议按以下顺序验证本地结果：

```powershell
conda run --no-capture-output -n intership python scripts/build_local_serving_from_raw.py --config config/settings.yaml --lstm --lstm-epochs 40
conda run --no-capture-output -n intership python scripts/verify_local_pipeline.py
conda run --no-capture-output -n intership pytest -q
```

再检查：

```powershell
Get-Content data/serving/local_real_pipeline_manifest.json
Get-Content data/serving/source_status.json
Get-Content data/serving/data_quality_report.json
```

验证重点不是只看“完整率 100%”，还要核对每个疾病的频率、单位、日期范围、观测数、训练目标是否来自真实观测，以及来源状态中的说明。
