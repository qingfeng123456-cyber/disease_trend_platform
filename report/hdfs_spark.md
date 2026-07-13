# 实验报告（六）：Windows、Xshell、Ubuntu、HDFS 与 Spark 保姆教程

## 1. 先理解这套架构

老师所说的“主机 PyCharm 连接虚拟机 Hadoop/Spark”可能包含三种不同技术，不能把端口和用途混在一起：

1. **SSH/SFTP 控制模式（本项目已经实现，推荐）**：Windows Python 通过 SSH 在 Ubuntu 执行 `spark-submit`，通过 SFTP 同步代码和报告。Spark 真正在虚拟机运行。
2. **WebHDFS 模式（项目有客户端，但默认关闭）**：Windows 通过 HTTP REST 上传/下载 HDFS 文件。它只解决文件访问，不负责执行 Spark。
3. **Spark Connect 模式（可选，项目当前未采用）**：Windows PySpark 客户端通过 gRPC 连接 Spark Connect Server。要求客户端/服务端版本兼容，而且不是现有 Spark 作业的无修改替代。

Hadoop NameNode 的 `9870` 是管理网页，不是 Spark 计算接口；Spark `8080` 通常是 Standalone Master 管理网页；Spark 应用 `4040` 只在作业运行期间出现。浏览器能打开这些 URL 只代表管理端口可达，不代表 Python 已经能提交作业。

当前项目的推荐远程架构：

```text
Windows 11 + PyCharm + Conda
  |  Paramiko SSH/SFTP，端口 22
  v
Ubuntu 虚拟机项目目录
  |  hdfs dfs -put
  v
HDFS Raw
  |  spark-submit --master local[*]
  v
HDFS Silver Parquet
  |  SFTP 下载运行/质量报告
  v
Windows data/serving/remote
```

`local[*]` 表示 Spark 使用 Ubuntu 虚拟机全部逻辑核心运行，数据仍可从 HDFS 读写；这种教学单机模式不需要 YARN，也不需要启动 Spark Standalone Master。

## 2. 准备清单

### 2.1 Windows 主机

- VMware Workstation 或 VirtualBox；
- Ubuntu 虚拟机；
- Xshell（SSH 终端）和可选 Xftp；
- Git、Conda/Miniconda、PyCharm；
- 当前项目目录；
- 与虚拟机互通的网络。

Xshell 官方站：`https://www.netsarang.com/en/xshell/`。只从官方来源下载安装。

### 2.2 Ubuntu 虚拟机

- OpenSSH Server；
- Java（版本需同时兼容所装 Hadoop/Spark）；
- Hadoop；
- Spark；
- Miniconda 或系统 Python；
- 足够磁盘空间。Raw、HDFS 副本、Silver 和临时 shuffle 会同时占空间，建议至少预留 20 GB。

### 2.3 官方资料

- Hadoop 单节点：`https://hadoop.apache.org/docs/current/hadoop-project-dist/hadoop-common/SingleCluster.html`
- Hadoop 下载：`https://hadoop.apache.org/releases.html`
- WebHDFS：`https://hadoop.apache.org/docs/current/hadoop-project-dist/hadoop-hdfs/WebHDFS.html`
- Spark 下载：`https://spark.apache.org/downloads.html`
- Spark 提交应用：`https://spark.apache.org/docs/latest/submitting-applications.html`
- Spark Standalone：`https://spark.apache.org/docs/latest/spark-standalone.html`
- Spark Connect：`https://spark.apache.org/docs/latest/spark-connect-overview.html`
- PySpark 安装：`https://spark.apache.org/docs/latest/api/python/getting_started/install.html`
- PyCharm 解释器：`https://www.jetbrains.com/help/pycharm/configuring-python-interpreter.html`

版本选择以老师虚拟机现有版本优先。不要只追求“最新版”；Windows PySpark、Ubuntu Spark、Java 和 Hadoop 需要兼容。

## 3. 配置虚拟机网络

### 3.1 推荐：桥接网络

桥接模式让虚拟机像局域网中的独立电脑一样获得 IP，最适合课堂局域网。

Ubuntu 查看 IP：

```bash
hostname -I
ip address
```

假设显示 `192.168.1.100`。Windows PowerShell 测试：

```powershell
ping 192.168.1.100
Test-NetConnection 192.168.1.100 -Port 22
```

