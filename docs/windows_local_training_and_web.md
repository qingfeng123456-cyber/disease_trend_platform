# Windows / PyCharm 本地训练与网页接入顺序

## 1. 当前真实调用链

```text
data/raw 中的真实 CSV
  -> scripts/build_local_serving_from_raw.py
  -> data/silver/local 清洗表
  -> data/gold/local/forecast_features.csv
  -> GBDT（必跑）和 PyTorch LSTM（可选）
  -> data/models/local 模型文件
  -> data/serving/*.json
  -> src.web.app Flask API
  -> ECharts 网页
```

`src.models.run_models` 已改为真实流水线入口；只有显式添加 `--demo` 才会生成 demo。不要再把 `src/models/lstm_optional.py` 当作网页完整入口单独运行，因为网页还需要主流水线重新导出全部 serving JSON。

## 2. 先确认 PyCharm 解释器

PyCharm 打开：`File -> Settings -> Project -> Python Interpreter`。

选择：

```text
C:\Users\16355\miniconda3\envs\intership\python.exe
```

环境名称是 `intership`，不是 `inter`。PyCharm Terminal 是否显示 `(base)` 不重要，后面的 `conda run -n intership` 会强制使用正确环境。

检查命令：

```powershell
conda run --no-capture-output -n intership python -c "import sys; print(sys.executable)"
```

## 3. 首次安装 LSTM 依赖

当前基础环境不强制安装 PyTorch。需要训练 LSTM 时执行一次：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_lstm_dependencies.ps1
```

等价命令：

```powershell
conda run --no-capture-output -n intership python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
```

验证：

```powershell
conda run --no-capture-output -n intership python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

CPU 版本可以正常训练，只是速度比 CUDA 慢。不要同时安装 TensorFlow；当前项目真实 LSTM 使用 PyTorch。

## 4. 推荐的一键运行命令

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_local_real_pipeline.ps1 -EnableLstm -LstmEpochs 20
```

这个命令依次完成：

1. 检查 `intership` 和 PyTorch；
2. 清洗 OWID、Kaggle、结核病、呼吸系统、人口和天气数据；
3. 生成 Silver 与 Gold 表；
4. 训练并保存 GBDT；
5. 按疾病原生频率构造序列窗口，依次训练 6 个独立 LSTM；
6. 分疾病比较朴素值、移动平均、GBDT（仅 COVID）和对应 LSTM 的测试集 MAE；
7. 把每个疾病模型的预测导出到 serving JSON；
8. 在 5000 端口启动 Flask。

快速验证流程时可以先跑 2 轮：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_local_real_pipeline.ps1 -EnableLstm -LstmEpochs 2 -BuildOnly
```

正式结果再使用 20 至 30 轮。早停会在原始目标单位的验证集 MAE 连续 5 轮没有改善时自动结束。

## 5. 在 PyCharm 中按两个运行配置执行

### 配置 A：清洗、特征、训练、导出

新建 `Python` Run Configuration：

```text
Name: Local Train And Export
Script path: scripts\build_local_serving_from_raw.py
Parameters: --config config\settings.yaml --lstm --lstm-epochs 20
Working directory: 当前项目根目录
Python interpreter: intership
```

先运行配置 A。看到以下内容才表示发生了真实训练：

```text
[GBDT] ... 020/120 ... 120/120
[LSTM] Prepared windows=...
[LSTM] Epoch 01/20 ... train_loss=... val_loss=... val_mae=... eta=...
[LSTM] Training complete ... model=data/models/local/local_pytorch_lstm.pt
```

### 配置 B：启动网页

再新建 `Python` Run Configuration：

```text
Name: Local Flask Web
Module name: src.web.app
Working directory: 当前项目根目录
Python interpreter: intership
```

运行配置 B，浏览器访问：

```text
http://127.0.0.1:5000
```

配置 A 重新训练后，serving JSON 会更新。若修改过 Python 后端代码，应先停止配置 B，再重新启动；只更新数据时刷新浏览器即可。

## 6. 模型与网页是否真正接通

成功训练后应同时存在：

```text
data/models/local/local_sklearn_gbdt.joblib
data/models/local/local_pytorch_lstm.pt
data/gold/local/lstm_predictions.csv
data/serving/local_pytorch_lstm_metrics.json
data/serving/model_comparison.json
data/serving/trend.json
data/serving/predictions.json
```

检查网页模型选项：

```powershell
(Invoke-RestMethod 'http://127.0.0.1:5000/api/options').data.models
```

检查 LSTM 指标：

```powershell
(Invoke-RestMethod 'http://127.0.0.1:5000/api/model-metrics').data.models.local_pytorch_lstm
```

检查 LSTM 趋势预测：

```powershell
$url = 'http://127.0.0.1:5000/api/trend?location=CHN&disease=COVID-19&model=local_pytorch_lstm'
(Invoke-RestMethod $url).data.points | Select-Object -Last 5
```

只有 6 个 `.pt` 文件、逐疾病指标 JSON、API 模型选项和逐疾病趋势预测同时存在，才算 LSTM 真正完成“训练 -> 接口 -> 网页”闭环。也可以直接运行 `conda run --no-capture-output -n intership python scripts\verify_local_pipeline.py` 做全链路检查。

## 7. 重要口径

- GBDT 只训练 COVID-19 国家级日频数据；LSTM 则为每个疾病单独训练一个模型。
- COVID 输入过去 28 天并预测第 `t+7` 天；流感/新冠住院输入 12 周、RSV 输入 8 周并预测下一周；结核病输入 5 年、HIV/AIDS 输入 3 年并预测下一年。
- 每个疾病都独立按日期约 70%/15%/15% 切分训练、验证、测试，不能随机拆分时间序列。
- 仅在模型输入历史窗口中对很短的内部缺口做有限插值，预测标签必须是原始观测值；周频和年频数据不会扩成日频。
- 每种疾病仍保留朴素值和移动平均作对照，复杂模型不保证优于朴素基线。
- 网页默认展示该疾病测试 MAE 最低的可用模型。
