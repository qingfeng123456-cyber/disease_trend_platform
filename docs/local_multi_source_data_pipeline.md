# Windows 本地多源真实数据流水线

## 当前采用的数据方案

本地流水线会读取真实文件并统一为 `location_code + disease + date` 观测表，但保留各来源的统计频率和指标单位，不把不同口径相加。

| 数据源 | 项目用途 | 频率与指标 | 清洗决策 |
|---|---|---|---|
| OWID COVID compact | COVID-19 主表、模型主数据 | 国家级日新增病例 | 过滤 ISO3 国家代码和配置日期；优先采用官方 `new_cases`/平滑值 |
| Kaggle COVID-19 daily reports | COVID 数据质量交叉检查 | 国家级日累计病例 | 与 OWID 比较，不追加、不求和，避免重复病例 |
| Kaggle Tuberculosis 六个 CSV | 结核病趋势及辅助指标 | 年度发病率（每 10 万人） | 发病率作为趋势主指标；死亡、发现率、治疗成功率、HIV 占比保留在 Silver 表 |
| Weekly Hospital Respiratory Data and Metrics | 流感、RSV、新冠住院趋势 | 美国全国周新增住院入院人数 | 直接使用文件内 `USA` 全国行，不再次汇总州数据；0-1 百分比转换为 0-100 |
| World Bank + Kaggle World Population | 人口、GDP、城市化、密度 | 国家年度 | 同年 World Bank 优先；人口年份间线性插值并标记，OWID 人口作为后备值 |
| Open-Meteo | 同期温度、湿度、降水特征 | 国家代表城市日频 | 日数据精确关联；周数据聚合到周六；无天气时保留疫情记录 |
| Kaggle historical hourly weather | 历史天气保留、美国结核病天气探索 | 2012-2017 小时数据转国家日均和年度均值 | 分块读取 27 个美国城市；保留 1,887 个国家日记录及观测数；另派生 6 个年度均值，只关联同年 USA 结核病，不拼接 COVID |
| China CDC HTML/PDF | 官方报告索引和人工复核 | 2026 年网页、周报及附件 | URL 去重，解析类别/年/周/月，检查本地附件，提取高置信正文摘要；原文件不覆盖 |
| WHO GHO OData | HIV/AIDS 年度趋势、结核病辅助指标和完整指标目录 | 国家年度及部分特殊维度 | `HIV_0000000026` 作为年度新增感染主序列；18 个结核病国家年度指标按 ISO3+year 左连接；其余记录进入目录、摘要和重复审计，不跨口径入模 |

当前 `config/settings.yaml` 中的国家范围为 `CHN, USA, JPN, KOR, GBR, FRA, DEU, IND, BRA, AUS`。修改 `collectors.countries` 后可扩展 serving 范围。

## COVID 日期连续性与报告节奏

Kaggle `covid_19_data.csv` 覆盖 2020-01-22 至 2021-05-29，只用于与 OWID 重叠期交叉校验；2024 年图表不可能来自该文件。OWID 主表覆盖到 2025 年，并保留来源发布的 `new_cases` 和 `new_cases_smoothed`，其他数据集不会覆盖或叠加这些值。

中国 2024-08-25 至 2024-11-05 的核查结果为 73 个自然日、73 行、缺失日期 0；其中 51 天的 OWID 原始新增值为 0，反映来源在该时期以批次方式更新，并非清洗删行。网页对这种“日期完整但报告值稀疏”的窗口使用柱形显示原始报告值，继续用 7 日均线表达趋势。预测点使用 `forecast_target_date` 对齐到真正的 t+7 目标日，不再画在预测发起日。

## 明确不强行合并的数据

- Kaggle 2012-2017 小时天气不与 COVID 强行关联；它仅进入 2012-2017 年 USA 结核病年度特征。
- 中国疾控 HTML/PDF 已生成结构化 Silver 索引，但复杂 PDF 图表不作为模型标签，避免错误抽数。
- WHO 的 `No data` 不填 0；年龄、性别和来源维度从 `raw_json` 解析保留。跨采集主题的同一 WHO 记录按指标代码和 WHO 记录 ID 去重，Raw 文件不删除。
- 结核病年度发病率、HIV 年度新增感染数、COVID 日病例和呼吸系统周住院人数单位不同，不放进同一个训练目标，也不跨疾病相加。

## 温湿度关联图

`/api/weather-correlation` 按当前疾病、地区和日期过滤同期记录，并返回：