### 3.2 NAT 模式

如果桥接受校园网络限制，可以用 NAT。主机通常仍能访问虚拟机 NAT 地址；若不能，需要在 VMware/VirtualBox 配置端口转发，例如主机 `2222 -> 虚拟机 22`。此时远程配置使用主机可达地址和端口 2222。

### 3.3 IP 变化

每次重启 IP 可能变化。可在路由器做 DHCP 保留，或给 Ubuntu 配静态 IP。至少每次运行前执行 `hostname -I` 并核对 `config/remote_cluster.yaml`。

## 4. 安装并启用 SSH

在 Ubuntu 本地终端：

```bash
sudo apt update
sudo apt install -y openssh-server
sudo systemctl enable --now ssh
sudo systemctl status ssh
```

如果启用了 UFW：

```bash
sudo ufw allow OpenSSH
sudo ufw status
```

Windows 测试：

```powershell
ssh student@192.168.1.100
```

首次连接会显示主机指纹。应在 Ubuntu 执行 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` 核对，而不是无条件信任。

## 5. 用 Xshell 登录 Ubuntu

1. 打开 Xshell，新建会话。
2. 协议选 SSH。
3. 主机填写虚拟机 IP，端口通常 22。
4. 用户名填写 Ubuntu 用户，例如 `student`。
5. 首次连接核对主机指纹。
6. 使用密码登录；稳定后建议改用 SSH 私钥。

登录后执行：

```bash
whoami
hostname
pwd
hostname -I
```

不要在聊天、报告、Git 或 `config/remote_cluster.yaml` 中写明文密码。

## 6. 检查老师已经配置的环境

很多教学虚拟机已经装好 Hadoop/Spark，先检查，避免重复安装：

```bash
java -version
hadoop version
spark-submit --version
python3 --version
jps
which hdfs
which spark-submit
echo "$JAVA_HOME"
echo "$HADOOP_HOME"
echo "$SPARK_HOME"
echo "$HADOOP_CONF_DIR"
```

项目也提供：

```bash
bash scripts/check_environment.sh
python scripts/check_bigdata_environment.py --config config/settings.yaml
```

如果三者都正常，直接跳到第 11 节配置项目。只有命令缺失时才继续安装。

## 7. 安装 Java、Hadoop 与 Spark（空白 Ubuntu）

### 7.1 Java

Hadoop 3.x 与 Spark 3.x 教学环境通常可使用 JDK 11；Spark 4.x 通常需要更高版本。先查看所选发行版官方要求。以下以 JDK 11 的 Hadoop 3/Spark 3 教学环境为例：

```bash
sudo apt update
sudo apt install -y openjdk-11-jdk ssh rsync curl wget
java -version
readlink -f "$(which java)"
```

找到 Java 根目录，例如 `/usr/lib/jvm/java-11-openjdk-amd64`。

### 7.2 创建安装目录

```bash
sudo mkdir -p /opt/bigdata
sudo chown -R "$USER":"$USER" /opt/bigdata
```

### 7.3 下载 Hadoop

从 `https://hadoop.apache.org/releases.html` 选择稳定版本并校验 SHA512/GPG。示例变量中的版本号必须替换成实际下载版本：

```bash
cd /tmp
HADOOP_VERSION=3.x.y
wget "https://downloads.apache.org/hadoop/common/hadoop-${HADOOP_VERSION}/hadoop-${HADOOP_VERSION}.tar.gz"
tar -xzf "hadoop-${HADOOP_VERSION}.tar.gz" -C /opt/bigdata
ln -s "/opt/bigdata/hadoop-${HADOOP_VERSION}" /opt/bigdata/hadoop
```

### 7.4 下载 Spark

从 `https://spark.apache.org/downloads.html` 选择与 Hadoop 兼容的预构建包：

```bash
cd /tmp
SPARK_VERSION=3.x.y
SPARK_PACKAGE="spark-${SPARK_VERSION}-bin-hadoop3"
wget "https://downloads.apache.org/spark/spark-${SPARK_VERSION}/${SPARK_PACKAGE}.tgz"
tar -xzf "${SPARK_PACKAGE}.tgz" -C /opt/bigdata
ln -s "/opt/bigdata/${SPARK_PACKAGE}" /opt/bigdata/spark
```

