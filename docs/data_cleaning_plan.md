# Kaggle 原始数据清洗计划

本计划基于实际读取 `data/raw/kaggle` 中 CSV 后生成。本阶段不修改 Spark 作业。

## 1. 推荐使用文件

- 疫情主表：`epidemic/novel-corona-virus-2019-dataset/archive (2)/covid_19_data.csv`
- 天气表：`weather/historical-hourly-weather-data/temperature.csv`
- 人口/社会经济表：`population/world-population-dataset/world_population.csv`

## 2. 关联方式

- 疫情表与人口表：优先把疫情表国家名标准化，再与人口表 `CCA3`/国家名映射关联。
- 疫情表与天气表：天气数据先按小时聚合为日频，再把城市映射到国家，最后按 `date + country` 关联。
- 如果后续补充 ISO3 映射表，应统一输出 `location_code`。

## 3. 字段处理建议

### 疫情主表

- 保留/转换：
  - `ObservationDate` -> `date`，转换为 `YYYY-MM-DD`。
  - `Country/Region` -> `location`，后续映射为 `location_code`。
  - `Province/State` -> `province`，国家级分析可为空或聚合。
  - `Confirmed` -> `total_cases`，属于累计值。
  - `Deaths` -> `total_deaths`，属于累计值。
  - `Recovered` -> `total_recovered`，属于累计值。
- 注意：当前主表多为累计值，需要按地区和日期排序后用差分计算新增值，不能把累计值直接当新增病例。
- 删除或暂不进入模型：`SNo`、`Last Update`。

### 天气表

- `datetime` -> `date`，小时级聚合为日频。
- `temperature.csv` 通常为开尔文温度，需转换为摄氏度：`temperature_c = temperature_k - 273.15`。
- `humidity.csv` 单位通常为百分比，需检查 0-100 合法范围。
- 需要读取 `city_attributes.csv` 获取城市、国家、经纬度，再和天气宽表按城市列关联。
- 天气表是宽表，城市在列上，清洗时应转换成长表：`date, city, value`。

### 人口/社会经济表

- `Country/Territory` -> `location`。
- `CCA3` -> `location_code`。
- `2022 Population`、`2020 Population` 等年份列应转换成长表：`location_code, year, population`。
- `Density (per km²)` 可保留为人口密度特征。

## 4. 需要重点检查的问题

- weather data is city-based while epidemic data is country/province-based; a city-to-country mapping is required
- epidemic/novel-corona-virus-2019-dataset/archive (2)/covid_19_data.csv: negative public-health/population values in ['Confirmed', 'Deaths', 'Recovered']
- epidemic/novel-corona-virus-2019-dataset/covid_19_data.csv/covid_19_data.csv: negative public-health/population values in ['Confirmed', 'Deaths', 'Recovered']
- 国家名称不一致：疫情表国家名与人口表国家名可能不同，应建立国家名到 ISO3 的映射。
- 日期格式不一致：疫情表可能是 `MM/DD/YYYY`，天气表可能是 `YYYY-MM-DD HH:MM:SS`。
- 数据泄漏风险：预测目标必须用未来值构造，但输入特征只能使用当前日及历史日；累计值差分必须只用历史相邻日期。