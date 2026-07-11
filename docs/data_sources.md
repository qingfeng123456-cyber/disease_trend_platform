# 数据来源

## OWID

- 内容：国家-日期级 COVID-19 数据。
- 入口：`https://catalog.ourworldindata.org/garden/covid/latest/compact/compact.csv`
- 采集器：`src.collectors.owid_collector`
- 说明：自动保存原始 CSV、来源 URL、字段报告和采集时间。

## Open-Meteo

- 内容：历史温度、降水、湿度、风速、气压。
- 入口：`https://archive-api.open-meteo.com/v1/archive`
- 采集器：`src.collectors.open_meteo_collector`
- 说明：地区来自 `config/locations.csv`，按年份分批请求，已有完整文件会跳过。

## World Bank

- 内容：人口、城市化率、人均 GDP。
- 指标：`SP.POP.TOTL`、`SP.URB.TOTL.IN.ZS`、`NY.GDP.PCAP.CD`
- 采集器：`src.collectors.world_bank_collector`

## WHO GHO

- 内容：可扩展健康指标。
- 采集器：`src.collectors.who_collector`
- 示例：

```bash
python -m src.collectors.who_collector --indicators WHOSIS_000001
```

## 中国疾控中心

- 内容：公开页面标题、发布时间、附件 URL、本地归档路径。
- 采集器：`src.collectors.china_cdc_collector`
- 说明：只采集无需登录的公开页面和公开附件。HTML/PDF/Excel 解析与下载分开，无法稳定解析时进入人工核查。

## Demo 数据

```bash
python -m src.collectors.generate_demo_data
```

固定随机种子，生成完整演示所需的疫情、天气、人口、预测、风险、质量报告和 API JSON。