如果所选版本已进入 Apache Archive，或官网提供的预构建包名称不是 `bin-hadoop3`，应以下载页给出的实际 URL 和 SHA512 为准，再同步修改 `SPARK_PACKAGE`。

### 7.5 环境变量

编辑 `~/.bashrc`，添加：

```bash
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
export HADOOP_HOME=/opt/bigdata/hadoop
export SPARK_HOME=/opt/bigdata/spark
export HADOOP_CONF_DIR=$HADOOP_HOME/etc/hadoop
export PATH=$PATH:$HADOOP_HOME/bin:$HADOOP_HOME/sbin:$SPARK_HOME/bin:$SPARK_HOME/sbin
export PYSPARK_PYTHON=python
```

加载并验证：

```bash
source ~/.bashrc
java -version
hadoop version
spark-submit --version
```

在 `$HADOOP_HOME/etc/hadoop/hadoop-env.sh` 中也设置正确 `JAVA_HOME`。

## 8. 配置单机伪分布式 HDFS

### 8.1 创建数据目录

```bash
mkdir -p ~/hadoop-data/namenode ~/hadoop-data/datanode
```

### 8.2 `core-site.xml`

编辑 `$HADOOP_HOME/etc/hadoop/core-site.xml`：

```xml
<configuration>
  <property>
    <name>fs.defaultFS</name>
    <value>hdfs://localhost:9000</value>
  </property>
</configuration>
```

### 8.3 `hdfs-site.xml`

```xml
<configuration>
  <property>
    <name>dfs.replication</name>
    <value>1</value>
  </property>
  <property>
    <name>dfs.namenode.name.dir</name>
    <value>file:///home/student/hadoop-data/namenode</value>
  </property>
  <property>
    <name>dfs.datanode.data.dir</name>
    <value>file:///home/student/hadoop-data/datanode</value>
  </property>
</configuration>
```

把 `/home/student` 替换为 `echo $HOME` 的真实结果。

### 8.4 本机免密 SSH

Hadoop 启停脚本会 SSH 到 localhost：

```bash
ssh-keygen -t ed25519
cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys
ssh localhost
exit
```

### 8.5 只在全新集群格式化一次

```bash
hdfs namenode -format
```

**危险提醒：只对从未使用的新 NameNode 执行一次。已有 HDFS 数据时绝对不要再次格式化，否则元数据会丢失。** 项目的 `init_hdfs.sh` 和服务脚本都故意不会执行 format。

### 8.6 启动和验证 HDFS

```bash
start-dfs.sh
jps
hdfs dfsadmin -report
hdfs dfs -mkdir -p /user/$USER
hdfs dfs -ls /
```

`jps` 应看到 NameNode、DataNode、SecondaryNameNode。浏览器或 SSH 隧道访问 `http://虚拟机IP:9870`。

## 9. Spark 运行模式

### 9.1 推荐：`local[*]`

本项目 `config/settings.yaml` 和远程示例默认使用：

```bash
spark-submit --master 'local[*]' your_job.py
```

不需要 `start-master.sh`、`start-worker.sh` 和 YARN。Spark 计算进程在 Ubuntu 单机运行，输入/输出仍可以是 HDFS。

简单验证：

```bash
spark-submit --master 'local[*]' --version
pyspark --master 'local[*]'
```

进入 PySpark 后：

```python
spark.range(10).show()
```

### 9.2 可选：Spark Standalone

只有老师要求演示 Standalone 集群时才启用：

```bash
start-master.sh
start-worker.sh spark://localhost:7077
jps
```

Master 提交地址通常为 `spark://虚拟机IP:7077`，网页通常是 `http://虚拟机IP:8080`。管理网页 8080 不能代替 7077 提交地址。

### 9.3 可选：YARN

项目单机路线不需要 YARN。若老师要求，需额外配置 `mapred-site.xml`、`yarn-site.xml`，启动 `start-yarn.sh`，再使用 `--master yarn`。不要在尚未配置 YARN 时仅因为看到端口 8088 就切换。

## 10. Ubuntu Conda 环境

如果老师的 Spark 已能找到系统 Python，可直接使用；为隔离项目依赖，建议创建：

```bash
conda create -n disease_platform python=3.10 -y
conda activate disease_platform
python -m pip install -r requirements-remote.txt
```

