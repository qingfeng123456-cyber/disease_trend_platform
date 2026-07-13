# 实验报告（三）：预测模型、接口与疾病差异

## 1. 模型任务定义

本项目不是把所有疾病混在同一个回归目标中，而是按照疾病的真实数据频率分别建模：

- COVID-19：日频，预测未来第 7 天的日新增病例趋势；
- Influenza：周频，预测下一周住院入院数；
- RSV：周频，预测下一周住院入院数；
- COVID-19 Hospital Admissions：周频，预测下一周住院入院数；
- Tuberculosis：年频，预测下一年每 10 万人估计发病率；
- HIV/AIDS：年频，预测下一年新发感染估计值。

当前统一训练入口会为每种可用疾病生成基线结果，并在启用 `-EnableLstm` 时训练 6 个独立 LSTM。COVID 另有 sklearn GBDT。网页模型下拉框只显示该疾病实际可用的模型。

## 2. 模型及代码对应关系

| 模型 | 当前实现位置 | 适用疾病 | 模型文件/结果 |
|---|---|---|---|
| 最近值基线 | `scripts/build_local_serving_from_raw.py` 的训练编排 | 全部疾病 | 预测进入 Gold/Serving，无单独二进制模型 |
| 移动平均基线 | 同上 | 全部疾病 | 预测进入 Gold/Serving |
| HistGradientBoostingRegressor | 同文件 `fit_predict` | COVID 日频 | `data/models/local/local_sklearn_gbdt.joblib` |
| PyTorch LSTM | `src/models/lstm_optional.py` | 六种疾病各一套 | `data/models/local/*.pt` |
| Spark MLlib GBT | `src/spark_jobs/train_gbt.py` | 旧/可选 Spark COVID 路线 | HDFS 模型目录和预测 Parquet |
| 旧 Demo/CLI 基线 | `src/models/naive_baseline.py`、`src/models/run_models.py` | Demo 或旧路线 | Demo serving 文件 |

需要注意：当前真实本地 GBDT 的实现以 `scripts/build_local_serving_from_raw.py` 为准；`src/spark_jobs/train_gbt.py` 是另一条 Spark 路线，两者不是同一次训练。

## 3. 数据输入与输出总流向

```text
Silver 规范疾病观测
  -> build_features
  -> data/gold/local/forecast_features.csv
       |-> 最近值基线
       |-> 移动平均基线
       |-> sklearn GBDT（COVID）
       |-> 六个独立 PyTorch LSTM
  -> data/gold/local/*predictions.csv
  -> data/models/local/*.{joblib,pt}
  -> data/serving/model_metrics.json
  -> data/serving/predictions.json + trend.json
  -> Flask API -> 网页模型选择和图表
```

Flask 不加载 `.pt` 或 `.joblib` 在线推理。训练程序先离线生成预测 JSON，网页读取 JSON。因此重新训练后，只要 Serving 导出成功并刷新网页，结果就会自动出现；无需把 PyTorch 嵌入 Flask 请求处理。

## 4. 最近值基线

### 4.1 原理

最近值基线假设下一时间步与最近一次观测相同：

```text
y_hat(t+h) = y(t)
```

它没有可训练参数，但在缓慢变化或高度自相关的时间序列上很强。TB 年度发病率下降缓慢，最近值基线优于小样本 LSTM是合理现象，不代表 LSTM 接口没有运行。

### 4.2 实现与作用

- 对每个 `disease + location_code` 独立生成预测。
- 预测步长按疾病频率解释。
- 是所有疾病的最低复杂度参照，也是当前网页默认模型。
- 模型比较按测试集 MAE 选择最佳模型，复杂模型不会因为名称高级就自动成为最佳。

## 5. 移动平均基线

### 5.1 原理

移动平均使用最近若干个观测的平均值预测未来：

```text
y_hat(t+h) = mean(y(t-w+1), ..., y(t))
```

