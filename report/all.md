# 实验报告（七）：完整数据流、项目结构与脚本说明

## 1. 项目总体目标

本项目将公开传染病、天气、人口和社会经济数据组织成可重复运行的数据工程流程，完成多疾病趋势分析、基线/机器学习/LSTM 预测、Flask API 和 ECharts 可视化。项目同时支持：

- Windows 本地 Pandas + sklearn + PyTorch 完整演示；
- Ubuntu HDFS + Spark Silver 教学流程；
- Demo 固定种子备用流程。

三者用途不同，当前最完整的六疾病网页由 Windows 本地真实数据流水线生成。

## 2. 完整数据流向

```text
公开来源/Kaggle 手动文件
  |
  v
data/raw
  |  不覆盖原文件，保留采集元数据
  v
清洗与规范化
  |-- Windows: scripts/build_local_serving_from_raw.py + Pandas
  |-- Ubuntu:  src/spark_jobs/clean_*.py + Spark
  v
Silver
  |-- data/silver/local/*.csv
  `-- hdfs:///disease_platform/silver/*/*.parquet
  |
  v
Gold 特征
  |-- 疾病原生频率、滞后、滚动、天气、人口、目标日期
  `-- data/gold/local/forecast_features.csv
  |
  +--> 最近值基线
  +--> 移动平均基线
  +--> sklearn HistGradientBoosting（COVID）
  `--> 六个 PyTorch LSTM
  |
  v
