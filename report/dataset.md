# 实验报告（一）：项目数据集说明

## 1. 报告目的与统计口径

本项目名称为“基于机器学习的传染病发病趋势预测与可视化系统”。本报告依据当前项目中的真实文件、`config/settings.yaml`、`data/serving/local_real_pipeline_manifest.json` 和 `data/serving/source_status.json` 编写，不依据文件夹名称猜测字段。

项目采用 Raw、Silver、Gold、Serving 四层数据组织：

- **Raw**：下载或采集后的原文件，原则上只追加、不覆盖、不修改。
- **Silver**：完成字段统一、去重、单位转换和质量标记的规范表。
- **Gold**：面向统计分析和模型训练的特征表、预测明细。
- **Serving**：Flask 可以直接读取的 JSON 文件。

当前网页实际展示的是 `real_local_multi_source` 模式。数据范围主要限定为 10 个国家：`AUS、BRA、CHN、DEU、FRA、GBR、IND、JPN、KOR、USA`。不同疾病的原始覆盖范围不同，所以不是每一种疾病都覆盖这 10 个国家。

## 2. 数据集总览

| 数据集 | 来源与入口 | 原始位置 | 原始规模 | 频率/范围 | 项目用途 |
|---|---|---|---:|---|---|
| OWID COVID-19 compact | Our World in Data，`https://catalog.ourworldindata.org/garden/covid/latest/compact/compact.csv` | `data/raw/owid/` | 591,522 行 | 日频；清洗后 2020-01-01 至 2025-12-31 | COVID 主表、预测目标 |
| Kaggle Novel Corona Virus 2019 | `https://www.kaggle.com/datasets/sudalairajkumar/novel-corona-virus-2019-dataset` | `data/raw/kaggle/epidemic/novel-corona-virus-2019-dataset/archive (2)/covid_19_data.csv` | 306,429 行 | 日频；2020-01-22 至 2021-05-29 | 与 OWID 交叉核验，不与主表相加 |
| Kaggle Tuberculosis | Kaggle 下载目录；当前仓库没有保存数据集 owner/slug 元数据 | `data/raw/kaggle/epidemic/Tuberculosis/` | 6 个 CSV，共约 32,429 行 | 国家年度指标；主序列使用 2000 至 2022 年 | 结核病发病率主序列及辅助指标 |
| Weekly Hospital Respiratory Data and Metrics | Kaggle 下载目录；文件内容为美国周频住院呼吸疾病指标 | `data/raw/kaggle/epidemic/Weekly Hospital Respiratory Data and Metrics/` | 12,768 行 | 周频；2020-08-08 至 2024-11-16 | 流感、RSV、新冠住院预测 |
| Open-Meteo Historical Weather | `https://archive-api.open-meteo.com/v1/archive` | `data/raw/open_meteo/<ISO3>/` | 8,600 行 | 日频；2020-01-22 至 2025-01-16 | 同期温湿度、降水、风速等特征 |
| Kaggle Historical Hourly Weather | `https://www.kaggle.com/datasets/selfishgene/historical-hourly-weather-data` | `data/raw/kaggle/weather/historical-hourly-weather-data/` | 每个指标 45,253 个小时时间点，27 个美国城市列 | 小时频；2012-10-01 至 2017-11-30 | 美国历史天气探索、结核病同年辅助分析 |
| World Bank Indicators | `https://api.worldbank.org/v2/` | `data/raw/world_bank/` | 当前 CSV 覆盖 2020 至 2025 | 国家年度 | 人口、城市化率、人均 GDP |
| Kaggle World Population | `https://www.kaggle.com/datasets/iamsouravbanerjee/world-population-dataset` | `data/raw/kaggle/population/world-population-dataset/world_population.csv` | 234 行 | 国家多年度宽表 | 人口、面积、密度等后备值 |
| WHO GHO | WHO Global Health Observatory OData API，`https://www.who.int/data/gho/info/gho-odata-api` | `data/raw/who/` | 105 个 CSV，122,169 行，80 个指标 | 多数为国家年度；1990 至 2024 | HIV 主序列、TB 辅助指标、完整指标目录 |
| 中国疾控公开页面 | 中国疾病预防控制中心公开页面及附件 | `data/raw/china_cdc/` | 27 条页面元数据、HTML 和 12 个 PDF 附件 | 页面/周报/月报级 | 官方报告索引、来源核验，不直接作模型标签 |
| Demo 固定种子数据 | 项目自带生成器 | `data/raw/demo/` | 由脚本生成 | 教学演示 | 无真实数据时验证程序，不进入当前真实数据结果 |

> Kaggle 的 TB 和周频呼吸数据目录中没有 `dataset-metadata.json`，因此无法从本地文件可靠还原 Kaggle 的作者 slug、页面 URL 和许可证。报告不伪造这三项；提交课程材料前应从当时的下载页面补录页面地址、作者和许可证截图。

## 3. OWID COVID-19 日频数据

### 3.1 文件与字段