如果 `conda` 在非交互 SSH 命令中不可用，项目配置通过 `conda_executable` 指向完整路径，例如 `/home/student/miniconda3/bin/conda`。

通常不在 Conda 环境重复安装 PySpark，因为 `spark-submit` 自带与服务端匹配的 PySpark。只有发行版明确要求时，才安装与 `spark-submit --version` 完全匹配的 `pyspark`。

## 11. 配置 HDFS 项目目录

在 Ubuntu 项目根目录：

```bash
bash scripts/start_bigdata_services.sh
bash scripts/init_hdfs.sh
hdfs dfs -ls -R /disease_platform
```

会创建：

```text
/disease_platform/raw
/disease_platform/silver
/disease_platform/gold
/disease_platform/serving
/disease_platform/checkpoints
```

停止服务：

```bash
bash scripts/stop_bigdata_services.sh
```

如果使用了 YARN，则启停命令追加 `--with-yarn`。

## 12. 配置 Windows Conda 与 PyCharm

### 12.1 创建 Windows 控制环境

可新建轻量环境：

```powershell
conda create -n disease_remote python=3.10 -y
conda run -n disease_remote python -m pip install -r requirements-host.txt
```

也可复用项目已有 `intership`：

```powershell
conda run -n intership python -m pip install -r requirements-host.txt
```

检查环境名：

```powershell
conda info --envs
```

项目使用的是 `intership`，不是 `inter`。

### 12.2 PyCharm 解释器

1. `Settings -> Project -> Python Interpreter`。
2. `Add Interpreter -> Add Local Interpreter -> Conda`。
3. 选择 Existing Environment。
4. 指向 `disease_remote` 或 `intership` 的 `python.exe`。
5. 在 PyCharm Terminal 中运行 `python -c "import paramiko,yaml; print('ok')"`。

PyCharm 只是编辑器和 Windows 控制端；当前方案不要求在 Windows 安装 Hadoop、Spark、Java 或 PySpark。

## 13. 配置远程连接文件

复制模板：

```powershell
Copy-Item config\remote_cluster.example.yaml config\remote_cluster.yaml
Copy-Item .env.example .env
```

编辑 `config/remote_cluster.yaml`：

```yaml
remote:
  host: 192.168.1.100
  port: 22
  username: student
  auth_method: password
  project_dir: /home/student/disease_trend_platform
  conda_env: disease_platform
  conda_executable: /home/student/miniconda3/bin/conda

bigdata:
  spark_master: "local[*]"
  start_hdfs_when_missing: true
  start_yarn: false
  use_webhdfs: false
```

在 `.env` 中填写 `REMOTE_PASSWORD`，或改成密钥认证并配置 `key_file`。`.env` 和 `config/remote_cluster.yaml` 都不应提交 Git。

首次建议保持 `allow_unknown_host: false`。把 Ubuntu 主机公钥指纹加入可信主机后再自动运行。

## 14. Windows 远程控制命令

以下命令均在项目根目录执行。

### 14.1 只生成计划，不连接

```powershell
conda run --no-capture-output -n disease_remote python scripts/remote_pipeline.py all --dry-run
```

### 14.2 检查远程状态

```powershell
conda run --no-capture-output -n disease_remote python scripts/remote_pipeline.py status
```

### 14.3 同步项目

```powershell
conda run --no-capture-output -n disease_remote python scripts/remote_pipeline.py sync
```

同步会遵守 `sync.exclude`，默认不上传 `.git`、`.idea`、缓存、日志和本地 Silver/Gold/Models。大 Raw 是否上传由 `upload_raw_data` 控制。

### 14.4 启动 HDFS

```powershell
conda run --no-capture-output -n disease_remote python scripts/remote_pipeline.py start
```

### 14.5 上传 Raw 到 HDFS

```powershell
conda run --no-capture-output -n disease_remote python scripts/remote_pipeline.py upload --checksum
```

`--checksum` 更可靠但对大文件更慢；`--force` 会覆盖已存在文件。

### 14.6 运行 Spark Silver

```powershell
conda run --no-capture-output -n disease_remote python scripts/remote_pipeline.py silver
```

### 14.7 下载报告

```powershell
conda run --no-capture-output -n disease_remote python scripts/remote_pipeline.py download
```

### 14.8 一键执行当前远程流程

