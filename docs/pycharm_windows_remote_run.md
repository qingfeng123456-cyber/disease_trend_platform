# Windows PyCharm 一键远程运行说明

本项目的新运行架构是：

```text
Windows PyCharm 本地 Python 控制端
-> SSH/SFTP 连接 Ubuntu 虚拟机
-> Ubuntu 执行 HDFS 和 spark-submit
-> HDFS raw 到 HDFS silver
-> SFTP 下载 JSON 报告回 Windows
```

这不是连接 Hadoop 网页执行程序。Hadoop 的 9870 页面只是 NameNode 管理网页，不能当作 Spark 计算接口。

## 1. Windows 和 Ubuntu 分工

Windows：

- 保存项目源代码
- 使用 PyCharm 和本地 Conda 解释器
- 运行 `scripts/remote_pipeline.py`
- 通过 SSH/SFTP 控制 Ubuntu
- 查看 PyCharm 控制台中的 Spark 日志
- 查看下载回来的 JSON 报告

Ubuntu：

- 安装 Java、Hadoop、HDFS、Spark
- 不需要图形界面
- 运行 `hdfs dfs`
- 运行 `spark-submit`
- 生成 HDFS Silver Parquet

## 2. Windows Conda 安装依赖

建议创建一个单独的本地 Conda 环境：

```powershell
conda create -n disease_remote python=3.12 -y
conda activate disease_remote
pip install -r requirements-host.txt
```

Windows 主机不需要安装：

- Java
- Hadoop
- Spark
- PySpark

## 3. 填写 remote_cluster.yaml

复制模板：

```powershell
copy config\remote_cluster.example.yaml config\remote_cluster.yaml
```

需要填写：

- `remote.host`：Ubuntu 虚拟机 IP
- `remote.port`：一般是 22
- `remote.username`：Ubuntu 用户名
- `remote.auth_method`：`password` 或 `key`
- `remote.key_file`：私钥认证时填写
- `remote.project_dir`：Ubuntu 上项目目录，例如 `/home/student/disease_trend_platform`
- `remote.conda_env`：Ubuntu 上用于运行 Python 脚本的 Conda 环境名
- `remote.conda_executable`：Ubuntu 上 conda 可执行文件路径
- `bigdata.hadoop_home`、`bigdata.spark_home`：如果 Ubuntu 的 PATH 已配置好，可以先留空

密码不要写进 YAML。

## 4. 填写 .env

复制模板：

```powershell
copy .env.example .env
```

如果用密码认证：

```text
REMOTE_PASSWORD=你的Ubuntu密码
REMOTE_KEY_PASSPHRASE=
```

如果用私钥认证：

```text
REMOTE_PASSWORD=
REMOTE_KEY_PASSPHRASE=你的私钥口令
```

`.env` 已加入 `.gitignore`，不要提交。

## 5. 查询虚拟机 IP

在 Ubuntu 的 Xshell 中执行：

```bash
hostname -I
```

把返回的 IP 填到 `remote.host`。

## 6. 测试 SSH

Windows PowerShell 可以先测试：

```powershell
ssh student@192.168.1.100
```

能登录后，再运行 PyCharm 一键脚本。

## 7. PyCharm 设置

1. 打开 PyCharm。
2. 选择 Windows 本地 Conda 环境 `disease_remote`。
3. 打开 Run Configurations。
4. 选择项目中的共享配置 `Remote Silver Pipeline`。
5. 确认：
   - Script：`scripts/remote_pipeline.py`
   - Parameters：`all --config config/remote_cluster.yaml --env-file .env`
   - Working directory：项目根目录
   - Python interpreter：Windows 本地 `disease_remote`
6. 点击绿色运行按钮。

## 8. 一键脚本会做什么

`all` 命令会自动执行：

1. 读取远程配置和 `.env`
2. 检查本地项目必要数据
3. SSH 连接 Ubuntu
4. 检查远程环境
5. 创建远程项目目录
6. SFTP 同步代码和 raw 数据
7. 检查或启动 HDFS
8. 执行 `scripts/init_hdfs.sh`
9. 远程执行 `upload_raw_to_hdfs.py`
10. 远程执行 `run_silver_pipeline.py`
11. 实时显示 Spark 日志
12. 检查 HDFS raw/silver 目录
13. 下载 JSON 报告到 Windows

下载目录：

```text
data/serving/remote/
```

运行记录：

```text
data/serving/remote/remote_pipeline_run.json
logs/remote_pipeline.log
```

日志不会记录密码、私钥内容或口令。

## 9. 打开 Hadoop 和 Spark 网页

运行：

```powershell
python scripts\open_cluster_webui.py --config config\remote_cluster.yaml
```

默认检查并打开：

- NameNode：`http://<remote_host>:9870`
- YARN：`http://<remote_host>:8088`
- Spark Master：`http://<remote_host>:8080`

Spark Application `4040` 只有 Spark 作业运行期间才存在：

```powershell
python scripts\open_cluster_webui.py --config config\remote_cluster.yaml --include-spark-application
```

如果端口不可访问，先检查虚拟机网络、防火墙、服务是否启动或端口映射。脚本不会自动修改 Ubuntu 防火墙。

## 10. 常见错误

### SSH 连接失败

检查：

- Ubuntu 是否开机
- IP 是否正确
- SSH 服务是否启动
- Windows 是否能 `ping` 通虚拟机
- 端口 22 是否开放

### Host key unknown

默认不会无提示接受未知主机。可以先用 Windows `ssh user@host` 接受主机指纹，或在配置中显式设置：

```yaml
allow_unknown_host: true
```

第一次接受未知主机时，脚本会打印主机指纹和安全提示。

### HDFS 未启动

如果配置允许，脚本会执行：

```bash
start-dfs.sh
```

如果仍失败，用 Xshell 登录 Ubuntu 检查：

```bash
jps
hdfs dfs -ls /
```

### Spark 作业失败

PyCharm 控制台会显示远程 stdout/stderr。失败日志也会写入：

```text
data/serving/remote/remote_pipeline_run.json
logs/remote_pipeline.log
```

### HDFS Safe Mode

脚本不会自动强制退出 Safe Mode。请先在 Ubuntu 检查 NameNode 状态，再决定如何处理。

### 磁盘空间不足

用 Xshell 检查：

```bash
df -h
free -h
```

## 11. 安全警告

不要执行：

```bash
hdfs namenode -format
```

除非你能确认这是第一次初始化的新 HDFS，否则格式化 NameNode 可能清空已有 HDFS 元数据。
