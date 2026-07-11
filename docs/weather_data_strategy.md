# 天气数据策略

生成日期：2026-07-10

## 1. 问题结论

当前已下载的 Kaggle 天气数据日期范围为 2012-10-01~2017-11-30，而疫情主表日期范围为 2020-01-22~2021-05-29，日期完全不重叠。

因此不能把 2012-2017 年天气数据和 2020-2021 年疫情数据按日期强行关联。

## 2. Kaggle 天气搜索状态

已实际执行：

```powershell
kaggle --version
```

真实结果：当前环境未安装 Kaggle CLI，命令返回 `The term 'kaggle' is not recognized`。

因此本阶段没有使用 Kaggle CLI 搜索或下载新的天气数据，也没有伪造 Kaggle 候选数据集检查结果。

如后续手动查找 Kaggle 天气数据，推荐关键词：

- `global daily weather 2020 2021`
- `historical weather covid 2020 2021`
- `daily temperature precipitation country`
- `weather data by city 2020 2021`

## 3. 最终天气补充数据源

采用 Open-Meteo Archive API 补充日频天气数据。首批范围为 2020-01-22 至 2021-05-29；为匹配当前 COVID 默认窗口，又补充了 2024-01-17 至 2025-01-16。

API：

- `https://archive-api.open-meteo.com/v1/archive`

本阶段实际验证 API 返回了以下日频字段：

| API 字段 | 本项目字段 | 单位 |
| --- | --- | --- |
| `temperature_2m_mean` | `temperature_mean` | °C |
| `temperature_2m_max` | `temperature_max` | °C |
| `temperature_2m_min` | `temperature_min` | °C |
| `precipitation_sum` | `precipitation_sum` | mm |
| `relative_humidity_2m_mean` | `relative_humidity_mean` | % |
| `wind_speed_10m_max` | `wind_speed_max` | km/h |

这些字段由日频接口直接返回，本阶段没有使用小时数据聚合。

## 4. 代表城市天气代理变量

疫情数据是国家级，天气数据来自具体经纬度。当前采用“代表城市天气代理变量”的方式：

- China -> Beijing
- United States -> Washington DC
- United Kingdom -> London
- France -> Paris
- Germany -> Berlin
- India -> New Delhi
- Brazil -> Brasilia
- Japan -> Tokyo
- South Korea -> Seoul
- Australia -> Canberra

后续候选国家和代表城市维护在：

- `config/weather_locations.csv`

重要限制：

代表城市天气仅作为国家天气背景的近似代理，不代表整个国家的气象状况，因此天气相关结论只能作为课程项目中的探索性分析。

## 5. 保存目录和元数据

原始天气数据保存到：

- `data/raw/open_meteo/<location_code>/`

当前保留原 CHN、USA、GBR 的 2020/2021 文件，并新增 AUS、BRA、CHN、DEU、FRA、GBR、IND、JPN、KOR、USA 的 2024/2025 文件。命名格式统一为：

- `data/raw/open_meteo/<ISO3>/open_meteo_<ISO3>_<year>.csv`

每个 CSV 旁边保存 `.meta.json`，包含：

- `source`
- `source_url`
- `request_url`
- `request_params`
- `downloaded_at`
- `location`
- `location_code`
- `representative_city`
- `latitude`
- `longitude`
- `start_date`
- `end_date`
- `record_count`
- `fields`
- `units`

## 6. 小规模采集验证结果

已实际运行：

```powershell
python scripts\download_weather_data.py --location-codes CHN USA GBR --start-date 2020-01-22 --end-date 2021-05-29
```

结果：

| location_code | files | date range | rows | duplicate date |
| --- | ---: | --- | ---: | ---: |
| CHN | 2 | 2020-01-22~2021-05-29 | 494 | 0 |
| USA | 2 | 2020-01-22~2021-05-29 | 494 | 0 |
| GBR | 2 | 2020-01-22~2021-05-29 | 494 | 0 |

已实际运行：

```powershell
python scripts\validate_dataset_overlap.py --output-json data\serving\dataset_overlap_validation.json
```

关键结果：

- 疫情与天气国家交集：3 个，`CHN, GBR, USA`
- 疫情与天气日期交集：2020-01-22~2021-05-29

## 7. COVID 默认窗口扩充结果

已实际运行：

```powershell
conda run --no-capture-output -n intership python scripts\download_weather_data.py --location-codes AUS BRA CHN DEU FRA GBR IND JPN KOR USA --start-date 2024-01-17 --end-date 2025-01-16
```

结果为 20 个 CSV 和 20 个 `.meta.json`：10 个国家各 366 行，共 3,660 行；日期重复数为 0；`temperature_mean`、`relative_humidity_mean`、`precipitation_sum` 缺失数均为 0。重新运行本地流水线后，Open-Meteo 清洗表共有 5,142 行，特征表天气匹配行数为 5,377。中国 COVID 默认窗口返回 366 个 `exact_day` 匹配点，`fallback_used=false`。
- 每个已采集国家共同日期数：494
- 天气 `location_code + date` 重复键数量：0
- 日期解析错误：0

## 7. 后续扩展建议

后续可在确认当前 3 国清洗逻辑稳定后，再逐步采集：

- France, Germany, Italy, Spain
- Russia, India, Brazil
- Japan, South Korea, Canada, Australia

每次扩展后都应重新运行：

```powershell
python scripts\validate_dataset_overlap.py --output-json data\serving\dataset_overlap_validation.json
```
