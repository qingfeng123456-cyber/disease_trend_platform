# Ubuntu Hadoop + Spark 运行手册

本手册用于把 Windows 中开发好的项目迁移到 Ubuntu 虚拟机，并运行 HDFS raw 上传和 Spark Silver 清洗。

## 1. 从 Windows 上传项目到 Ubuntu

在 Windows 中可以把整个项目目录压缩后上传，也可以使用 `scp`。示例：

```powershell
scp -r disease_trend_platform user@ubuntu-host:~/disease_trend_platform
```

进入 Ubuntu 后：

```bash
cd ~/disease_trend_platform
```

项目代码不要依赖 Windows 的 `D:\` 路径，所有脚本都会从当前项目目录自动解析相对路径。

## 2. 创建 Python 虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate
python --version
pip install -r requirements.txt
```

如果 Ubuntu 网络较慢，可以先安装运行脚本必需的包，再按课程环境补齐。

## 3. Hadoop 和 Spark 的区别

Hadoop HDFS 负责分布式文件存储，本项目用它保存：

- `/disease_platform/raw`
- `/disease_platform/silver`
- `/disease_platform/gold`
- `/disease_platform/serving`

Spark 负责分布式计算，本项目用 PySpark 把 raw CSV 清洗成 Silver Parquet。

使用 `local[*]` 模式时，不需要提前启动 Spark 常驻服务；`spark-submit` 会在运行任务时启动 Spark 作业。

## 4. 检查 Java、Hadoop、Spark

```bash
python scripts/check_bigdata_environment.py
```

也可以手工检查：

```bash
java -version
hadoop version
spark-submit --version
which hdfs
which spark-submit
hdfs getconf -confKey fs.defaultFS
jps
```

如果 `hdfs` 或 `spark-submit` 不存在，需要先配置 Hadoop/Spark 的 `PATH`。

## 5. 启动 HDFS

本项目只需要 HDFS 和 Spark local 模式，默认不需要 YARN。

```bash
bash scripts/start_bigdata_services.sh
```

如果你准备使用 YARN，再执行：

```bash
bash scripts/start_bigdata_services.sh --with-yarn
```

禁止执行：

```bash
hdfs namenode -format
```

除非能确认是第一次初始化的全新环境，否则格式化 NameNode 可能清空已有 HDFS 元数据。

## 6. 检查 jps

启动 HDFS 后应看到类似进程：

```bash
jps
```

通常至少应包含：

- NameNode
- DataNode
- SecondaryNameNode

使用 `local[*]` 跑 Spark 时，不要求看到 Spark 常驻进程。

## 7. 初始化项目 HDFS 目录

```bash
bash scripts/init_hdfs.sh
```

该脚本会创建：

- `/disease_platform`
- `/disease_platform/raw`
- `/disease_platform/silver`
- `/disease_platform/gold`
- `/disease_platform/serving`
- `/disease_platform/checkpoints`

脚本可重复运行，不会格式化 NameNode，不会删除已有数据。

## 8. 上传 raw 原始数据

先做计划预览：

```bash
python scripts/upload_raw_to_hdfs.py --config config/settings.yaml --dataset all --dry-run
```

正式上传并验证文件大小：

```bash
python scripts/upload_raw_to_hdfs.py \
  --config config/settings.yaml \
  --dataset all \
  --verify
```

如果 HDFS 已存在同名文件且确认需要覆盖：

```bash
python scripts/upload_raw_to_hdfs.py \
  --config config/settings.yaml \
  --dataset all \
  --force \
  --verify
```

上传清单保存在：

- `data/serving/hdfs_upload_manifest.json`

## 9. 检查上传结果

```bash
hdfs dfs -ls -R /disease_platform/raw
```

关键路径应包括：

- `/disease_platform/raw/kaggle/epidemic/covid_19_data.csv`
- `/disease_platform/raw/kaggle/population/world_population.csv`
- `/disease_platform/raw/open_meteo/CHN/`
- `/disease_platform/raw/open_meteo/USA/`
- `/disease_platform/raw/open_meteo/GBR/`

## 10. 运行 Spark Silver 清洗

推荐使用流水线脚本：

```bash
python scripts/run_silver_pipeline.py \
  --config config/settings.yaml \
  --master "local[*]"
```

该脚本会依次调用：

- `src/spark_jobs/clean_epidemic.py`
- `src/spark_jobs/clean_population.py`
- `src/spark_jobs/clean_weather.py`
- `src/spark_jobs/data_quality_report.py`

也可以单独运行某个作业：

```bash
spark-submit \
  --master "local[*]" \
  src/spark_jobs/clean_epidemic.py \
  --config config/settings.yaml
```

```bash
spark-submit \
  --master "local[*]" \
  src/spark_jobs/clean_population.py \
  --config config/settings.yaml
```

```bash
spark-submit \
  --master "local[*]" \
  src/spark_jobs/clean_weather.py \
  --config config/settings.yaml
```

```bash
spark-submit \
  --master "local[*]" \
  src/spark_jobs/data_quality_report.py \
  --config config/settings.yaml
```

## 11. 检查 Silver Parquet

```bash
hdfs dfs -ls -R /disease_platform/silver
```

应看到：

- `/disease_platform/silver/epidemic`
- `/disease_platform/silver/population`
- `/disease_platform/silver/weather`

## 12. 查看数据质量报告

本地报告：

```bash
cat data/serving/silver_data_quality_report.json
```

HDFS 报告：

```bash
hdfs dfs -cat /disease_platform/serving/silver_data_quality_report.json
```

流水线运行记录：

```bash
cat data/serving/silver_pipeline_run.json
```

## 13. 停止服务

如果只启动了 HDFS：

```bash
bash scripts/stop_bigdata_services.sh
```

如果也启动了 YARN：

```bash
bash scripts/stop_bigdata_services.sh --with-yarn
```

停止脚本不会删除 HDFS 数据。

## 14. 常见错误

### hdfs command not found

说明 Hadoop 没装好或 `PATH` 没配置。先检查：

```bash
which hdfs
hadoop version
```

### HDFS is not accessible

说明 HDFS 服务未启动或配置有问题。先执行：

```bash
start-dfs.sh
jps
hdfs dfs -ls /
```

### spark-submit command not found

说明 Spark 没装好或 `PATH` 没配置。先检查：

```bash
which spark-submit
spark-submit --version
```

### raw 输入不存在

先确认上传步骤成功：

```bash
hdfs dfs -ls -R /disease_platform/raw
cat data/serving/hdfs_upload_manifest.json
```

### PySpark 读取 Open-Meteo 元数据 JSON 报错

本项目天气清洗使用 `/*/*.csv` 输入模式，只读取 CSV，不会读取 `.meta.json`。如果手动改了输入路径，请不要直接读整个目录下所有文件。

### local[*] 是否需要 YARN

不需要。`local[*]` 会在当前机器本地启动 Spark 作业，适合课程项目和单机虚拟机环境。只有要用集群资源管理时才考虑 YARN。
