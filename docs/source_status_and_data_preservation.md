# 数据源状态与保留式清洗

## 状态含义

网页“数据源状态”不再把所有未入模来源都标为 `warn`：

| 状态 | 页面文字 | 含义 |
|---|---|---|
| `ok` | 正常 | 已读取并产生可用的 Silver、Gold 或模型结果 |
| `info` | 说明 | 已清洗和保存，但因口径或解析风险不直接作为模型目标 |
| `not_configured` | 未配置 | 配置中主动关闭或没有选择指标，不属于数据错误 |
| `warn` | 需检查 | 文件缺失、配置后无输出、附件丢失或模型训练失败等真实异常 |

## 本次三个原警告的处理

### China CDC

- 原因：原状态只发现 27 行网页元数据，无法区分已清洗和待人工复核。
- 处理：按 `page_url` 去重并保留最新下载；解析报告类别、年、周、月；检查 HTML/PDF 本地文件；保留正文预览、页面 URL、附件 URL 和本地路径；提取周报正文中少量高置信摘要数字。
- 输出：`data/silver/local/china_cdc_metadata_clean.csv`。
- 当前状态：`info`。复杂 PDF 表格仍不自动充当病例标签，原始 HTML/PDF 不修改。

### WHO

- 原因：`config/settings.yaml` 中 `collectors.who.indicators: []`，因此 0 行是配置结果，不是缺失值或清洗失败。
- 处理：状态改为 `not_configured`。
- 启用条件：先明确需要的 WHO 指标代码，再配置采集；不能为了消除黄色状态伪造或补零。

### Kaggle 2012-2017 历史天气

- 原因：日期不与 COVID 主表重叠，且数据集在当前十国范围内只覆盖 USA。
- 处理：分块读取温度、湿度、气压、风速宽表；仅选择 27 个美国城市；温度由 Kelvin 转 Celsius；按年聚合为 6 行。
- 输出：`data/silver/local/historical_weather_annual_clean.csv`。
- 关联：`location_code = USA` 且 `year` 相同，只补充 2012-2017 年 USA 结核病记录；不与 COVID 强行关联。
- 当前状态：`ok`，页面会同时显示“原始 45,253 行 / 清洗 6 行”。聚合不是数据丢失，原小时表仍完整保留在 Raw 层。

## 数据保留规则

1. `data/raw` 永不被流水线覆盖。
2. 去重只发生在 Silver，保留原始 URL、行号和下载时间以便追溯。
3. 没有天气的疫情行继续保留，天气是可选特征。
4. 统计频率或单位不同的数据不相加：COVID 为日病例，呼吸系统为周住院数，结核病为年度每 10 万人发病率。
5. 年度天气关联只使用同国家、同年份，不做跨年代填充。

## 运行与检查

```powershell
conda run --no-capture-output -n intership python scripts\build_local_serving_from_raw.py
conda run --no-capture-output -n intership python -m src.web.app
```

浏览器打开 `http://127.0.0.1:5000`。接口检查：

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/source-status
Invoke-RestMethod "http://127.0.0.1:5000/api/weather-correlation?disease=Tuberculosis&location=USA&start_date=2012-01-01&end_date=2017-12-31"
```
