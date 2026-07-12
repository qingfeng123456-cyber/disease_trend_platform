# 基于机器学习的传染病趋势预测与可视化分析平台

这是一个适合课程实训和答辩演示的完整工程。项目把公开数据采集、HDFS 分层、Spark 清洗与特征工程、机器学习预测、Flask API 和 ECharts 可视化大屏串成一条可运行链路。

本项目支持两种模式：

- `demo`：固定随机种子生成演示数据，不需要网络、Hadoop 或 Spark，适合先跑通网页。
- `real`：采集公开数据，上传 HDFS，用 Spark 生成 silver/gold/serving 层结果。

> 数据真实性声明：演示数据只用于课程展示，不代表真实疫情。风险指数是课程项目分析指标，不等同于公共卫生部门正式风险等级，不能用于医疗决策。

## 1. 系统架构

```text
公开数据源
  -> Python 采集器
  -> data/raw 与 HDFS raw
  -> Spark 清洗标准化
  -> silver Parquet
  -> Spark 关联与特征工程
  -> gold Parquet
  -> 模型训练与预测
  -> data/serving/*.json
  -> Flask API
  -> ECharts 大屏
```

Flask 请求期间不会启动 Spark。Spark 离线生成小型 JSON，Flask 只读取 `data/serving`。

## 2. 技术栈

- Python 3.10+，Flask，pytest
- Hadoop HDFS
- Spark / PySpark DataFrame / Spark ML
- ECharts 5
- 可选：statsmodels ARIMA、PyTorch LSTM、Hive 外部表

## 3. 目录结构

```text
config/                 settings.yaml、locations.csv、日志配置
data/raw/               原始数据
data/silver/            本地 silver 备用目录
data/gold/              本地 gold 备用目录
data/serving/           Flask 读取的 JSON
scripts/                环境检查、HDFS、Spark、Web 脚本
src/common/             配置、路径、日志、HTTP、清洗工具
src/collectors/         OWID、Open-Meteo、World Bank、WHO、中国疾控、demo 数据
src/spark_jobs/         清洗、特征工程、GBT、导出大屏
src/models/             朴素基线、ARIMA、可选 LSTM、指标
src/web/                Flask API 与 ECharts 页面
hive/schema.sql         Hive 外部表示例
tests/                  不依赖 Hadoop 的单元测试
docs/                   架构、API、数据字典、部署、分工、答辩文档
```

## 4. Windows、Xshell、Ubuntu、PyCharm 的关系

- Windows：写代码、看浏览器大屏、用 PyCharm 管理项目。
- PyCharm：可以配置 SFTP 自动上传，也可以只本地写代码。
- Xshell：连接 Ubuntu 服务器，运行 Hadoop、Spark 和 Flask。
- Ubuntu：真正运行 HDFS、Spark、采集器和 Web 服务的地方。

推荐流程：Windows/PyCharm 修改代码，Git 推送或 SFTP 上传到 Ubuntu，然后在 Xshell 中执行脚本。

## 5. 上传代码到服务器

方式 A：Git。

```bash
git clone <你的仓库地址>
cd disease_trend_platform
git pull
```

方式 B：PyCharm SFTP Deployment。把整个项目目录上传到 Ubuntu，例如：

```bash
cd ~/projects/disease_trend_platform
```

不要用压缩包反复覆盖整个目录，容易丢掉数据和配置。

## 6. 环境检查

在 Ubuntu 项目目录运行：

```bash
bash scripts/check_environment.sh
```

也可以手动检查：

```bash
pwd
find . -maxdepth 3 -type f | sort
python3 --version
java -version
hadoop version
spark-submit --version
git status
```

如果某个命令不存在，脚本会如实提示。没有 Hadoop/Spark 时仍可运行 demo 模式。

## 7. 安装 Python 依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

国内网络慢时可换镜像：