- 当前文件：`data/raw/owid/owid_compact_20260710T034222Z.csv`
- 文件大小：约 167.3 MB。
- 采集代码：`src/collectors/owid_collector.py`。
- 核心字段：日期、国家名称、ISO3 国家代码、新增病例、平滑新增病例、累计病例、新增死亡、累计死亡、人口等。
- 清洗关联键：`location_code + date`，其中 `location_code` 为 ISO3。

### 3.2 清洗后的实际覆盖

- 原始 591,522 行；筛选项目十国和配置日期后为 21,920 行。
- 2020-01-01 至 2025-12-31，国家数 10。
- 网页 COVID 可用日期为 2020-01-04 至 2025-12-31，这是经过按周对齐/展示可用性整理后的范围。
- 该表是 COVID 唯一主表。Kaggle COVID 只用于比较重叠日期，不会叠加病例。

### 3.3 数据特点

OWID 提供统一的国家代码和较长时间范围，适合国家级时间序列。部分国家在后疫情时期以批次方式报告，因此会出现连续日期上的大量 0 和少量峰值。这是来源报告节奏，不等于清洗程序删除日期。

## 4. Kaggle COVID-19 交叉核验数据

- 文件：`covid_19_data.csv`。
- 原始字段包含 `ObservationDate`、`Country/Region`、`Province/State`、`Confirmed`、`Deaths`、`Recovered` 等。
- 原始粒度是“国家/省份/日期累计值”，不是国家日新增病例。
- 清洗时先规范国家名和日期，再按国家、日期汇总省份累计值，通过相邻日期差分得到新增量。
- 十国范围内清洗后 4,879 行，覆盖 2020-01-22 至 2021-05-29。
- 用途是对 OWID 重叠期的数量级、趋势和日期连续性进行交叉检查。

该数据集不能与 OWID 主表求和，否则同一批病例会被重复计算；也不能把 `Confirmed` 直接当成 `new_cases`，因为前者是累计值。

## 5. Kaggle Tuberculosis 六表

目录中实际包含：

1. `1- incidence-of-tuberculosis-sdgs.csv`：结核病估计发病率，作为项目 TB 主指标，单位为每 10 万人。
2. `2- tuberculosis-deaths-by-age.csv`：分年龄结核病死亡数据。
3. `3- tuberculosis-case-detection-rate.csv`：病例发现率。
4. `4- tuberculosis-treatment-success-rate-by-type.csv`：不同病例类型的治疗成功率。
5. `5- tuberculosis-patients-with-hiv-share.csv`：TB 患者中的 HIV 占比。
6. `6- tuberculosis-deaths-under-five-ihme.csv`：5 岁以下结核病死亡估计。

这些文件属于国家年度指标，不是每日病例。清洗后的主序列为 230 行，即 10 个国家乘以 23 个年度（2000 至 2022）。其余文件不会丢弃，而是作为辅助列保留在 Silver；字段口径不相同的记录不会被强行相加。

## 6. 美国周频呼吸系统住院数据

- 文件：`raw_weekly_hospital_respiratory_data_2020_2024.csv`，约 6.2 MB。
- 原始 12,768 行。
- 文件同时包含全国和地区/州层级、多种指标。项目选择文件中已经给出的 `USA` 全国行，避免把全国行和州行再次求和。
- 清洗输出 507 条规范疾病观测：流感、RSV、新冠住院入院数。
- 流感和新冠住院可用范围为 2020-08-08 至 2024-11-16；RSV 可用范围从 2023-10-07 开始。
- 关联键：`disease + location_code + date + frequency`，其中日期统一为报告周的周六。

周频数据在网页和 LSTM 中保持周频。网页为了连续绘图可以生成“展示用日历轴”，但不会把每天都伪造为一个新的真实周观测。

## 7. 天气数据

### 7.1 Open-Meteo 同期天气

- 采集代码：`src/collectors/open_meteo_collector.py` 和 `scripts/download_weather_data.py`。
- 地点表：`config/weather_locations.csv`，每个国家选一个代表城市及经纬度。
- 保存方式：`data/raw/open_meteo/<ISO3>/open_meteo_<ISO3>_<year>.csv`，旁边保存 `.meta.json` 请求参数和单位。
- 字段：平均/最高/最低气温、平均相对湿度、降水量、最大风速等。
- 单位：温度摄氏度、湿度百分比、降水毫米、风速按元数据所列单位。
- 实际输出：10 国共 8,600 条日记录，2020-01-22 至 2025-01-16。

它是国家代表城市代理变量，不代表全国平均天气，因此图表标题和报告中必须写“代表城市天气”。

### 7.2 Kaggle 2012-2017 历史小时天气

实际文件包括 `temperature.csv`、`humidity.csv`、`pressure.csv`、`wind_speed.csv`、`wind_direction.csv`、`weather_description.csv` 和 `city_attributes.csv`。每个指标 CSV 以时间为行、27 个美国城市为列。

项目分块读取并聚合为：

- 1,887 条 USA 国家日记录，保留每天参与计算的城市观测数；
- 6 条年度聚合记录，用于与同年 USA 结核病指标做探索性关联。

“45,253 原始行变为 1,887 日记录”是小时到日的聚合，不是删除 96% 的有效数据；每条日记录吸收了当天多个小时、多个城市的观测。该数据日期不与 2020 年后的 COVID 重叠，因此绝不强拼到 COVID。

