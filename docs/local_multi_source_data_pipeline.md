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

当前 `config/settings.yaml` 中的国家范围为 `CHN, USA, JPN, KOR, GBR, FRA, DEU, IND, BRA, AUS`。修改 `collectors.countries` 后可扩展 serving 范围。

## 明确不强行合并的数据

- Kaggle 2012-2017 小时天气与 2020 年后的疫情不重叠，只保留为原始资料，不进入特征表。
- 中国疾控 HTML/PDF 当前为页面元数据和人工复核材料，尚无稳定的逐病种数值表，因此不猜测解析病例数。
- WHO 目录没有配置指标或本地 CSV，流水线会在数据源状态中标记为未配置。
- 结核病年度发病率、COVID 日病例和呼吸系统周住院人数单位不同，不放进同一个模型训练目标，也不计算跨疾病病例总量占比。

## 温湿度关联图

`/api/weather-correlation` 按当前疾病、地区和日期过滤同期记录，并返回：

- `temperature_correlation`：温度与当前平滑指标的 Pearson 相关系数；
- `humidity_correlation`：湿度与当前平滑指标的 Pearson 相关系数；
- `sample_size`：有效匹配点数量；
- `message`：无同期天气时的原因。

图中横轴为温度，纵轴为当前疾病指标，颜色表示湿度。相关性只表示统计关联，不代表因果关系。当前 Open-Meteo 文件覆盖 CHN、GBR、USA 的 2020-01-22 至 2021-05-29；RSV 数据从 2023-10 开始，因此 RSV 暂无同期天气点是符合真实日期范围的结果。

## 运行顺序

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_local_real_pipeline.ps1
```

只构建数据、不启动 Flask：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_local_real_pipeline.ps1 -BuildOnly
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
- `data/gold/local/forecast_features.csv`：保留无天气行的统一特征表；
- `data/serving/local_real_pipeline_manifest.json`：来源、口径、关联和质量报告。
