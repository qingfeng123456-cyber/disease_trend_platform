# 国家名称映射报告

生成日期：2026-07-10

本报告基于真实读取：

- `data/raw/kaggle/epidemic/novel-corona-virus-2019-dataset/archive (2)/covid_19_data.csv`
- `data/raw/kaggle/population/world-population-dataset/world_population.csv`
- `config/country_name_mapping.csv`
- `data/serving/dataset_overlap_validation.json`

## 1. 映射目标

疫情表使用 `Country/Region`，人口表使用 `Country/Territory` 和 `CCA3`。为了后续 Spark 清洗和建模，统一输出：

- `standard_name`
- `location_code`

最终关联键：

- 疫情表：标准化后 `location_code + date`
- 人口表：`location_code + year`
- Open-Meteo 天气表：`location_code + date`

## 2. 映射结果

| 指标 | 结果 |
| --- | ---: |
| 疫情原始国家/地区名数量 | 228 |
| 人口表 ISO3 代码数量 | 234 |
| 已生成映射行数 | 228 |
| 可用人口映射行数 | 223 |
| 行级映射成功率 | 97.807% |
| 疫情与人口唯一 ISO3 交集数量 | 209 |

`223` 表示疫情表原始国家/地区名中有 223 行可映射到人口表；`209` 表示映射后去重的唯一 ISO3 国家代码数量。两者不同，是因为多个疫情原始名称可能映射到同一个国家代码，例如 `UK` 和 `North Ireland` 都归到 `GBR`。

## 3. 重点国家名称检查

| 疫情原始名称 | 人口表名称 | standard_name | location_code | 处理方式 |
| --- | --- | --- | --- | --- |
| `US` | United States | United States | USA | 手工映射 |
| `Mainland China` | China | China | CHN | 手工映射 |
| `UK` | United Kingdom | United Kingdom | GBR | 手工映射 |
| `Russia` | Russia | Russia | RUS | 手工映射 |
| `South Korea` | South Korea | South Korea | KOR | 手工映射 |
| `Taiwan` | Taiwan | Taiwan | TWN | 手工映射 |
| `Congo (Brazzaville)` | Republic of the Congo | Republic of the Congo | COG | 手工映射 |
| `Congo (Kinshasa)` | DR Congo | DR Congo | COD | 手工映射 |
| `Burma` | Myanmar | Myanmar | MMR | 手工映射 |
| `Vietnam` | Vietnam | Vietnam | VNM | 手工映射 |
| `West Bank and Gaza` | Palestine | Palestine | PSE | 手工映射 |
| `occupied Palestinian territory` | Palestine | Palestine | PSE | 手工映射 |
| `East Timor` | Timor-Leste | Timor-Leste | TLS | 手工映射 |
| `North Ireland` | United Kingdom | United Kingdom | GBR | 手工映射 |

重点说明：

- 当前疫情表未出现 `Côte d'Ivoire` 这个原始写法，实际出现的是 `Ivory Coast`，可直接映射到人口表。
- 当前疫情表未出现 `Korea, South`，实际出现的是 `South Korea`。
- `North Ireland` 是历史原始名称，当前映射到 `United Kingdom`，后续清洗时应在国家级聚合前统一到 `GBR`。

## 4. 未映射或禁用名称

| 疫情原始名称 | 原因 |
| --- | --- |
| `Channel Islands` | 人口表没有单一对应 CCA3，且该行代表复合地区 |
| `Diamond Princess` | 非国家级人口实体 |
| `Kosovo` | 当前人口文件没有可匹配 CCA3 行 |
| `MS Zaandam` | 非国家级人口实体 |
| `Others` | 非明确国家级人口实体 |

这些名称保留在 `config/country_name_mapping.csv` 中，`enabled=false`，后续清洗不能静默删除，应在数据质量报告中统计。

## 5. 疫情表国家日期粒度检查

实际检查结果：

- 完全重复行：0
- 同一国家、同一日期、同一省州重复键：5 个
- 同一国家同一天存在多个省州行：9099 个国家-日期组合
- 同一国家同一天同时存在空省州行和省州行：1065 个国家-日期组合

重复键示例：

| country | date | province | count |
| --- | --- | --- | ---: |
| Mainland China | 2020-01-23 | Hubei | 2 |
| Mainland China | 2020-03-11 | Hebei | 2 |
| Mainland China | 2020-03-11 | Gansu | 2 |
| Mainland China | 2020-03-12 | Hebei | 2 |
| Mainland China | 2020-03-12 | Gansu | 2 |

国家总行和省州行并存示例：

| country | date | rows | blank_province | nonblank_province |
| --- | --- | ---: | ---: | ---: |
| Denmark | 2020-03-22 | 3 | 1 | 2 |
| France | 2020-03-22 | 10 | 1 | 9 |
| Netherlands | 2020-03-22 | 4 | 1 | 3 |
| UK | 2020-03-22 | 8 | 1 | 7 |

因此，疫情清洗必须先处理同一省州同日重复记录，再谨慎处理国家总行和省州行并存问题，最后按国家日期聚合。

## 6. 后续清洗规则

疫情字段转换：

- `ObservationDate` -> `date`
- `Country/Region` -> `epidemic_name`
- `Province/State` -> `province`
- `Confirmed` -> `total_cases`
- `Deaths` -> `total_deaths`
- `Recovered` -> `total_recovered`
- `SNo`、`Last Update` 不进入模型特征

新增病例生成规则：

- 先在国家-日期累计值层面排序
- 再计算差分
- `new_cases_raw` 保留原始差分
- `new_cases_clean = greatest(new_cases_raw, 0)`
- `new_deaths_raw` 保留原始差分
- `new_deaths_clean = greatest(new_deaths_raw, 0)`
- `is_negative_case_correction` 标记负数病例修订
- `is_negative_death_correction` 标记负数死亡修订

人口规则：

- 2020 年疫情记录使用 `2020 Population`
- 2021 年疫情记录继续使用最近可用历史值 `2020 Population`
- 不使用 `2022 Population` 填补 2020 或 2021，避免未来数据泄漏

天气规则：

- Open-Meteo 天气通过 `location_code + date` 与疫情国家日期表关联
- 代表城市天气只作为国家天气背景的近似代理，不代表全国气象状况
