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

预测目标 `target_t_plus_7` 表示未来第 7 天新增病例平滑值，不作为输入特征。

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
