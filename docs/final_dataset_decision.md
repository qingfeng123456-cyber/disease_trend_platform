# 最终数据方案修正

生成日期：2026-07-10

本文件基于已实际读取的 `docs/raw_data_profile.md`、`docs/data_cleaning_plan.md`、`data/serving/raw_data_profile.json`、`config/country_name_mapping.csv` 和 `data/serving/dataset_overlap_validation.json`。

## 1. 数据分层

### 方案 A：global_core

`global_core` 是本项目的全球核心数据集，只使用 Kaggle 已下载数据：

- 疫情数据：`data/raw/kaggle/epidemic/novel-corona-virus-2019-dataset/archive (2)/covid_19_data.csv`
- 人口数据：`data/raw/kaggle/population/world-population-dataset/world_population.csv`
- 国家映射表：`config/country_name_mapping.csv`

用途：

- 全球疫情趋势统计
- 全球风险地图
- 国家排行榜
- 时间序列预测
- Spark GBT 主模型
- 全球数据质量分析

`global_core` 的主粒度确定为 `location_code + date`，即国家-日期粒度。疫情表原始粒度混有国家、省州和地区行，不能直接作为模型主键。

### 方案 B：weather_enhanced

`weather_enhanced` 在 `global_core` 基础上补充同期天气数据：

- 疫情数据：同 `global_core`
- 人口数据：同 `global_core`
- 天气数据：`data/raw/open_meteo/<location_code>/open_meteo_<location_code>_<year>.csv`
- 天气位置配置：`config/weather_locations.csv`

已完成小规模验证国家：

| location | location_code | representative_city | weather date range | records |
| --- | --- | --- | --- | ---: |
| China | CHN | Beijing | 2020-01-22~2021-05-29 | 494 |
| United States | USA | Washington DC | 2020-01-22~2021-05-29 | 494 |
| United Kingdom | GBR | London | 2020-01-22~2021-05-29 | 494 |

`weather_enhanced` 先用于探索性天气增强分析和后续 Spark 清洗验证，不要求覆盖全部 228 个疫情国家。

## 2. 现有 Kaggle 天气数据处理

现有 Kaggle 天气数据：

- `data/raw/kaggle/weather/historical-hourly-weather-data/temperature.csv`
- 日期范围：2012-10-01~2017-11-30
- 疫情主表日期范围：2020-01-22~2021-05-29

两者日期完全不重叠，因此该 Kaggle 天气数据不得进入 `target_t_plus_7` 的同期疫情预测特征。

该数据保留为 `historical_climate_reference`，仅可用于：

- 历史城市气候展示
- 温度长期分布图
- Kaggle 数据处理示例
- Spark 宽表转长表展示

## 3. 疫情主表粒度规则

实际检查发现：

- 疫情表唯一国家/地区名：228 个
- 疫情日期范围：2020-01-22~2021-05-29，共 494 天
- 完全重复行：0
- 同一国家同一天存在多个省州行：9099 个国家-日期组合
- 同一国家同一天同时存在空省州行和省州行：1065 个国家-日期组合
- 同一国家、同一日期、同一省州重复键：5 个

因此清洗顺序必须是：

1. 标准化国家名称，生成 `standard_name` 和 `location_code`
2. 处理同一省州同一天重复记录
3. 按国家和日期聚合累计病例
4. 对聚合后的国家累计病例排序
5. 再使用差分生成新增病例

禁止直接把原始 `Confirmed` 当作新增病例，也禁止在未处理国家总行和省州行并存问题前直接求和。

## 4. 人口使用规则

人口表需要从宽表转换成长表：

- `Country/Territory` -> `location`
- `CCA3` -> `location_code`
- 年份人口列 -> `year, population`

疫情记录的人口匹配规则：

- 2020 年疫情记录使用 `2020 Population`
- 2021 年疫情记录如果没有 `2021 Population`，使用最近可用历史值 `2020 Population`
- 不允许用 `2022 Population` 填补 2020 或 2021，避免未来数据泄漏

## 5. 进入下一阶段判断

根据 `scripts/validate_dataset_overlap.py` 的真实运行结果：

- 至少 3 个国家天气采集成功：是
- 疫情和天气共同日期数至少 300：是，已验证国家均为 494 天
- 人口映射成功：是，已采集天气国家均有 CCA3 人口映射
- 日期字段可解析：是
- 天气与人口主键无明显重复：是
- raw 疫情表仍需在 Spark 清洗阶段先处理省州重复和国家聚合：是

结论：可以进入 Spark 清洗阶段，但不能直接进入模型训练阶段。
