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

#### 7.1.1 地区 Embedding 与疾病独立参数

这句话包含两个不同层次的设计：

1. **同一种疾病内部共享模型**：多个国家或地区的该疾病序列共同训练一个疾病专属 LSTM；
2. **不同疾病之间隔离模型**：COVID-19、流感、RSV、结核病、HIV/AIDS 和新冠住院分别训练，各自保存参数文件。

因此，项目不是“每个国家各训练一个 LSTM”，也不是“所有疾病共用一个 LSTM”，而是：

```text
每种疾病一个独立模型
  + 该疾病模型内部可接收多个国家的序列
  + 地区 Embedding 告诉模型当前样本来自哪个国家
```

##### 1. 地区代码为什么需要 Embedding

神经网络不能直接把 `CHN`、`USA`、`GBR` 等字符串作为数值输入。程序先建立地区索引，例如：

```text
CHN -> 0
USA -> 1
GBR -> 2
IND -> 3
```

Embedding 层再把每个地区索引转换成一个可训练的低维向量。下面只是结构示例，不是当前模型参数的真实数值：

```text
CHN -> [ 0.32, -0.18,  0.71, 0.09]
USA -> [-0.12,  0.54,  0.21, 0.63]
GBR -> [ 0.45,  0.11, -0.35, 0.28]
```

这些向量不是人工填写的，也不分别代表温度、GDP、人口或政策。它们由训练误差反向传播自动更新，是模型为了改善预测而学习到的“地区潜在表示”。因此不能把某一个 Embedding 维度直接解释成具体社会经济因素。

##### 2. 什么叫“多个国家共享趋势规律”

以 COVID-19 为例，中国、美国、英国等国家的历史窗口都输入同一个 COVID LSTM：

```text
中国 COVID 历史序列 ─┐
美国 COVID 历史序列 ─┼─> 同一组 COVID LSTM 权重
英国 COVID 历史序列 ─┤
印度 COVID 历史序列 ─┘
```

这些国家共同更新同一组 LSTM 时序参数。LSTM 可以从全部国家样本中学习相对通用的序列形态，例如：

- 连续增长后可能放缓；
- 高峰后可能回落；
- 最近若干期通常比很久以前的观测更影响下一期；
- 移动趋势、周期波动和趋势反转的常见形态。

这种设计称为参数共享。它可以汇总同一疾病在多个国家的数据，比为每个国家单独训练一个小模型更节省参数；当某个国家样本较少时，也能从其他国家的同病种序列中学习通用时序规律。

训练一个地区样本时，梯度会同时更新：

- 该疾病共享的 LSTM 参数；
- 该疾病共享的全连接预测头；
- 当前地区对应的那一行 Embedding 参数。

其他地区的 Embedding 不会因为这一条样本直接更新，但共享 LSTM 会接收到该样本提供的时序信息。

##### 3. 什么叫“同时保留国家差异”

历史序列先经过 LSTM，得到最后隐藏状态 `h(T)`；地区代码经过 Embedding，得到地区向量 `e_location`。两者拼接后再进入预测头：

```text
历史序列 -> LSTM -> h(T) ----------------┐
                                          ├-> 拼接 -> Linear -> 预测
地区代码 -> Embedding -> e_location ------┘
```

即使两个国家最近一段时间的曲线形状相近，LSTM 隐藏状态也相近，它们仍会因为地区向量不同而得到不同预测：

```text
中国预测输入 = [共同趋势信息 h(T), 中国地区向量]
美国预测输入 = [共同趋势信息 h(T), 美国地区向量]
```

Embedding 可能隐式吸收长期稳定的地区差异，例如整体数量级、报告习惯或长期波动特点。但这只是模型内部为降低预测误差形成的统计表示，不能据此断言差异一定由人口、气候、医疗能力或政策造成。

当前结构是在 LSTM 输出之后拼接地区向量。因此更准确的表述是：

- LSTM 是多个地区共享的时序规律提取器；
- 地区 Embedding 在预测头中调整同一时序表示对应的最终输出；
- Embedding 不会让共享 LSTM 本身变成完全不同的国家专属 LSTM。

对于只有 USA 一个地区的 Influenza、RSV 和 COVID-19 Hospital Admissions，Embedding 仍保留在统一网络结构中，但不存在多个国家之间的 Embedding 对比，其跨地区共享作用有限。

##### 4. 为什么不同疾病不能共享同一个 LSTM

COVID-19 和 Tuberculosis 的统计结构并不相同：