它能压低短期噪声和单次批量报告峰值。项目按真实频率采用不同窗口：日频通常 7 个观测，周频 4 周，年频 3 年。

### 5.2 实现细节

- 只使用当前及过去观测，避免未来泄漏。
- 每个地区独立滚动。
- 数据不足一个完整窗口时按已有历史计算或遵守最小观测规则。
- Serving 的趋势图还显示移动平均线，但显示线不等于模型训练目标。

## 6. sklearn GBDT

### 6.1 原理

当前采用 `sklearn.ensemble.HistGradientBoostingRegressor`。梯度提升依次训练多棵较小的回归树，每一轮重点拟合前面模型的残差；最终预测是多轮树模型的累加。直方图算法先把连续特征分箱，训练大表时比传统精确切分更快。

官方类说明：`https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html`。

### 6.2 当前实现

- 代码：`scripts/build_local_serving_from_raw.py` 中 `fit_predict`。
- 适用：当前仅 COVID 日频。
- 切分：按时间 70%/15%/15%，不随机打乱。
- 迭代：最多约 120 棵/轮次，以 20 为一段输出进度。
- 主要参数：学习率约 0.06、最大叶子数 31、固定随机种子 2026。
- 模型保存：`data/models/local/local_sklearn_gbdt.joblib`。

### 6.3 输入特征

COVID 的特征主要包括：

- 病例历史：滞后 1/7/14/21/28 日、7/14/28 日滚动均值和标准差、增长率；
- 日历：星期、月份、年内序号等；
- 天气：温度、湿度、降水、风速及 `has_weather`；
- 社会经济：人口、人口密度、城市化率、人均 GDP；
- 地区：ISO3 one-hot/编码特征；
- 目标：与 `forecast_target_date` 对齐的未来第 7 天病例趋势值。

缺失天气不会删掉病例行。数值特征使用训练集统计量填充，并有匹配标记告诉模型该天气是否真实存在。

## 7. PyTorch LSTM

### 7.1 工作原理

LSTM 是带门控记忆的循环神经网络。每个时间步读取一个序列值，通过遗忘门、输入门和输出门决定保留、写入和输出哪些历史信息，从而学习长期依赖。项目使用 PyTorch `torch.nn.LSTM`，官方说明：`https://docs.pytorch.org/docs/stable/generated/torch.nn.LSTM.html`。

模型结构为：

```text
历史数值序列
  -> log1p + StandardScaler
  -> LSTM
地区代码 -> Embedding ----+
  -> 拼接最后隐藏状态和地区嵌入
  -> Linear -> ReLU -> Dropout -> Linear
  -> 未来一步/第 7 天预测
```

地区 Embedding 允许同一疾病模型在多个国家间共享趋势规律，同时保留国家差异。每种疾病使用独立模型，不会让 TB 年度发病率和 COVID 日病例共享同一个 LSTM 参数文件。

### 7.2 训练实现

核心函数为 `src/models/lstm_optional.py::train_lstm_forecaster`：

1. `prepare_windows` 按疾病、地区、频率生成滑动窗口。
2. 训练前做 `log1p`，减小病例峰值的长尾影响。
3. `StandardScaler` 只在训练集拟合。
4. 损失函数为 `SmoothL1Loss`，比均方误差对极端峰值更稳健。
5. 优化器为 Adam，默认学习率 `1e-3`。
6. 梯度裁剪阈值 5，减少循环网络梯度爆炸。
7. 每轮计算验证集原尺度 MAE，保存最佳 checkpoint。
8. 连续若干轮验证集不改善时早停；`patience=0` 可禁用早停。
9. 训练结束后加载最佳权重，而不是最后一轮权重。
10. 输出非负预测、训练/验证/测试指标和每个预测目标日期。

### 7.3 六个疾病模型配置