```powershell
conda run --no-capture-output -n disease_remote python scripts/remote_pipeline.py all --checksum
```

执行顺序是状态检查、同步、环境报告、服务启动、Raw 上传、HDFS 检查、Silver Spark 作业、再次检查、下载报告。运行记录在 `data/serving/remote/` 和日志中。

## 15. 当前 Spark Silver 的输入与输出

上传器 `scripts/upload_raw_to_hdfs.py` 当前正式发现：

- Kaggle COVID；
- Kaggle World Population；
- Open-Meteo 国家/年份天气。

支持参数：

```bash
python scripts/upload_raw_to_hdfs.py --dataset all --dry-run
python scripts/upload_raw_to_hdfs.py --dataset all --verify
python scripts/upload_raw_to_hdfs.py --dataset weather --force --verify
```

Silver 编排器：

```bash
python scripts/run_silver_pipeline.py --master 'local[*]'
```

它运行：

```text
clean_epidemic.py
clean_population.py
clean_weather.py
data_quality_report.py
```

输出 HDFS Parquet 和 `data/serving/silver_pipeline_run.json`。可用 `--skip-epidemic`、`--skip-population`、`--skip-weather`、`--skip-quality` 或 `--dry-run`。

## 16. 在 Xshell 中查看运行结果

```bash
jps
hdfs dfsadmin -report
hdfs dfs -ls -R /disease_platform/raw
hdfs dfs -ls -R /disease_platform/silver
hdfs dfs -du -h /disease_platform/raw
hdfs dfs -du -h /disease_platform/silver
cat data/serving/silver_pipeline_run.json
```

检查 Parquet 样例：

```bash
pyspark --master 'local[*]'
```

```python
df = spark.read.parquet("hdfs:///disease_platform/silver/epidemic")
df.printSchema()
df.show(5, truncate=False)
df.count()
```

不要用 `hdfs dfs -cat` 直接阅读 Parquet，它是二进制列式文件。

## 17. 通过 Xshell 隧道查看管理页面

如果 Windows 不能直接访问虚拟机端口，可在 Xshell 会话属性中设置 SSH Tunneling：

| 本地端口 | 远端主机 | 远端端口 | 浏览器地址 |
|---:|---|---:|---|
| 19870 | `127.0.0.1` | 9870 | `http://127.0.0.1:19870` NameNode |
| 18088 | `127.0.0.1` | 8088 | `http://127.0.0.1:18088` YARN（若启用） |
| 18080 | `127.0.0.1` | 8080 | `http://127.0.0.1:18080` Spark Master（若启用） |
| 14040 | `127.0.0.1` | 4040 | `http://127.0.0.1:14040` 当前 Spark 作业 |

也可以使用项目工具打印/打开地址：

```powershell
conda run -n disease_remote python scripts/open_cluster_webui.py --config config/remote_cluster.yaml
```

Spark 4040 只有作业仍在运行时可用；作业结束后打不开是正常现象。

## 18. 本地与远程模式如何自由切换

### 18.1 模式 A：Windows 本地真实完整模式（当前推荐演示）