| 项目 | COVID-19 | Tuberculosis |
|---|---|---|
| 时间频率 | 日频 | 年频 |
| 预测目标 | 日新增病例趋势 | 每 10 万人年度估计发病率 |
| 预测跨度 | 未来第 7 天 | 下一年 |
| 默认历史窗口 | 28 个日观测 | 5 个年观测 |
| 数值单位 | 病例数 | 每 10 万人发病率 |
| 典型变化 | 日级波动、疫情高峰和集中报告 | 年度缓慢变化 |

如果强行共享一个 LSTM，模型会把“相邻一天”和“相邻一年”视为同一种时间步，还会混淆病例人数与每 10 万人发病率，训练目标在统计上没有统一含义。因此项目按疾病分别建立窗口、缩放器、网络参数、验证过程和输出文件。

##### 5. 六种疾病对应的独立参数文件

```text
COVID-19
  -> data/models/local/local_pytorch_lstm.pt

Influenza
  -> data/models/local/local_pytorch_lstm_influenza.pt

RSV
  -> data/models/local/local_pytorch_lstm_rsv.pt

Tuberculosis
  -> data/models/local/local_pytorch_lstm_tuberculosis.pt

HIV/AIDS
  -> data/models/local/local_pytorch_lstm_hiv.pt

COVID-19 Hospital Admissions
  -> data/models/local/local_pytorch_lstm_hospital.pt
```

“独立参数文件”意味着各疾病分别拥有自己的：

- LSTM 权重；
- 地区 Embedding 参数；
- 全连接预测头参数；
- 目标值缩放器；
- 地区索引映射；
- 窗口长度和预测跨度；
- 训练、验证和测试指标。

所以这套设计可以概括为：

> 地区 Embedding 解决“同一种疾病在不同国家可能表现不同”的问题；疾病独立模型解决“不同疾病的频率、单位、目标和变化规律根本不同”的问题。

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

本项目不是只计算 MAE，而是采用“一个主要指标 + 四个辅助指标”的评价方式：

- **主要选择指标是时间测试集 MAE**。它与当前疾病预测目标单位一致、容易解释，并且不像 RMSE 那样过度放大少数批量上报尖峰。`best_model` 按同一疾病各模型的 MAE 最小值确定；
- **RMSE 是大误差诊断指标**。当 RMSE 明显高于 MAE 时，说明测试集中可能存在少量预测偏差很大的时点；
- **R² 是拟合优度辅助指标**。越接近 1 越好，0 表示没有优于均值基线，负值表示比均值基线更差。小样本、非平稳序列或极端异常预测可能产生很大的负数；
- **MAPE 和 sMAPE 是相对误差辅助指标**。Serving JSON 保存的是比例值，浏览器乘以 100 后显示百分比。病例为 0 或接近 0 时，MAPE 会非常不稳定，所以不能单独用它选择模型；
- **不同疾病之间不直接比较 MAE/RMSE**。例如 COVID 的目标是病例数，而 TB 的目标是每 10 万人估计发病率，两者单位和数量级不同。

网页顶部“最佳模型”卡片只突出展示主要选择指标 MAE。下方“模型五项测试指标”热力矩阵同时展示 MAE、RMSE、R²、MAPE 和 sMAPE：

- 横轴是当前疾病可用的最近值、移动平均、GBDT、LSTM 等模型；
- 纵轴是五项评价指标，每个单元格直接显示测试集真实数值；
- MAPE 和 sMAPE 在浏览器中转换为百分比显示；
- 单元格由红到绿仅表示**同一指标行内**各模型的相对排名，不代表跨疾病的绝对等级；
- 鼠标悬停单元格会显示指标定义和“越高/越低越好”的判断方向；
- 极端负 R² 或超大 MAPE 不再与 MAE/RMSE 共用数值坐标轴，因此不会把其他模型的正常数值压缩到无法辨认。

完整指标由 `src/models/metrics.py` 计算，经训练编排写入 `data/serving/model_metrics.json` 和 `data/serving/model_comparison.json`，由 `GET /api/model-metrics?disease=疾病名` 返回。前端 `src/web/static/js/app.js` 请求接口，`src/web/static/js/charts.js` 的 `modelOption()` 生成五项指标热力矩阵。

当前实际结果中多个疾病的最近值基线优于 LSTM，这是正常且应如实报告的实验结果。可能原因包括：

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

## 14. 温湿度与日新增病例关联

网页中的说明为：