| 疾病 | 模型名 | 频率 | 历史窗口 | 预测跨度 | 默认隐藏层 | 最大批次 | 最大短缺口 |
|---|---|---|---:|---:|---:|---:|---:|
| COVID-19 | `local_pytorch_lstm` | 日 | 28 日 | 7 日 | 32 | 128 | 3 日 |
| Influenza | `local_pytorch_lstm_influenza` | 周 | 12 周 | 1 周 | 16 | 32 | 2 周 |
| RSV | `local_pytorch_lstm_rsv` | 周 | 8 周 | 1 周 | 12 | 16 | 2 周 |
| COVID-19 Hospital Admissions | `local_pytorch_lstm_hospital` | 周 | 12 周 | 1 周 | 16 | 32 | 2 周 |
| Tuberculosis | `local_pytorch_lstm_tuberculosis` | 年 | 5 年 | 1 年 | 12 | 32 | 1 年 |
| HIV/AIDS | `local_pytorch_lstm_hiv` | 年 | 3 年 | 1 年 | 12 | 16 | 1 年 |

PowerShell 的 `-LstmWindow` 和 `-LstmHiddenSize` 主要控制 COVID 上限；其他疾病会使用更适合其样本量和频率的较小配置。

### 7.4 为什么周频和年频不能简单转成日频

把一个年度 TB 发病率复制成 365 个相同日值不会增加信息，只会让模型误以为有 365 个独立观测，并造成严重伪样本和过度自信。当前实现采用“原生频率 LSTM”：

- 年频窗口的一个步长是一年；
- 周频窗口的一个步长是一周；
- 只为连续计算短缺口补输入，不制造训练目标；
- 网页按真实频率说明“下一年”或“下一周”。

这是真正让周频/年频接入 LSTM，同时不篡改统计含义的方法。

## 8. 疾病间的输入差异

### 8.1 COVID-19

样本最多，使用十国日频历史、代表城市同期天气、人口和社会经济特征。可同时训练 GBDT 和 LSTM。来源中批次报告导致尖峰和大量零值，所以趋势目标使用来源平滑值/项目滚动特征，原始新增仍保留用于图表。

### 8.2 Influenza、RSV 与 COVID 住院

只有 USA 全国周频，模型重点使用自身历史序列。Open-Meteo 日数据先聚合为同周天气辅助分析；当前 LSTM 主结构使用目标历史和地区嵌入，不把日天气硬复制为周标签。RSV 样本最少，所以窗口和隐藏层更小。

### 8.3 Tuberculosis

目标是每 10 万人估计发病率，不是病例人数。Gold 可携带人口、Kaggle 辅助指标、WHO 18 个同年辅助指标和可匹配年度天气；当前 LSTM 为保证跨疾病实现一致和小样本稳定，核心输入仍是发病率历史和地区嵌入。十国 23 年只有约 230 个主观测，因此复杂 LSTM 很容易不如最近值基线。

### 8.4 HIV/AIDS

WHO 中只有 6 个项目国家形成连续可用主序列。保留 WHO 的估计上下界用于解释不确定性；LSTM 使用较短 3 年窗口和较小网络，避免在 96 行主序列上堆叠过多参数。

## 9. 模型评价

`src/models/metrics.py` 和训练编排计算：

- MAE：平均绝对误差，单位与目标相同，最容易解释；
- RMSE：均方根误差，对大误差更敏感；
- R²：相对均值基线的解释度，小样本或非平稳序列可能为负；
- MAPE：百分比误差，真实值接近 0 时不稳定；
- sMAPE：对称百分比误差，仍需结合 MAE 阅读。

模型选择主要依据时间测试集 MAE。当前实际结果中多个疾病的最近值基线优于 LSTM，这是正常且应如实报告的实验结果。可能原因包括：

- TB/HIV/RSV 样本非常少；
- 疾病序列变化缓慢，最近值本身很强；
- 来源存在批量上报和结构变化；
- LSTM 输入主要是单变量历史，参数增加不一定提升泛化；
- 训练目标是预测未来真实观测，不以训练损失最低作为最终选择。