```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

PySpark 建议与服务器 `spark-submit --version` 一致，必要时单独安装对应版本。

## 8. Demo 模式运行

```bash
python -m src.collectors.generate_demo_data
python -m src.models.run_models --demo
python -m src.web.app
```

浏览器访问：

```text
http://服务器IP:5000
```

云服务器没有开放 5000 端口时，在 Windows 本机开 SSH 隧道：

```bash
ssh -L 5000:127.0.0.1:5000 用户名@服务器IP
```

然后访问：

```text
http://127.0.0.1:5000
```

一键 demo：

```bash
bash scripts/run_all.sh --demo
bash scripts/start_web.sh
```

## 9. 采集真实数据

```bash
python -m src.collectors.run_all --sources owid world_bank open_meteo who china_cdc
```

说明：

- OWID 保存国家-日期级疫情 CSV 和字段报告。
- Open-Meteo 按 `config/locations.csv` 的地区、按年份分批请求。
- World Bank 采集人口、城市化率、人均 GDP。
- WHO 采集器支持分页，默认未配置指标，可用 `--indicators` 指定。
- 中国疾控只归档公开页面和附件，不绕过登录、验证码或访问限制。

网络不可用时不要声称真实采集成功，先运行 demo 模式。

## 10. HDFS 分层

初始化目录：

```bash
bash scripts/init_hdfs.sh
```

上传 raw 数据：

```bash
bash scripts/upload_raw_to_hdfs.sh
```

HDFS 目录：

```text
/disease_platform/raw
/disease_platform/silver
/disease_platform/gold
/disease_platform/serving
/disease_platform/checkpoints
```

脚本重复运行不会因为目录已存在而失败。没有 `hdfs` 命令时会提示并保持本地模式。

## 11. Spark 流水线

```bash
bash scripts/run_spark_pipeline.sh
```

等价于依次运行：

```bash
spark-submit src/spark_jobs/clean_epidemic.py --input "/disease_platform/raw/owid/*.csv" --output "/disease_platform/silver/epidemic_daily"
spark-submit src/spark_jobs/clean_weather.py --input "/disease_platform/raw/open_meteo/*.csv" --output "/disease_platform/silver/weather_daily"
spark-submit src/spark_jobs/clean_population.py --input "/disease_platform/raw/world_bank/*.csv" --output "/disease_platform/silver/population_yearly"
spark-submit src/spark_jobs/build_features.py --epidemic "/disease_platform/silver/epidemic_daily" --weather "/disease_platform/silver/weather_daily" --population "/disease_platform/silver/population_yearly" --output "/disease_platform/gold/forecast_features" --horizon 7
spark-submit src/spark_jobs/train_gbt.py --input "/disease_platform/gold/forecast_features" --model-output "/disease_platform/models/gbt_t_plus_7" --prediction-output "/disease_platform/gold/predictions"
spark-submit src/spark_jobs/export_dashboard.py --features "/disease_platform/gold/forecast_features" --predictions "/disease_platform/gold/predictions" --serving-dir data/serving
```

没有 Spark 时先用 demo 模式，代码中仍保留真实 Spark 实现。

## 12. 模型训练

### Windows 本地真实数据（推荐）

不训练 LSTM，运行清洗、特征、GBDT、serving 和网页：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_local_real_pipeline.ps1
```

首次使用 LSTM 时，先安装可选 PyTorch CPU 依赖：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_lstm_dependencies.ps1
```

然后运行真实数据 LSTM，并在终端显示 epoch/batch 进度：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_local_real_pipeline.ps1 -EnableLstm -LstmEpochs 20
```

