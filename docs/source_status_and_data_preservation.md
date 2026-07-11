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

- 当前输入：`data/raw/who` 下 105 个指标 CSV，共 122,169 条原始记录。
- 处理：解析 WHO 记录 ID、国家、年份、年龄、性别、上下界和来源维度；跨采集主题重复记录去重；`No data` 保留在全指标目录但不填 0。
- 主序列：`HIV_0000000026` 清出 96 条年度新增 HIV 感染观测，覆盖 AUS、BRA、DEU、FRA、GBR、IND，进入 Gold、年度移动平均和下一年预测误差接口。
- 结核病：死亡率、治疗覆盖率和新发/复发病例仅作为辅助字段按 `ISO3 + year` 关联，不替换 Kaggle 结核病发病率主指标。
- 排除规则：监狱人群 COVID/HIV/TB 指标口径特殊；自动搜索误命中的 magnetic flux、fluoride toothpaste 等只进入目录，不进入疾病模型。
- 输出：`who_indicators_clean.csv`、`who_hiv_annual_clean.csv`、`who_tuberculosis_auxiliary_clean.csv`。
- 当前状态：`ok`。状态依据本地文件和实际清洗输出，不再取决于配置列表是否为空。

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
4. 统计频率或单位不同的数据不相加：COVID 为日病例，呼吸系统为周住院数，结核病为年度每 10 万人发病率，HIV 为年度新增感染估计数。
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
