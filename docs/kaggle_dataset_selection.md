# Kaggle 数据集选择与下载方案

更新时间：2026-07-10

## 1. 当前环境结论

已检查当前项目所在 Windows/PowerShell 环境：

```text
kaggle --version        -> 未安装 kaggle 命令
python -m kaggle --version -> 未安装 kaggle Python 模块
```

同时，当前环境直接访问 Kaggle 页面时出现 SSL 连接失败。因此本轮不下载数据、不伪造文件行数、不伪造许可证结论。本文档先给出候选数据集和人工下载方案；文件列表、字段名、行数、日期范围、地区范围、缺失率和许可证需要在你们下载后用 `scripts/inspect_kaggle_dataset.py` 做本地核验。

不要在聊天中发送 Kaggle API Token，也不要把 `kaggle.json` 提交到项目。

## 2. Kaggle 搜索关键词

建议先用这些关键词在 Kaggle 搜索，不要一次下载很多重复数据集：

```text
covid 19 daily cases csv country region confirmed deaths recovered
coronavirus daily time series csv country date confirmed deaths
covid world vaccination progress country vaccinations date iso_code csv
historical hourly weather data temperature humidity pressure csv city
climate change earth surface temperature country csv
world population dataset CCA3 country 2020 population csv
world development indicators GDP urbanization population country code csv
healthcare resources hospital beds country csv
```

筛选优先级：

1. CSV 优先，字段名清晰。
2. 有 `date` 或日期字段。
3. 有国家/地区字段，最好有 ISO3，例如 `iso_code`、`Country Code`、`CCA3`。
4. 时间跨度较长。
5. 地区覆盖较广。
6. 缺失值少。
7. 许可证允许课程项目使用。
8. 能和天气、人口、GDP、城市化率关联。

## 3. 候选数据集

> 注意：以下是候选下载清单，不是已完成本地核验的结论。请下载后运行检查脚本补齐“实际文件列表、字段、行数、缺失率、许可证”。

### 候选 1：Novel Corona Virus 2019 Dataset

- Kaggle 标识：`sudalairajkumar/novel-corona-virus-2019-dataset`
- Kaggle 页面：`https://www.kaggle.com/datasets/sudalairajkumar/novel-corona-virus-2019-dataset`
- 数据内容：COVID-19 疫情时间序列，通常包含确诊、死亡、康复等指标。
- 预期文件名：常见文件包括 `covid_19_data.csv`、JHU time series CSV。实际以本地检查为准。
- 主要字段：预期包含日期、国家/地区、省州、确诊、死亡、康复。实际字段需检查。
- 数据规模：待本地检查脚本统计。
- 日期范围：待本地检查脚本统计。
- 地区范围：待本地检查脚本统计。
- 缺失值情况：待本地检查脚本统计。
- 许可证：待 Kaggle 页面和本地元信息确认。
- 优点：传染病每日病例主数据候选，适合时间序列预测。
- 缺点：字段可能偏原始，需要统一国家名和日期字段；COVID-19 单病种。
- 是否推荐：推荐作为核心传染病候选 1。
- 在本项目中的用途：生成 `epidemic_daily`，用于趋势图、预测目标、模型评估。

下载后建议放置：

```text
data/raw/kaggle/epidemic/novel-corona-virus-2019-dataset/
```

### 候选 2：COVID-19 Dataset / Corona Virus Report

- Kaggle 标识：`imdevskp/corona-virus-report`
- Kaggle 页面：`https://www.kaggle.com/datasets/imdevskp/corona-virus-report`
- 数据内容：整理后的 COVID-19 国家/地区数据，常见为清洗后的病例、死亡、康复、活跃病例等。
- 预期文件名：常见文件包括 `covid_19_clean_complete.csv`、`full_grouped.csv`、`country_wise_latest.csv`、`day_wise.csv`。实际以本地检查为准。
- 主要字段：预期包含国家/地区、日期、经纬度、确诊、死亡、康复、活跃病例、WHO 区域。实际字段需检查。
- 数据规模：待本地检查脚本统计。
- 日期范围：待本地检查脚本统计。
- 地区范围：待本地检查脚本统计。
- 缺失值情况：待本地检查脚本统计。
- 许可证：待 Kaggle 页面和本地元信息确认。
- 优点：字段通常更适合新手理解，适合作为快速演示和接口联调。
- 缺点：可能更新时间较早或日期跨度有限，需要下载后核实；仍是 COVID-19 单病种。
- 是否推荐：推荐作为核心传染病候选 2 或备选。
- 在本项目中的用途：用于快速建立 `date + country + cases` 的最小预测闭环。