> r 为皮尔逊线性相关系数，n 为匹配样本数；相关不代表因果。

该模块不是预测模型，也不负责证明天气导致病例变化。它是探索性统计分析模块，用于观察同一地区、同一日期或同一统计周期内，温度、相对湿度与疾病指标是否呈现线性同步变化。

### 14.1 完整数据流

```text
data/raw/open_meteo/<ISO3>/open_meteo_<ISO3>_<YEAR>.csv
  -> clean_weather
  -> data/silver/local/weather_daily_clean.csv
  -> aggregate_weather + build_features

Silver 疾病观测
  -> 按 location_code + date/统计周期关联天气
  -> data/gold/local/forecast_features.csv
  -> 筛选 has_weather = true 的完整匹配行
  -> data/serving/weather_correlation.json
  -> DataService.weather_correlation
  -> 计算温度 r、湿度 r 和样本数 n
  -> GET /api/weather-correlation
  -> app.js -> charts.js 的 weatherOption
  -> ECharts 温湿度与疾病指标散点图
```

### 14.2 天气数据来源与清洗

天气由 `src/collectors/open_meteo_collector.py` 从 Open-Meteo Archive API 下载，命令入口是 `scripts/download_weather_data.py`。原始文件放在：

```text
data/raw/open_meteo/<ISO3>/open_meteo_<ISO3>_<YEAR>.csv
```

主要字段包括：

- `date`：天气观测日期；
- `location_code`：ISO3 国家代码；
- `temperature_mean`：日平均温度，单位为摄氏度；
- `temperature_max`、`temperature_min`：日最高、最低温度；
- `relative_humidity_mean`：日平均相对湿度，单位为百分比；
- `precipitation_sum`：日累计降水量，单位为毫米；
- `wind_speed_max`：日最大风速。

每个国家使用配置中的一个代表城市作为国家级教学代理点，因此天气字段不能解释为整个国家所有地区的平均天气。`scripts/build_local_serving_from_raw.py` 中的 `clean_weather()` 负责日期解析、ISO3 标准化、数值转换、关键字段缺失处理和 `location_code + date` 去重，清洗后输出：

```text
data/silver/local/weather_daily_clean.csv
```

### 14.3 天气与疾病数据如何关联

关联工作由 `scripts/build_local_serving_from_raw.py` 的 `aggregate_weather()` 和 `build_features()` 完成。不同频率使用不同聚合方式：

| 疾病数据频率 | 天气处理 | 关联键 |
|---|---|---|
| 日频 | 保留当天日频天气 | `location_code + date` |
| 周频 | 将一周日频天气求平均并映射到报告周星期六 | `location_code + week_end_date` |
| 年频 | 将全年日频天气求平均并映射到当年 12 月 31 日 | `location_code + year_end_date` |

COVID-19 日新增病例使用同一 ISO3 国家代码、同一自然日的天气。天气采用左连接，因此天气缺失不会删除疾病观测。程序同时生成：

- `has_weather`：温度和湿度是否同时存在；
- `weather_match_level`：`exact_day`、`weekly_mean_to_saturday`、`annual_mean` 或 `unmatched`；
- `weather_source`：天气来源说明。

关联后的完整模型特征输出到：

```text
data/gold/local/forecast_features.csv
```

### 14.4 r 和 n 的计算方法

计算代码位于 `src/web/services/data_service.py`：

- `DataService.weather_correlation()`：筛选有效样本并组织接口结果；
- `DataService._pearson()`：按照皮尔逊公式计算相关系数。

对每一个匹配日期 `i` 定义：

```text
T_i = temperature_mean         当期平均温度
H_i = relative_humidity_mean   当期平均相对湿度
C_i = new_cases_smoothed       当期平滑后的疾病指标
```

温度与疾病指标的皮尔逊相关系数为：

```text
                  Σ((T_i - T̄)(C_i - C̄))
r_temperature = -----------------------------
                 √[Σ(T_i - T̄)² Σ(C_i - C̄)²]
```

湿度相关系数将公式中的 `T` 替换为 `H`。其中：

- `r` 的范围为 `-1` 到 `1`；
- `r > 0` 表示总体同向线性变化，`r < 0` 表示总体反向线性变化；
- `r` 接近 0 表示没有明显线性关系，不代表不存在非线性关系；
- `n` 是同时具有有限温度、湿度和 `new_cases_smoothed` 的匹配记录数；
- 少于 3 个有效样本时返回 `null`；
- 任一变量没有变化、导致公式分母为 0 时也返回 `null`；
- 最终 `r` 保留 4 位小数。