`LstmEpochs` 是最大轮次。默认按还原到原始单位后的验证集 MAE 判断，连续 5 轮不改善就早停；要强制跑满 40 轮：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_local_real_pipeline.ps1 -EnableLstm -LstmEpochs 40 -DisableLstmEarlyStopping
```

也可用 `-LstmPatience 10` 调整早停耐心值。流水线会为 6 种疾病分别训练独立 LSTM：COVID-19 使用日频窗口并预测 `new_cases_smoothed`，流感、RSV 和新冠住院使用周频原始观测值，结核病和 HIV/AIDS 使用年频原始观测值。各模型拥有独立的时间切分、标准化器、权重文件和测试指标，不会把周频或年频记录伪造扩展成日频，也不会混合不同疾病的目标单位。训练日志同时显示变换空间的 `val_loss` 和原始单位的 `val_mae`；最佳权重及早停由后者决定。真实覆盖可查看 `data/serving/model_data_coverage.json` 或 `GET /api/model-coverage`。

同一流程也可以直接用 Python 运行：

```powershell
conda run --no-capture-output -n intership python scripts\build_local_serving_from_raw.py --lstm --lstm-epochs 20
conda run --no-capture-output -n intership python -m src.web.app
```

真实 LSTM 读取 `data/gold/local/forecast_features.csv`，模型分别保存到
`data/models/local/local_pytorch_lstm*.pt`，预测会进入 Flask 的
`trend.json`、`predictions.json`、`model_metrics.json` 和 `model_comparison.json`。
网页切换疾病时只显示该疾病可用的模型；没有成功训练时不会伪造 LSTM 选项。

本地朴素基线：

```bash
python -m src.models.run_models --demo
```

Spark GBT：

```bash
bash scripts/run_spark_pipeline.sh
```

ARIMA 示例：

```bash
python -m src.models.arima_baseline --input data/demo/epidemic_daily_demo.csv --output data/serving/arima_result.json
```

LSTM 是可选项，不是唯一模型。使用 `--lstm` 但未安装 PyTorch 时会立即报错并给出安装命令，不会静默跳过。Windows/PyCharm 完整顺序见 `docs/windows_local_training_and_web.md`。

## 13. Flask API

启动：

```bash
bash scripts/start_web.sh
```

接口：

```text
GET /api/health
GET /api/overview
GET /api/trend?location=CHN&disease=COVID-19&model=demo_trend_model
GET /api/risk-map
GET /api/rankings
GET /api/model-metrics
GET /api/data-quality
GET /api/options
GET /api/model-coverage
```

所有接口统一返回：

```json
{"ok": true, "status": "ok", "data": {}, "error": null}
```

## 14. ECharts 大屏

首页包含：

- 实际病例与预测趋势；
- 7 日移动平均；
- 风险地图；
- 高风险地区排行榜；
- 温湿度与病例关联；
- 模型指标对比；
- 数据质量仪表盘；
- 增长率；
- 疾病占比；
- 预测误差；
- 数据源状态。

页面使用 ECharts CDN。网络断开时基础 HTML 仍可打开，但图表库需要联网或把 ECharts 下载到 `src/web/static/vendor` 后修改模板引用。

## 15. 测试和语法检查

```bash
python -m compileall src tests
pytest -q
python scripts/verify_local_pipeline.py
```

这些测试不依赖 Hadoop 集群。

## 16. Hive

```bash
hive -f hive/schema.sql
```

Hive 不是网页实时查询来源，只用于展示 Hadoop 生态协同能力。

## 17. 常见错误

- `python3: command not found`：Windows 上可能只有 `python`，Ubuntu 建议安装 `python3`。
- `hdfs: command not found`：Hadoop 环境变量未配置，先检查 `HADOOP_HOME` 和 PATH。
- `spark-submit: command not found`：Spark 未安装或 PATH 未配置。
- `ModuleNotFoundError`：没有激活虚拟环境或依赖未安装。
- PyPI 下载失败：换国内镜像，或先用 demo 模式验证项目。
- 页面显示接口异常：先运行 `python -m src.collectors.generate_demo_data` 生成 serving JSON。

## 18. 答辩演示顺序

1. 展示项目架构图和目录结构。
2. 运行环境检查脚本。
3. 展示 `data/raw` 和 HDFS raw 目录。
4. 展示 Spark 作业和 silver/gold Parquet。
5. 展示特征工程字段和 `lead(target, 7)` 防泄漏设计。
6. 展示朴素基线与 GBT/ARIMA 对比。
7. 展示 Flask API。
8. 展示 ECharts 大屏筛选和风险排名。
9. 强调演示数据和风险指标免责声明。

## 19. 五人分工

详见 [docs/team_tasks.md](docs/team_tasks.md)。核心原则是每个人负责一段链路，但所有输出必须接入同一套 `data/serving` 和 Flask API，避免五套代码互不兼容。