data/models/local + data/gold/local/*predictions.csv
  |
  v
data/serving/*.json
  |
  v
src/web/app.py -> DataService -> /api/*
  |
  v
index.html + app.js + charts.js -> ECharts Dashboard
```

关键边界：Flask 只读 Serving；模型只读 Gold；清洗只读 Raw。只启动网页不会自动清洗和训练。

## 3. 根目录结构

```text
disease_trend_platform/
├─ config/                 本地、远程、国家、地点、日志配置
├─ data/
│  ├─ raw/                 原始数据
│  ├─ silver/local/        本地规范清洗表
│  ├─ gold/local/          特征和预测明细
│  ├─ models/local/        joblib/PT 模型
│  ├─ serving/             Flask JSON 与运行报告
│  └─ demo/                示例数据
├─ docs/                   开发过程中的专题文档
├─ report/                 本次七份实验报告
├─ hive/schema.sql         Hive 表结构草案
├─ scripts/                PowerShell、Bash、Python 运行工具
├─ src/
│  ├─ collectors/          采集器
│  ├─ common/              配置、日志、HTTP、HDFS 和清洗公共函数
│  ├─ models/              LSTM、指标和旧基线
│  ├─ remote/              SSH/SFTP/远程环境控制
│  ├─ spark_jobs/          Spark Silver/Gold/ML 作业
│  └─ web/                 Flask、模板、CSS、JavaScript
├─ tests/                  单元与接口测试
├─ requirements*.txt       不同运行环境依赖
├─ README.md               项目入口说明
└─ pytest.ini              测试配置
```

## 4. `config/` 配置文件

| 文件 | 作用 |
|---|---|
| `settings.yaml` | 本地路径、HDFS 路径、十国、数据 URL、Spark、模型和 Flask 参数 |
| `remote_cluster.example.yaml` | Windows 控制 Ubuntu 的无密钥示例模板 |
| `remote_cluster.yaml` | 用户本地真实远程配置，不应提交 Git |
| `country_name_mapping.csv` | 不同来源国家名到 ISO3 映射 |
| `locations.csv` | 地区目录 |
| `weather_locations.csv` | 十国代表城市、经纬度 |
| `disease_aliases.json` | 疾病别名规范化 |
| `logging.yaml` | 日志格式和级别 |

`.env.example` 只列出 `REMOTE_PASSWORD` 和 `REMOTE_KEY_PASSPHRASE` 变量名。复制成 `.env` 后填写，永远不要提交真实密码。

## 5. `src/collectors/` 数据采集层

| 文件 | 作用 |
|---|---|
| `base_collector.py` | 采集器基类、目录和元数据约定 |
| `owid_collector.py` | 下载 OWID compact COVID CSV |
| `open_meteo_collector.py` | 按国家代表城市、年份采集历史天气并保存 meta |
| `world_bank_collector.py` | 获取人口、城市化、人均 GDP |
| `who_collector.py` | WHO GHO 分页采集、主题/指标保存 |
| `china_cdc_collector.py` | 中国疾控公开页面、附件和元数据采集 |
| `run_all.py` | 组合采集入口 |
| `generate_demo_data.py` | 固定随机种子 Demo 数据 |
| `owid_covid.py`、`open_meteo.py`、`world_bank.py`、`china_cdc.py` | 早期/兼容采集模块 |

采集器负责保存 Raw，不负责直接训练模型。

## 6. `src/common/` 公共层

| 文件 | 作用 |
|---|---|
| `config.py` | YAML 读取、嵌套配置访问 |
| `paths.py` | 项目根目录和跨平台路径 |
| `logger.py` | 日志初始化 |
| `exceptions.py` | 平台异常类型 |
| `http_client.py`、`http.py` | HTTP 重试和下载 |
| `hdfs_cli.py` | 对 `hdfs dfs` 命令的安全封装 |
| `cleaning.py` | 通用清洗函数 |
| `time_series_covid_19_*.py` | 早期 COVID 时间序列处理兼容代码 |

## 7. `src/spark_jobs/` Spark 层

| 文件 | 作用 | 当前远程 all 是否调用 |
|---|---|---|
| `clean_epidemic.py` | 疫情 Silver | 是 |
| `clean_population.py` | 人口 Silver | 是 |
| `clean_weather.py` | 天气 Silver | 是 |
| `data_quality_report.py` | Silver/Gold 质量报告 | 是 |
| `schemas.py` | 显式 Spark Schema | 间接使用 |
| `spark_session.py` | SparkSession 构建 | 间接使用 |
| `build_features.py` | HDFS Silver 到 Gold 特征 | 当前新远程 all 未调用 |
| `aggregate_statistics.py` | 聚合统计 | 当前新远程 all 未调用 |
| `train_gbt.py` | Spark MLlib GBT | 当前新远程 all 未调用 |
| `export_dashboard.py` | Spark 结果导出 Serving | 当前新远程 all 未调用 |

仓库中存在文件不等于一键流程已经调用。实验演示应以实际编排脚本为准。

## 8. `src/models/` 模型层

| 文件 | 作用 |
|---|---|
| `lstm_optional.py` | 当前六疾病原生频率 PyTorch LSTM |
| `metrics.py` | MAE、RMSE、R²、MAPE、sMAPE |
| `naive_baseline.py` | 旧/独立最近值基线 |
| `arima_baseline.py` | ARIMA 实验/备用实现，不在当前主流水线模型列表 |
| `run_models.py` | Demo/旧模型编排 |

当前真实本地主编排在 `scripts/build_local_serving_from_raw.py`，最近值、移动平均和 sklearn GBDT 都由它组织。

## 9. `src/remote/` 远程控制层

| 文件 | 作用 |
|---|---|
| `config.py` | 读取远程 YAML 和 `.env`，隐藏密钥 |
| `ssh_client.py` | Paramiko SSH 命令和 SFTP |
| `project_sync.py` | 比较大小/时间或校验和，同步项目 |
| `remote_environment.py` | 拼接 Conda、Java、Hadoop、Spark 环境命令 |
| `cluster_manager.py` | 检查/启动 HDFS 和可选 YARN |
| `webhdfs_client.py` | 可选 WebHDFS REST 客户端，默认不启用 |

## 10. `src/web/` Web 层

- `app.py`：Flask 路由和统一异常响应；
- `services/data_service.py`：Serving 缓存、校验和过滤；
- `templates/index.html`：页面容器；
- `static/css/style.css`：自定义暗色 Dashboard；
- `static/js/api.js`：HTTP；
- `static/js/app.js`：状态和并行请求；
- `static/js/charts.js`：ECharts；
- `static/js/particles.js`：历史命名文件，当前不承担粒子特效。

## 11. `.ps1` 是什么

`.ps1` 是 Microsoft PowerShell 脚本文件，相当于 Windows 下的自动化命令清单。它可以定义参数、检查退出码、调用 Conda/Python，并在某一步失败时停止。

运行通用形式：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\脚本名.ps1 -参数名 参数值
```

`-ExecutionPolicy Bypass` 只对这一次新启动的 PowerShell 进程绕过脚本策略，不会永久修改系统策略。项目目前只有两个 `.ps1`。

## 12. `install_lstm_dependencies.ps1`

路径：`scripts/install_lstm_dependencies.ps1`。

作用：

1. 接收 `-CondaEnv`，默认 `intership`；
2. 使用 PyTorch 官方 CPU wheel 源安装 `torch`；
3. 检查 pip 退出码；
4. 导入 PyTorch并打印版本和 CUDA 是否可用。

运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_lstm_dependencies.ps1 -CondaEnv intership
```

它只安装 LSTM 依赖，不清洗数据、不训练模型、不启动网页。

## 13. `run_local_real_pipeline.ps1`

路径：`scripts/run_local_real_pipeline.ps1`，当前 Windows 完整主入口。

参数：

| 参数 | 默认 | 含义 |
|---|---:|---|
| `-CondaEnv` | `intership` | Conda 环境名 |
| `-Config` | `config\settings.yaml` | 项目配置 |
| `-EnableLstm` | 关闭 | 是否训练 6 个 LSTM |
| `-LstmEpochs` | 20 | 最大 Epoch |
| `-LstmWindow` | 28 | COVID 历史窗口上限 |
| `-LstmBatchSize` | 128 | 批次上限 |
| `-LstmHiddenSize` | 32 | 隐藏层上限 |
| `-LstmPatience` | 5 | 验证集不改善早停耐心 |
| `-DisableLstmEarlyStopping` | 关闭 | 设定后强制跑满 Epoch |
| `-LstmNoBatchProgress` | 关闭 | 关闭批次进度条 |
| `-BuildOnly` | 关闭 | 只构建数据/模型，不启动 Flask |

内部步骤：

1. 用 `conda run` 验证环境 Python；
2. 若启用 LSTM，检查 PyTorch；
3. 调用 `scripts/build_local_serving_from_raw.py`；
4. 将 LSTM 参数传给 Python；
5. 检查退出码；
6. `BuildOnly` 时退出；
7. 否则检查 5000 端口，未占用时启动 Flask。

推荐完整构建：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_local_real_pipeline.ps1 `
  -CondaEnv intership -EnableLstm -LstmEpochs 40 -BuildOnly
```

然后单独启动网页：

```powershell
conda run --no-capture-output -n intership python -m src.web.app
```

分开运行便于看清构建结束状态，也避免训练完成后终端立即被 Flask 长期占用。

## 14. 所有 Bash `.sh` 脚本

`.sh` 是 Bash 脚本，主要在 Ubuntu/Xshell 中运行，不应直接在普通 Windows PowerShell 执行。

| 脚本 | 作用 | 备注 |
|---|---|---|
| `check_environment.sh` | 检查 Python、Java、Hadoop、Spark、Git | 诊断工具 |
| `init_hdfs.sh` | 创建 `/disease_platform` 分层目录 | 不会 format NameNode |
| `start_bigdata_services.sh` | 启动 HDFS，可选 YARN | `--with-yarn` |
| `stop_bigdata_services.sh` | 停止 HDFS，可选 YARN | 不删除数据 |
| `upload_raw_to_hdfs.sh` | 早期 glob 上传 OWID/World Bank/Open-Meteo/WHO 等 | 较粗粒度；新流程优先 Python 上传器 |
| `run_pipeline.sh` | 旧 Spark 清洗、Gold、GBT、Serving 全链 | 与当前新远程路径未完全统一 |
| `run_spark_pipeline.sh` | `run_pipeline.sh` 的别名包装 | 旧入口 |
| `run_collectors.sh` | 调用 `src.collectors.run_all` | 实际联网采集 |
| `run_models.sh` | 调用旧 `src.models.run_models` | Demo/旧入口 |
| `run_all.sh` | `--demo` 或早期 `--real` 总编排 | 不等于当前 Windows 六疾病主入口 |
| `start_web.sh` | Linux 启动 Flask，支持环境变量 | 当前可用 |
| `stop_web.sh` | 用 `lsof` 停止指定端口 Flask | Linux 可用 |

## 15. 所有主要 Python 工具脚本

| 脚本 | 作用 |
|---|---|
| `build_local_serving_from_raw.py` | 本地多源清洗、Gold、模型、Serving 总编排 |
| `download_weather_data.py` | 补采 Open-Meteo 指定日期天气 |
| `inspect_kaggle_dataset.py` | 本地 Kaggle 文件结构快速检查 |
| `profile_raw_kaggle_data.py` | CSV 全量/分块画像并输出报告 |
| `validate_dataset_overlap.py` | 疫情、天气、人口日期和地区重叠验证 |
| `verify_local_pipeline.py` | 检查本地模型/Serving 契约和输出完整性 |
| `check_bigdata_environment.py` | Java/Hadoop/Spark/HDFS 环境报告 |
| `upload_raw_to_hdfs.py` | 新 HDFS 上传器、清单、校验 |
| `run_silver_pipeline.py` | Spark Silver 作业编排 |
| `remote_pipeline.py` | Windows SSH/SFTP 远程总控制 |
| `open_cluster_webui.py` | 检查/打开 HDFS、YARN、Spark UI，提示隧道 |

## 16. 依赖文件

| 文件 | 安装位置 | 内容 |
|---|---|---|
| `requirements.txt` | Windows 完整本地环境 | Pandas、Flask、sklearn、pyarrow 等，不含必装 torch |
| `requirements-lstm.txt` | Windows 可选 | PyTorch LSTM |
| `requirements-host.txt` | Windows 远程控制端 | Paramiko、dotenv、rich、测试等 |
| `requirements-remote.txt` | Ubuntu 项目环境 | PyYAML、Pandas、PyArrow、测试；PySpark通常由 Spark 提供 |

安装示例：

```powershell
conda run -n intership python -m pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\scripts\install_lstm_dependencies.ps1 -CondaEnv intership
conda run -n intership python -m pip install -r requirements-host.txt
```

## 17. 测试目录

`tests/` 覆盖 API、清洗规则、国家映射、疫情聚合、特征、指标、LSTM、HDFS CLI、远程配置、项目同步、SSH、WebHDFS、WHO 采集等。

运行：

```powershell
conda run --no-capture-output -n intership pytest -q
```

其中外部网络、真实 SSH 和真实 HDFS 不应由普通单元测试直接依赖；相关测试使用 mock，真实环境用远程状态命令和运行报告验收。

## 18. 新手推荐运行顺序

### 18.1 第一次安装

```powershell
conda info --envs
conda run -n intership python -m pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\scripts\install_lstm_dependencies.ps1 -CondaEnv intership
```

### 18.2 每次更新 Raw 后重建

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_local_real_pipeline.ps1 -CondaEnv intership -EnableLstm -LstmEpochs 40 -BuildOnly
```

### 18.3 验证

```powershell
conda run --no-capture-output -n intership python scripts/verify_local_pipeline.py
conda run --no-capture-output -n intership pytest -q
```

### 18.4 启动网页

```powershell
conda run --no-capture-output -n intership python -m src.web.app
```

访问 `http://127.0.0.1:5000`。

### 18.5 远程 HDFS/Spark 课程实验

```powershell
conda run --no-capture-output -n disease_remote python scripts/remote_pipeline.py all --dry-run
conda run --no-capture-output -n disease_remote python scripts/remote_pipeline.py all --checksum
```

远程流程当前跑到 Silver；完整多疾病模型和网页仍由 18.2 的本地流程生成。

## 19. 产物检查顺序

1. Raw 是否存在且大小合理；
2. `data/silver/local` 是否有各来源规范表；
3. `data/gold/local/forecast_features.csv` 是否更新；
4. `data/models/local` 是否有 GBDT 和 6 个 `.pt`；
5. `data/serving/local_real_pipeline_manifest.json` 是否为本次时间；
6. `source_status.json` 是否 6 个模型均为 ok；
7. `options.json` 是否列出 6 种疾病及各自模型；
8. `/api/health`、`/api/options`、`/api/trend`、`/api/predictions` 是否返回 `ok: true`；
9. 网页切换疾病时日期、地区、模型和图表是否联动。

## 20. 报告文件索引

- `report/dataset.md`：全部数据来源、频率、范围、目录和许可证原则；
- `report/data_cleaning.md`：逐源清洗、Silver/Gold、质量和串联；
- `report/model.md`：模型原理、疾病差异、训练接口和输出；
- `report/flask.md`：Flask 路由、API 契约、缓存和前后端交互；
- `report/echarts.md`：自定义界面、官方参考、图表和动态渲染；
- `report/hdfs_spark.md`：Xshell + Ubuntu + Hadoop + Spark 从零教程；
- `report/all.md`：全数据流、项目结构和所有运行脚本说明。

## 21. 当前实现边界与后续工作

当前已经完成：本地六疾病多源清洗、三类模型体系、6 个 LSTM、Serving、Flask、ECharts，以及远程 HDFS 上传和三表 Spark Silver 控制链。

尚未完全统一：远程 HDFS/Spark 对 OWID、WHO、TB、呼吸数据的全量上传与清洗；远程 Gold、六疾病模型和完整 Serving 自动回传；生产级数据库和 Web 服务器。

把这些边界写清楚比宣称“所有代码都在大数据集群运行”更符合实验可重复性，也便于下一位组员继续开发。