用途：清洗所有当前数据源、训练 GBDT 和 6 个 LSTM、更新网页。

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_local_real_pipeline.ps1 -CondaEnv intership -EnableLstm -LstmEpochs 40 -BuildOnly
conda run --no-capture-output -n intership python -m src.web.app
```

数据流：`data/raw -> data/silver/local -> data/gold/local -> data/models/local -> data/serving -> Flask`。

### 18.2 模式 B：Ubuntu HDFS/Spark Silver 教学模式

用途：演示 HDFS 分层存储和 Spark 分布式 API 清洗。

```powershell
conda run --no-capture-output -n disease_remote python scripts/remote_pipeline.py all --checksum
```

数据流：`Windows Raw -> Ubuntu -> HDFS Raw -> Spark -> HDFS Silver -> 运行报告回传`。

当前该命令**不会**训练六个 LSTM，也不会自动覆盖本地完整的 `data/serving/trend.json` 等网页文件。因此远程 Silver 跑完后直接打开本地网页，网页仍显示最近一次本地完整流水线生成的 Serving，这是当前架构边界，不是缓存 bug。

### 18.3 模式 C：旧 Spark Gold/GBT/Serving 路线

仓库保留 `scripts/run_pipeline.sh`，可串联 Spark 清洗、特征、MLlib GBT 和 Dashboard 导出。但它使用早期的 OWID/World Bank/Open-Meteo HDFS 目录约定，与较新的三类 Kaggle Silver 控制链及六疾病本地模式并未完全统一。

课程演示前不要直接用它覆盖当前 Serving。若要正式启用，下一阶段应统一 HDFS 路径、把 OWID/WHO/TB/呼吸数据上传器补齐、验证 Gold Schema，再把远程 Serving 下载到一个独立目录测试。

### 18.4 真正的“一键模式切换”含义

当前可以自由切换“运行哪条流水线”，但 Flask 的数据源仍是本地 `SERVING_DIR`。若未来要让 Flask 在两个 Serving 集合中切换，可使用两个目录：

```text
data/serving/local_complete/
data/serving/remote_spark/
```

启动前设置 `SERVING_DIR` 指向对应目录。只有远程 Spark 已经生成完整且通过 API 契约验证的 JSON 时，才能切到 remote_spark；不能让 Flask 直接把 HDFS Parquet 当成现有 JSON 读取。

## 19. Spark Connect 可选方案

如果老师明确要求“Windows PyCharm 中写 PySpark，直接连接 URL 执行”，可以研究 Spark Connect：

1. Ubuntu 启动 Spark Connect Server，常用 gRPC 端口 15002；
2. Windows 安装与服务端兼容的 `pyspark[connect]`；
3. Python 使用 `SparkSession.builder.remote("sc://IP:15002").getOrCreate()`；
4. 在 VM 防火墙和虚拟机网络放通端口，最好用 SSH 隧道。

但是当前项目 Spark 作业按经典 `spark-submit` 编写，某些 SparkContext/JVM API 在 Connect 中不可用。故 Spark Connect 是扩展实验，不是现在最稳妥的运行方式。

## 20. 常见故障排查

### 20.1 SSH 连接失败

```powershell
Test-NetConnection 192.168.1.100 -Port 22
```

检查虚拟机 IP、网络模式、`systemctl status ssh`、UFW 和用户名。

### 20.2 `hdfs` 或 `spark-submit` 找不到

```bash
source ~/.bashrc
echo $PATH
which hdfs
which spark-submit
```

远程非交互 shell 不一定加载 `.bashrc`，可在 `remote_cluster.yaml` 填完整 `hadoop_home`、`spark_home`、`java_home`。

### 20.3 NameNode 无法启动

检查：

```bash
jps
tail -n 100 "$HADOOP_HOME"/logs/*namenode*.log
```

不要用重新 format 作为通用修复。优先查 Java、目录权限、端口占用和配置路径。

### 20.4 Spark 读不到 HDFS

```bash
hdfs getconf -confKey fs.defaultFS
hdfs dfs -ls /disease_platform/raw
echo $HADOOP_CONF_DIR
```

确保 Spark 进程能读取同一套 `core-site.xml` 和 `hdfs-site.xml`。

### 20.5 Python 版本/包不一致

```bash
which python
python -V
spark-submit --version
```

设置 `PYSPARK_PYTHON` 为远程 Conda 环境 Python，所有 worker 在单机模式下使用同一路径。

### 20.6 网页仍是旧数据

远程 Silver 只生成 HDFS Silver 和报告，不会生成当前六疾病 Serving。若要更新网页，运行 Windows 本地完整流水线；若未来接通远程 Gold/Serving，则先下载完整 JSON 到 Flask 的 `SERVING_DIR`。

## 21. 推荐课堂演示顺序

1. Xshell 登录 Ubuntu，执行 `jps` 和 `hdfs dfs -ls -R /disease_platform`。
2. Windows 执行 `remote_pipeline.py status`。
3. 用 `upload --checksum` 展示 Raw 上传清单。
4. 执行 `silver`，在日志中展示每个 Spark 作业。
5. 作业运行时打开 4040，结束后在 9870 查看 Silver 目录。
6. 用 PySpark `printSchema/show/count` 展示 Parquet。
7. 回到 Windows，执行本地完整模型流水线并展示 6 个 LSTM 训练进度。
8. 启动 Flask，展示 API 和 ECharts。
9. 明确说明远程链当前负责 HDFS/Spark Silver，本地链负责完整多疾病模型和网页，避免把两条路径混称成同一条已完成链。