这里使用 `new_cases_smoothed` 而不是未经平滑的单日原始值。COVID-19 对应来源提供或流水线生成的 7 日平滑病例，其他疾病按照各自原生频率生成移动平均指标。

### 14.5 文件与 Serving 数据

| 数据层 | 文件 | 作用 |
|---|---|---|
| Raw | `data/raw/open_meteo/<ISO3>/*.csv` | Open-Meteo 原始日频天气 |
| Silver | `data/silver/local/weather_daily_clean.csv` | 日期、ISO3、数值类型和重复记录清洗后的天气表 |
| Gold | `data/gold/local/forecast_features.csv` | 疾病、天气、人口和时序特征的关联结果 |
| Serving | `data/serving/weather_correlation.json` | 网页相关分析所需的匹配样本 |

`weather_correlation.json` 保存每一个可匹配观测点，而不是只保存一个预先计算好的 `r`，主要字段为：

```text
date
location_code
location
disease
frequency
metric
metric_label
temperature_mean
relative_humidity_mean
precipitation_sum
new_cases_smoothed
weather_match_level
weather_source
```

这样 Flask 可以根据网页当前选择的疾病、地区和日期范围重新计算 `r` 与 `n`，而不是展示写死的全局相关系数。

### 14.6 Flask API 接入

Flask 路由定义在 `src/web/app.py`：

```text
GET /api/weather-correlation
```

请求示例：

```text
GET /api/weather-correlation?location=CHN&disease=COVID-19&start_date=2020-01-22&end_date=2021-05-29
```

处理过程为：

1. `DataService` 读取 `data/serving/weather_correlation.json`；
2. 按地区、疾病和日期范围过滤；
3. 仅保留温度、湿度和疾病指标均为有限数值的记录；
4. 用 `_pearson()` 分别计算温度和湿度相关系数；
5. 返回 `sample_size`、相关系数、匹配日期范围和绘图点；
6. 接口最多向图表返回最后 1,200 个点，但 `r` 与 `n` 使用过滤后的全部有效样本计算。

如果用户选择的日期范围没有同期天气，但该疾病和地区在其他日期存在天气，后端会回退到该序列全部可匹配天气期，并返回 `fallback_used: true` 和实际 `matched_date_range`，网页会明确显示回退提示。

### 14.7 前端动态渲染

`src/web/static/js/app.js` 的 `loadWeatherCorrelation()` 使用当前疾病、地区和日期调用 `/api/weather-correlation`。`setCharts()` 将结果传给 `src/web/static/js/charts.js` 的 `weatherOption()`，并根据是否发生日期回退更新面板说明。

`weatherOption()` 将每一条匹配记录转换为：

```text
[temperature_mean, new_cases_smoothed, relative_humidity_mean]
```

图表编码规则为：

- X 轴：平均温度；
- Y 轴：平滑后的当前疾病指标；
- 散点颜色：相对湿度，暖色偏干、蓝色偏湿；
- 散点大小：按照疾病指标相对大小进行平方根缩放；
- 标题：显示温度 `r`、湿度 `r` 和样本数 `n`；
- Tooltip：显示地区、日期、温度、湿度和疾病指标值。

网页调用关系为：

```text
refreshDashboard
  -> loadWeatherCorrelation
  -> GET /api/weather-correlation
  -> DataService.weather_correlation
  -> _pearson
  -> JSON API 响应
  -> setCharts
  -> weatherOption
  -> charts.weatherChart.setOption
```

### 14.8 为什么相关不代表因果

该图只能说明样本中的同期线性关系，不能得出“温度或湿度导致病例升高或降低”的结论，原因包括：

- 每个国家只使用一个代表城市的天气，不能代表全国所有地区；
- 病例按报告日期统计，可能存在延迟、集中补报和回溯修订；
- 天气和传染病都可能具有季节性，自相关会放大普通 Pearson `r`；
- 当前计算的是同期相关，没有检验 7 日、14 日等滞后效应；
- 没有控制检测能力、政策、人口流动、疫苗接种和病毒变异等混杂因素；
- Pearson 只衡量线性关系，且容易受到极端峰值影响；
- 使用平滑病例会降低短期噪声，但相邻样本不再完全独立。

答辩时应表述为：“该模块用于探索同期温湿度与疾病指标的线性关联，为后续外生特征研究提供线索”，不能表述为“已经证明天气变化造成病例变化”。