- `temperature_correlation`：温度与当前平滑指标的 Pearson 相关系数；
- `humidity_correlation`：湿度与当前平滑指标的 Pearson 相关系数；
- `sample_size`：有效匹配点数量；
- `message`：无同期天气时的原因。

图中横轴为温度，纵轴为当前疾病指标，颜色表示湿度。相关性只表示统计关联，不代表因果关系。Open-Meteo 原有文件覆盖 CHN、GBR、USA 的 2020-01-22 至 2021-05-29；2026-07-11 又补充了 10 个项目国家在 2024-01-17 至 2025-01-16 的日频天气。页面默认展示当前疾病和地区清洗后的完整日期范围，天气图只显示该完整范围内真正有同期匹配的日期，不伪造中间缺失天气。

复现本次天气补充并重新导出网页数据：

```powershell
conda run --no-capture-output -n intership python scripts\download_weather_data.py --location-codes AUS BRA CHN DEU FRA GBR IND JPN KOR USA --start-date 2024-01-17 --end-date 2025-01-16
conda run --no-capture-output -n intership python scripts\build_local_serving_from_raw.py
```

选择 `Tuberculosis + USA + 2012-2017` 时，接口会使用 Kaggle 历史天气年度聚合结果。该样本只有 6 个年度点，只适合课程中的探索性展示，不作为因果结论。

## 运行顺序

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_local_real_pipeline.ps1
```

只构建数据、不启动 Flask：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_local_real_pipeline.ps1 -BuildOnly
```

训练 LSTM 时默认启用验证集早停，`-LstmEpochs 40` 表示最多 40 轮，并不保证一定跑满。强制完整训练 40 轮：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_local_real_pipeline.ps1 -EnableLstm -LstmEpochs 40 -DisableLstmEarlyStopping -BuildOnly
```

保留早停但提高耐心值可使用 `-LstmPatience 10`。流水线会依次训练 COVID-19、流感、RSV、结核病、HIV/AIDS 和新冠住院 6 个原生频率 LSTM；训练日志会按疾病打印窗口数、数据分区、参数量、每轮批次数、最佳轮次和早停状态。

构建后执行全链路检查：

```powershell
conda run --no-capture-output -n intership python scripts\verify_local_pipeline.py
```

手动启动网页：

```powershell
conda run --no-capture-output -n intership python -m src.web.app
```

如果 Flask 已在运行但本次修改了 Python 后端代码，应先在原终端按 `Ctrl+C`，再重新启动。浏览器打开 `http://127.0.0.1:5000` 并强制刷新一次。

## 主要输出

- `data/silver/local/epidemic_observations_clean.csv`：多疾病标准观测表；
- `data/silver/local/owid_covid_daily_clean.csv`：OWID COVID 日表；
- `data/silver/local/kaggle_covid_validation_clean.csv`：Kaggle 校验表；
- `data/silver/local/tuberculosis_annual_clean.csv`：结核病年度主指标和辅助字段；
- `data/silver/local/respiratory_weekly_clean.csv`：美国呼吸系统周报宽表；
- `data/silver/local/historical_weather_daily_clean.csv`：27 个美国城市小时观测聚合后的 1,887 个国家日记录，保留各指标观测数和极值；
- `data/silver/local/historical_weather_annual_clean.csv`：美国历史小时天气的年度聚合表；
- `data/silver/local/china_cdc_metadata_clean.csv`：China CDC 去重后的报告和附件索引；
- `data/silver/local/who_indicators_clean.csv`：WHO 全指标去重目录及维度、用途和质量标记；
- `data/silver/local/who_hiv_annual_clean.csv`：可进入趋势和年度基线预测的 HIV/AIDS 主序列；
- `data/silver/local/who_tuberculosis_auxiliary_clean.csv`：18 个 WHO 结核病国家年度辅助指标及区间宽表；
- `data/silver/local/who_duplicate_audit.csv`：WHO 跨主题重复来源和内容冲突审计；
- `data/silver/local/who_indicator_summary.csv`：80 个 WHO 指标的用途、覆盖和数值可用性摘要；
- `data/gold/local/forecast_features.csv`：保留无天气行的统一特征表；
- `data/serving/model_data_coverage.json`：逐疾病、逐模型的真实数据覆盖和输入来源；
- `data/serving/local_pipeline_verification.json`：文件、模型、API 和端口自动检查结果；
- `data/serving/local_real_pipeline_manifest.json`：来源、口径、关联和质量报告。
