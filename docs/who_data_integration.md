# WHO 数据清洗与全链路接入

## 原始数据结论

`data/raw/who` 当前包含 105 个 WHO GHO CSV、122,169 条记录和 80 个有数据的唯一指标。所有 Raw 文件保持不变。

自动按疾病关键词下载的文件不能直接全部入模：

- `HIV_0000000026` 是各国年度新增 HIV 感染估计数，适合作为年度趋势主序列；
- `MDG_0000000017`、`TB_1`、`TB_c_newinc` 分别用于结核病死亡率、治疗覆盖率和新发/复发病例辅助字段；
- `PRISON_*` 是监狱人群特殊口径，不能替代全国指标；
- magnetic flux、fluoride toothpaste 等是旧关键词子串匹配造成的误采集，只保留用于审计；
- `No data` 表示 WHO 没有数值，不能清洗为 0。

## Silver 输出

### `who_indicators_clean.csv`

全指标目录。解析并保留：

- `indicator_code`、`indicator_name`、`location_code`、`location_type`、`year`；
- `numeric_value_clean`、`low`、`high`、`unit`；
- `dimension_1_*` 至 `dimension_3_*`、`sex`、`age`；
- `who_record_id`、父级地区、更新时间和原始文件路径；
- `usage_class`、`quality_flag`、`duplicate_source_count`。

跨主题重复数据使用 `indicator_code + who_record_id` 去重。本批 4,677 个重复键都只出现两次，全部来自 `MDG_0000000017` 同时被 HIV 和 tuberculosis 主题采集；两份记录逐字段完全一致，内容冲突为 0。原始 122,169 行全部留在 Raw，Silver 保留 117,492 条独立 WHO 记录，并增加全部来源文件、采集主题、内容版本数和冲突标记。

同时生成：

- `who_duplicate_audit.csv`：4,677 个重复键的来源、值和冲突审计；
- `who_indicator_summary.csv`：80 个指标的记录数、数值行数、项目国家覆盖、年份、单位、用途和重复副本数；
- `data/serving/who_indicator_summary.json`：供 Flask 查询的指标摘要。

### `who_hiv_annual_clean.csv`

使用 `HIV_0000000026`，仅保留：

- `location_type = COUNTRY`；
- 项目配置的 ISO3 国家；
- 非负且真实存在的 `numeric_value`。

当前输出 96 行、6 个国家、2000-2024 年。上下界保存在 `who_estimate_low/high`，成年人 HIV 流行率保存在 `hiv_prevalence_adults_percent`。数据空缺不插值。

### `who_tuberculosis_auxiliary_clean.csv`

按 `location_code + year` 生成 288 行十国辅助表。安全的国家年度标量指标从 3 个扩展到 18 个，包含死亡、HIV 阳性结核发病、病例通知、治疗覆盖和成功率、HIV 检测/ART、MDR/RR 检测及治疗等。它与 Kaggle 结核病主表左连接，230 行主表全部至少匹配一项 WHO 字段；不会增加重复趋势行，也不会改变“每 10 万人估计发病率”主指标。

当前 WHO 目录有 4,787 条项目国家数值记录，其中 3,069 条被分类为主序列辅助特征。维度化、特殊人群或统计口径不兼容的数据继续保存在目录和摘要 API，不会为了提高表面利用率而混入预测目标。

## Gold 与模型

HIV/AIDS 进入 `data/gold/local/forecast_features.csv`，并获得人口、GDP、城市化率、滞后值、3 年移动平均、增长率和下一年目标。当前 96 行人口均成功匹配，90 行具有下一年目标。

模型规则：

- HIV/AIDS 使用年度 `naive_last_value`、`moving_average` 基线和独立的 PyTorch LSTM；
- HIV LSTM 使用 3 年输入窗口预测下一年，模型、标准化器和时间切分均与其他疾病隔离；
- COVID 日频数据继续使用 sklearn GBDT 和独立 PyTorch LSTM；
- 不把年度 HIV 数据强行转换为日频，也不把不同疾病单位混成一个模型目标。

## Web 接入

重新运行流水线后：

- 疾病下拉框新增 `HIV/AIDS`；
- 地区只显示有 WHO 数值的 6 个国家；
- 趋势图显示年度新增 HIV 感染数和 3 年移动平均；
- 预测误差接口返回 90 条下一年基线预测记录；
- 风险地图、排行榜、疾病覆盖图和数据源状态同步包含 WHO/HIV；
- `/api/source-status` 显示 WHO 清洗行数和 HIV 主序列行数。
- `/api/who-indicators` 返回 80 个 WHO 指标的用途与覆盖摘要；
- 结核病趋势 API 的每个年度点可携带 18 个 WHO 辅助值及其区间字段。

## 运行命令

```powershell
conda run --no-capture-output -n intership python scripts\build_local_serving_from_raw.py
conda run --no-capture-output -n intership python -m src.web.app
```

HIV 接口示例：

```text
/api/trend?disease=HIV%2FAIDS&location=BRA&start_date=2000-01-01&end_date=2024-12-31&model=moving_average
/api/predictions?disease=HIV%2FAIDS&location=BRA&model=moving_average
```
