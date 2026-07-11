# 部署说明

## Demo 部署

```bash
cd disease_trend_platform
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m src.collectors.generate_demo_data
bash scripts/start_web.sh
```

访问：

```text
http://服务器IP:5000
```

## SSH 隧道

```bash
ssh -L 5000:127.0.0.1:5000 用户名@服务器IP
```

本机访问：

```text
http://127.0.0.1:5000
```

## 真实数据部署

```bash
python -m src.collectors.run_all --sources owid world_bank open_meteo china_cdc
bash scripts/init_hdfs.sh
bash scripts/upload_raw_to_hdfs.sh
bash scripts/run_spark_pipeline.sh
bash scripts/start_web.sh
```

## 可选生产化方向

- 用 systemd 管理 Flask 进程。
- 用 Nginx 反向代理。
- 定时运行采集和 Spark 作业。

基础版本不依赖 Redis、Nginx 或 Docker。
