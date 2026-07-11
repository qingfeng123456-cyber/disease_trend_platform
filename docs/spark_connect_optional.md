# Spark Connect 可选说明

本项目当前主路径是：

```text
Windows PyCharm 本地 Python 控制端
-> SSH/SFTP
-> Ubuntu spark-submit
-> HDFS raw/silver
```

Spark 3.4 以后可以使用 Spark Connect，让客户端通过远程协议连接 Spark 服务。但当前课程项目不依赖 Spark Connect，原因是：

- 用户的 Windows 主机不需要安装 Java、Hadoop 或完整 Spark。
- 已有 PySpark 作业可以直接在 Ubuntu 中通过 `spark-submit` 执行。
- HDFS 读写和 Spark 运行环境都在 Ubuntu，依赖更少，排错更直观。
- 远程日志可以通过 SSH 实时回传到 PyCharm 控制台。

因此不要为了 Spark Connect 重写已有 `clean_epidemic.py`、`clean_population.py`、`clean_weather.py` 或 `data_quality_report.py`。

如果后续确认 Ubuntu Spark 版本不低于 3.4，并且课程要求使用 Spark Connect，可以单独新增可选实验分支；主流程仍建议保留 SSH + spark-submit。