## 8. 人口和社会经济数据

### 8.1 World Bank

采集器：`src/collectors/world_bank_collector.py`。当前使用三个指标：

- `SP.POP.TOTL`：总人口；
- `SP.URB.TOTL.IN.ZS`：城市人口占比；
- `NY.GDP.PCAP.CD`：人均 GDP（现价美元）。

数据为国家年度，关联键是 `location_code + year`。当前本地 CSV 是 `world_bank_2020_2025.csv`，旁路 `.meta.json` 保存采集信息。

### 8.2 Kaggle World Population

文件 `world_population.csv` 有 234 个国家/地区行，包含国家名、ISO 代码、面积、密度、增长率、世界人口占比以及多个年份的人口宽表列。项目将年份列转成长表，作为 World Bank 缺值的后备来源。

两者合并后 Silver 输出 560 条国家年度记录。优先级是同年 World Bank值优先，Kaggle 作为后备；只在两个已知年份之间插值，不向已知范围之外随意外推。

## 9. WHO GHO 数据

- 采集代码：`src/collectors/who_collector.py`。
- 原始目录：`data/raw/who/`，105 个 CSV、122,169 行、80 个唯一指标。
- 时间范围：1990 至 2024，但每个指标和国家的覆盖不同。
- 常见字段：指标代码/名称、国家或 WHO 地区代码、年份、数值、估计上下界、维度、来源、WHO 记录 ID、原始 JSON。
- 主关联键：`indicator_code + who_record_id` 用于跨文件去重；进入疾病表后使用 `location_code + year`。

项目当前将 `HIV_0000000026` 整理为 HIV/AIDS 年度新发感染主序列，得到 96 行；另选取 18 个口径可解释的 TB 指标，按国家和年份左连接到结核病主表。其他 WHO 数据全部保留在 `who_indicators_clean.csv` 和指标摘要 API 中，不为了提高“利用率”而混合不同年龄、性别、地区层级和统计口径。

原始 122,169 行到 117,492 条唯一记录的差额为 4,677 条跨采集主题完全重复副本，冲突记录为 0。Raw 文件未删除。

## 10. 中国疾控公开资料

- 采集代码：`src/collectors/china_cdc_collector.py`。
- Raw 中保留 HTML、PDF/附件和 `page_metadata.jsonl`。
- 当前 27 条页面记录均经过 URL 去重、标题/发布日期/周次或月份提取、附件存在性检查和高置信摘要提取。
- 复杂 PDF 表格尚未作为模型标签，因为自动解析后难以保证疾病、地区、时间和单位口径完全可靠。

因此数据源状态显示 `info`，不是失败。它用于来源证明、人工复核和后续扩展。

## 11. Demo 数据与配置字典

`src/collectors/generate_demo_data.py` 使用固定随机种子生成疫情、天气、人口、预测和质量报告，目的是在没有网络和真实数据时验证网页。当前真实流水线不会把 Demo 与真实病例混合。

辅助字典包括：

- `config/country_name_mapping.csv`：来源国家名到 ISO3 的映射；
- `config/weather_locations.csv`：十国代表城市、经纬度；
- `config/settings.yaml`：日期、国家、路径、HDFS、Spark、模型和 Web 参数。

## 12. 许可证与引用原则

1. OWID、World Bank、WHO、Open-Meteo 应分别保留来源 URL、下载日期和原机构署名，并遵循各站点当前的数据使用条款。
2. Kaggle 不存在统一许可证，每个数据集以其页面的 License 栏为准。当前两个新增 Kaggle 目录缺少本地元数据，不能只根据文件名声称许可证。
3. 中国疾控公开网页可用于课程研究和来源核验，但公开访问不等于任意再许可；报告引用标题、发布日期和链接，附件不重新发布。
4. Raw 数据不提交密钥，不把 `.env`、Kaggle API token 或远程主机密码写入 Git。
5. 课程论文应在参考文献中写明数据提供方、数据集名称、URL、访问日期和版本/下载时间。

## 13. 当前疾病与数据频率

| 疾病 | 指标 | 真实频率 | 覆盖 | 可用模型 |
|---|---|---|---|---|
| COVID-19 | 日新增病例 | 日频 | 十国，2020-2025 | 最近值、移动平均、GBDT、COVID LSTM |
| Influenza | 周新增住院 | 周频 | USA，2020-2024 | 最近值、移动平均、Influenza LSTM |
| RSV | 周新增住院 | 周频 | USA，2023-2024 | 最近值、移动平均、RSV LSTM |
| COVID-19 Hospital Admissions | 周新增住院 | 周频 | USA，2020-2024 | 最近值、移动平均、Hospital LSTM |
| Tuberculosis | 估计发病率/10 万人 | 年频 | 十国，2000-2022 | 最近值、移动平均、TB LSTM |
| HIV/AIDS | 新发感染估计 | 年频 | 6 个有值国家，2000-2024 | 最近值、移动平均、HIV LSTM |

不同频率不直接拼接成一条时间序列。模型中的“一步预测”分别表示下一日、下一周或下一年。