不能只通过增大隐藏层或轮次保证 LSTM 获胜。更合理的后续实验是滚动时间验证、疾病专属外生特征、Poisson/负二项计数损失、超参数搜索和不确定性估计。

## 10. 训练接口

### 10.1 推荐的一键训练

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_local_real_pipeline.ps1 `
  -CondaEnv intership `
  -EnableLstm `
  -LstmEpochs 40 `
  -LstmPatience 5 `
  -BuildOnly
```

该命令依次清洗、生成 Gold、训练 GBDT、训练六个 LSTM、导出 Serving。终端会显示 15 个流水线阶段、每个疾病、每轮 Epoch、批次进度、loss、耗时和 ETA。

若必须完整跑满 40 轮：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_local_real_pipeline.ps1 `
  -CondaEnv intership -EnableLstm -LstmEpochs 40 -DisableLstmEarlyStopping -BuildOnly
```

早停并不是“只训练了 9 轮的 bug”，而是验证集连续 5 轮不改善后停止。完整轮数适合课程对照实验，但通常不保证测试集更好。

### 10.2 单疾病 LSTM CLI

`src/models/lstm_optional.py` 暴露参数：

- `--input`：Gold CSV；
- `--disease`、`--frequency`、`--model-name`；
- `--window`、`--horizon-steps`、`--max-imputation-gap`；
- `--epochs`、`--batch-size`、`--hidden-size`、`--learning-rate`、`--patience`；
- `--model-output`、`--predictions-output`、`--metrics-output`。

单独运行它只产生该模型文件和指定结果，不会自动重建全部网页 JSON；课程日常应优先使用一键流水线。

## 11. 模型文件和输出

模型目录：

```text
data/models/local/local_sklearn_gbdt.joblib
data/models/local/local_pytorch_lstm.pt
data/models/local/local_pytorch_lstm_influenza.pt
data/models/local/local_pytorch_lstm_rsv.pt
data/models/local/local_pytorch_lstm_tuberculosis.pt
data/models/local/local_pytorch_lstm_hiv.pt
data/models/local/local_pytorch_lstm_hospital.pt
```

Gold 预测包括总表 `data/gold/local/lstm_predictions.csv` 和疾病专属 CSV。网页最终读取：

- `data/serving/model_metrics.json`：模型级评价；
- `data/serving/model_comparison.json`：模型对比；
- `data/serving/predictions.json`：目标日期、真实值、预测值、误差；
- `data/serving/trend.json`：历史、移动平均、未来预测和区间；
- `data/serving/options.json`：每种疾病允许选择的模型。

## 12. Web 模型接口

模型相关 Flask API：

```text
GET /api/model-metrics?disease=COVID-19
GET /api/predictions?disease=COVID-19&location=CHN&model=local_pytorch_lstm
GET /api/trend?disease=COVID-19&location=CHN&model=local_pytorch_lstm&start_date=2024-01-01&end_date=2025-01-16
GET /api/model-coverage
```

统一成功响应：

```json
{"ok": true, "status": "ok", "data": {}, "error": null}
```

接口会校验疾病、地区、日期和模型是否属于 `options.json` 中该疾病的可用集合。前端刷新时同时请求趋势、预测误差和指标；ECharts 的趋势图和误差图都支持缩放及左右拖动。

## 13. Spark MLlib GBT 路线说明

`src/spark_jobs/train_gbt.py` 使用 Spark ML Pipeline/GBT 对 HDFS Gold 特征训练，输出 HDFS 模型和预测。相关串联脚本是旧的 `scripts/run_pipeline.sh`：清洗三表、构建特征、质量报告、训练 GBT、导出 Dashboard。

但较新的 Windows `remote_pipeline.py all` 当前只跑到 Silver，没有自动调用这条 Gold/GBT/Serving 链。因此当前网页看到的 GBDT 是 Windows 本地 sklearn 模型，而不是虚拟机 Spark MLlib 模型。实验报告和演示时必须明确这一点。
