# 数据字典

## 疫情日频表

| 字段 | 说明 |
|---|---|
| date | 统计日期 |
| location | 地区名称 |
| location_code | ISO3 地区代码 |
| continent | 大洲 |
| disease | 标准疾病名称 |
| new_cases_raw | 原始新增病例 |
| new_cases_clean | 建模用新增病例，负数修订截断为 0 |
| is_negative_correction | 是否为负数历史修订 |
| total_cases | 累计病例 |
| new_deaths | 新增死亡 |
| total_deaths | 累计死亡 |
| new_cases_smoothed | 平滑新增病例 |
| population | 人口 |
| source | 数据来源 |
| collected_at | 采集时间 |

## 特征表

包含 `lag_1`、`lag_3`、`lag_7`、`lag_14`、`rolling_mean_3`、`rolling_mean_7`、`rolling_mean_14`、`rolling_std_7`、`rolling_std_14`、`growth_rate_1`、`growth_rate_7`、`day_of_week`、`month`、`is_weekend`、`cases_per_million`、`deaths_per_million`、`temperature_mean`、`relative_humidity_mean`、`precipitation_sum`、`population`、`urban_population_ratio`、`gdp_per_capita`。

预测目标 `target_t_plus_7` 不作为输入特征：日频表示未来第 7 天，周频表示下一周，年频表示下一年。字段名为兼容既有接口而保留。

## 历史天气日表

`historical_weather_daily_clean.csv` 将 27 个美国城市的小时观测按自然日聚合，主键为 `location_code + date`。`temperature_mean`、`relative_humidity_mean`、`pressure_mean_hpa`、`wind_speed_mean` 是全部有效城市小时观测的日均值；对应的 `*_observations` 记录实际参与聚合的观测数，温度和风速还保留日极值。`historical_weather_annual_clean.csv` 是用于 USA 结核病同年探索性关联的精确观测加权年度派生表，不代表只清洗出了 6 条原始数据。

## WHO 指标表

| 字段 | 说明 |
|---|---|
| who_record_id | WHO endpoint 内的原始记录 ID，用于跨文件去重 |
| indicator_code / indicator_name | WHO 指标代码和名称 |
| location_code / location_type | ISO3 或 WHO 地区代码及地区层级 |
| year / date | 统计年份及统一后的年末日期 |
| numeric_value_clean | 可安全转换的数值；`No data` 保持为空 |
| low / high | WHO 估计区间下界和上界 |
| unit | 原单位或根据官方指标名称推断的 count、percent、per_100k |
| dimension_1_* ... dimension_3_* | 从 `raw_json` 解析的年龄、性别等维度 |
| usage_class | 主 HIV 序列、辅助特征、特殊人群参考、误匹配或目录保留 |
| quality_flag | 无数值、未来年份、关键词误匹配等质量标记 |
| duplicate_source_count | 同一 WHO 记录在采集文件中出现的副本数量 |
| duplicate_source_files / duplicate_collector_topics | 同一记录出现过的全部 Raw 文件和采集主题 |
| duplicate_content_variant_count | 同一 WHO 记录 ID 对应的不同内容版本数 |
| duplicate_content_conflict | 同一记录 ID 是否存在字段冲突；冲突时保留更新时间较新的版本并标记 |

WHO HIV 主序列另外保留 `who_estimate_low`、`who_estimate_high` 和 `hiv_prevalence_adults_percent`。结核病特征表现有 18 个 WHO 国家年度辅助指标，覆盖死亡、发病、通知、治疗覆盖、治疗成功、HIV 共病、MDR/RR 检测与治疗；每个指标同时保留可用的 `_low`、`_high` 区间字段。完整字段可查看 `data/silver/local/who_tuberculosis_auxiliary_clean.csv`。

## 风险指数

```text
risk_score =
0.40 * 近期病例水平归一化
+ 0.25 * 病例增长率归一化
+ 0.20 * 预测病例水平归一化
+ 0.15 * 异常程度归一化
```

风险等级：

- 低风险：0-35
- 中风险：35-55
- 较高风险：55-75
- 高风险：75-100

该风险指数是课程项目中的分析指标，不等同于公共卫生部门正式风险等级，不能用于医疗决策。