下载后建议放置：

```text
data/raw/kaggle/epidemic/corona-virus-report/
```

### 候选 3：Historical Hourly Weather Data

- Kaggle 标识：`selfishgene/historical-hourly-weather-data`
- Kaggle 页面：`https://www.kaggle.com/datasets/selfishgene/historical-hourly-weather-data`
- 数据内容：多个城市的小时级天气数据，通常包含温度、湿度、气压、风速、天气描述和城市经纬度。
- 预期文件名：常见文件包括 `temperature.csv`、`humidity.csv`、`pressure.csv`、`wind_speed.csv`、`weather_description.csv`、`city_attributes.csv`。实际以本地检查为准。
- 主要字段：预期包含 `datetime`、城市列，以及城市经纬度。实际字段需检查。
- 数据规模：待本地检查脚本统计。
- 日期范围：待本地检查脚本统计。
- 地区范围：待本地检查脚本统计。
- 缺失值情况：待本地检查脚本统计。
- 许可证：待 Kaggle 页面和本地元信息确认。
- 优点：天气字段丰富，小时级数据可聚合为日频，适合展示 Spark 聚合能力。
- 缺点：城市覆盖有限，不一定能和全球 COVID 国家数据完全匹配；需要先把城市映射到国家/地区。
- 是否推荐：推荐作为天气候选，但只用于能匹配到的城市/国家。
- 在本项目中的用途：清洗为 `weather_daily`，提供温度、湿度、气压、风速等特征。

下载后建议放置：

```text
data/raw/kaggle/weather/historical-hourly-weather-data/
```

### 候选 4：Climate Change: Earth Surface Temperature Data

- Kaggle 标识：`berkeleyearth/climate-change-earth-surface-temperature-data`
- Kaggle 页面：`https://www.kaggle.com/datasets/berkeleyearth/climate-change-earth-surface-temperature-data`
- 数据内容：Berkeley Earth 地表温度数据，通常包含国家、城市、州等维度的长期温度记录。
- 预期文件名：常见文件包括 `GlobalLandTemperaturesByCountry.csv`、`GlobalLandTemperaturesByCity.csv`、`GlobalTemperatures.csv`。实际以本地检查为准。
- 主要字段：预期包含日期、平均温度、温度不确定性、国家或城市。实际字段需检查。
- 数据规模：待本地检查脚本统计。
- 日期范围：待本地检查脚本统计。
- 地区范围：待本地检查脚本统计。
- 缺失值情况：待本地检查脚本统计。
- 许可证：待 Kaggle 页面和本地元信息确认。
- 优点：国家维度更容易和传染病国家数据关联，时间跨度通常很长。
- 缺点：多为月频，不是日频；如果用于每日病例预测，需要按月关联或只作为长期气候背景变量。
- 是否推荐：条件推荐。若老师接受月频气候变量，它比城市小时天气更容易关联国家。
- 在本项目中的用途：作为国家级温度背景特征，或用于按月聚合展示。

下载后建议放置：

```text
data/raw/kaggle/weather/climate-change-earth-surface-temperature-data/
```

### 候选 5：World Population Dataset

- Kaggle 标识：`iamsouravbanerjee/world-population-dataset`
- Kaggle 页面：`https://www.kaggle.com/datasets/iamsouravbanerjee/world-population-dataset`
- 数据内容：国家人口、面积、密度、增长率、大洲等。
- 预期文件名：常见文件包括 `world_population.csv`。实际以本地检查为准。
- 主要字段：预期包含国家、ISO3/CCA3、人口年份列、面积、密度、增长率、大洲。实际字段需检查。
- 数据规模：待本地检查脚本统计。
- 日期范围：待本地检查脚本统计。
- 地区范围：待本地检查脚本统计。
- 缺失值情况：待本地检查脚本统计。
- 许可证：待 Kaggle 页面和本地元信息确认。
- 优点：新手友好，国家代码容易和疫情数据关联。
- 缺点：不是日频数据；通常只有若干年份人口快照，GDP、城市化率等指标可能不完整。
- 是否推荐：推荐作为人口候选。
- 在本项目中的用途：按 `location_code` 或国家名关联，用于每百万人病例、风险指数和模型特征。

