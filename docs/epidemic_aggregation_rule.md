# 疫情国家-日期聚合规则

生成日期：2026-07-10

本规则基于真实读取：

- `data/raw/kaggle/epidemic/novel-corona-virus-2019-dataset/archive (2)/covid_19_data.csv`
- `config/country_name_mapping.csv`

目标输出粒度：

- `location_code + date`

## 1. 实际样本检查

指定国家检查结果：

| 国家 | 原始名称 | national_only | province_only | both |
| --- | --- | ---: | ---: | ---: |
| China | Mainland China | 0 | 494 | 0 |
| United States | US | 0 | 494 | 0 |
| United Kingdom | UK | 40 | 364 | 81 |
| Canada | Canada | 0 | 490 | 0 |
| Australia | Australia | 3 | 489 | 0 |
| France | France | 47 | 12 | 433 |

含义：

- `national_only`：同一国家同一天只有空省州行。
- `province_only`：同一国家同一天只有非空省州行。
- `both`：同一国家同一天同时有空省州行和非空省州行。

全表检查结果：

- 完全重复行：0
- 同一国家、同一日期、同一省州重复键：5 个
- 同一国家同一天存在多个省州行：9099 个国家-日期组合
- 同一国家同一天同时存在空省州行和省州行：1065 个国家-日期组合
- 1065 个冲突组合中，没有发现非空省州名等于国家名的重复国家主行。

## 2. 冲突样本观察

United Kingdom 在 2020-03-22：

- 空省州行累计确诊：5683
- 非空省州行累计确诊合计：58
- 非空省州包括 Bermuda、Cayman Islands、Channel Islands、Gibraltar、Isle of Man 等

France 在 2020-03-22：

- 空省州行累计确诊：16533
- 非空省州行累计确诊合计：196
- 非空省州包括 French Guiana、French Polynesia、Guadeloupe、Martinique、Mayotte、Reunion 等

Denmark 在 2020-03-22：

- 空省州行累计确诊：1395
- 非空省州行累计确诊合计：119
- 非空省州包括 Faroe Islands、Greenland

Netherlands 在 2020-03-22：

- 空省州行累计确诊：4204
- 非空省州行累计确诊合计：13
- 非空省州包括 Aruba、Curacao、Sint Maarten

这些样本显示：空省州行通常代表国家主体地区，非空省州行多为海外地区或属地，不是重复的国家总行。

## 3. 最终 Spark 聚合规则

清洗顺序：

1. 解析 `ObservationDate` 为 `date`。
2. 标准化国家名称，并通过 `config/country_name_mapping.csv` 映射 `location_code`。
3. 将空字符串 `Province/State` 统一为 null。
4. 按 `Country/Region + Province/State + ObservationDate` 检查重复。
5. 重复键使用确定性规则去重：优先 `Last Update` 较晚，其次 `SNo` 较大。
6. 按原始国家和日期统计是否存在国家行、省州行、冲突行。
7. 只存在国家行时，使用国家行累计值。
8. 只存在省州行时，使用省州行累计值之和。
9. 同时存在国家行和省州行时：
   - 如果发现非空省州名等于国家名或等于 `UK/United Kingdom` 这类国家主行，使用省州行合计，避免重复。
   - 当前真实数据未发现这种重复主行。
   - 当前真实数据默认使用 `国家行 + 省州行合计`，并标记 `aggregation_conflict=true`。
10. 多个疫情原始名称映射到同一 ISO3 后，再按 `location_code + date` 二次聚合。
11. 对国家-日期累计值排序后，再差分生成新增病例和新增死亡。

## 4. 负数修订处理

累计值差分可能出现负数，代表历史数据修订。

保留字段：

- `new_cases_raw`
- `new_cases_clean`
- `new_deaths_raw`
- `new_deaths_clean`
- `is_negative_case_correction`
- `is_negative_death_correction`

规则：

- 首日 `new_cases_raw = total_cases`
- 非首日 `new_cases_raw = total_cases - lag(total_cases)`
- `new_cases_clean = greatest(new_cases_raw, 0)`
- 死亡字段同理

不能删除负数修订信息。

## 5. 未映射国家处理

无法映射 ISO3 的原始名称不静默删除：

- 保留原始 `location`
- `location_code = null`
- 输出未映射清单
- 默认不进入需要人口关联的后续模型数据

当前未映射或禁用名称：

- Channel Islands
- Diamond Princess
- Kosovo
- MS Zaandam
- Others