下载后建议放置：

```text
data/raw/kaggle/population/world-population-dataset/
```

### 可选候选：COVID-19 World Vaccination Progress

- Kaggle 标识：`gpreda/covid-world-vaccination-progress`
- Kaggle 页面：`https://www.kaggle.com/datasets/gpreda/covid-world-vaccination-progress`
- 数据内容：国家/日期级疫苗接种进度。
- 预期文件名：常见文件包括 `country_vaccinations.csv`、`country_vaccinations_by_manufacturer.csv`。实际以本地检查为准。
- 主要字段：预期包含国家、ISO 代码、日期、累计接种、完整接种、每日接种、疫苗种类、来源。实际字段需检查。
- 数据规模：待本地检查脚本统计。
- 优点：可与 COVID-19 每日病例关联，作为可选解释变量。
- 缺点：不是所有国家日期都完整；疫苗字段缺失较常见；不适合非 COVID 疾病。
- 是否推荐：可选，不作为第一轮必须下载。
- 在本项目中的用途：模型可选特征、数据源扩展示例。

下载后建议放置：

```text
data/raw/kaggle/optional/covid-world-vaccination-progress/
```

## 4. 最适合新手的组合方案

第一轮只下载 3 个，不要贪多：

| 类型 | 推荐数据集 | 原因 |
|---|---|---|
| 核心传染病数据 | `sudalairajkumar/novel-corona-virus-2019-dataset` | 更适合作为每日病例时间序列主数据候选 |
| 天气数据 | `selfishgene/historical-hourly-weather-data` | 小组可以练习把小时级天气聚合到日频 |
| 人口数据 | `iamsouravbanerjee/world-population-dataset` | 国家代码/人口字段较适合作为每百万人病例特征 |

如果下载后发现核心传染病数据字段太乱，则改用：

```text
imdevskp/corona-virus-report
```

如果老师更重视国家级关联而不是日频天气，则天气可改用：

```text
berkeleyearth/climate-change-earth-surface-temperature-data
```

## 5. 人工下载方式

### 方式 A：网页下载

1. 打开 Kaggle 数据集页面。
2. 登录自己的 Kaggle 账号。
3. 点击 Download。
4. 解压到下面目录。
5. 不要把 ZIP、CSV 大文件提交 Git。

### 方式 B：Kaggle CLI 下载

在你自己的电脑或 Ubuntu 上安装并配置 Kaggle CLI。不要把 token 发到聊天里。

```bash
pip install kaggle
kaggle --version
```

下载示例：

```bash
kaggle datasets download -d sudalairajkumar/novel-corona-virus-2019-dataset -p data/raw/kaggle/epidemic/novel-corona-virus-2019-dataset --unzip
kaggle datasets download -d selfishgene/historical-hourly-weather-data -p data/raw/kaggle/weather/historical-hourly-weather-data --unzip
kaggle datasets download -d iamsouravbanerjee/world-population-dataset -p data/raw/kaggle/population/world-population-dataset --unzip
```

## 6. 下载后目录要求

请按这个结构放置：

```text
data/raw/kaggle/
├── epidemic/
│   ├── novel-corona-virus-2019-dataset/
│   └── corona-virus-report/
├── weather/
│   ├── historical-hourly-weather-data/
│   └── climate-change-earth-surface-temperature-data/
├── population/
│   └── world-population-dataset/
└── optional/
    └── covid-world-vaccination-progress/
```

## 7. 下载后本地检查命令

```bash
python scripts/inspect_kaggle_dataset.py --root data/raw/kaggle --output docs/kaggle_local_inventory.md --json-output data/raw/kaggle_inventory.json
```

检查脚本会输出：

- 文件列表；
- CSV 字段名；
- 行数；
- 可能的日期字段和日期范围；
- 可能的地区字段和去重数量；
- 缺失值比例；
- 样例行；
- 如果存在 `dataset-metadata.json`，会读取许可证和标题。

拿到 `docs/kaggle_local_inventory.md` 后，再决定最终使用哪个数据集进入 Spark 清洗。

## 8. 本轮结论

当前环境不能完成 Kaggle 文件级在线核验，所以本轮不应声称任何候选数据集已经满足行数、日期范围、缺失率或许可证要求。

下一步请先手动下载推荐的 3 个数据集到指定目录，然后运行检查脚本。检查结果出来后，再修改 Spark 清洗逻辑去适配真实字段。
