# 本地模型训练与运行审计

## 数据进入模型的真实范围

- `naive_last_value` 和 `moving_average` 覆盖全部疾病，并根据日频、周频、年频分别使用当前值或 7 点、4 点、3 点移动平均。
- `local_sklearn_gbdt` 只训练 COVID-19 日频目标，输入病例滞后/滚动特征、同期天气、人口、密度、城市化、GDP 和日历特征。天气缺失不会删除疫情行，而由 `has_weather` 标记并用训练集统计量补齐。
- `local_pytorch_lstm*` 为每种疾病训练独立模型：COVID-19 为日频，流感、RSV、新冠住院为周频，结核病和 HIV/AIDS 为年频。日频 COVID-19 预测来源发布的 `new_cases_smoothed`；周频和年频疾病直接预测原始 `value`，不再用移动平均值替代真实标签。每个模型拥有独立权重、标准化器、时间切分和指标；当前 LSTM 只读取对应疾病的历史目标序列与地区嵌入，不读取天气或社会经济协变量。
- 周频与年频序列只按其原生日历补齐短内部缺口，且只允许对输入历史做有限插值；目标日期必须有原始观测值。不同频率和不同单位不会混入同一个 LSTM，也不会扩成虚假的日频样本。

逐疾病和逐模型的机器可读报告为 `data/serving/model_data_coverage.json`，接口为 `GET /api/model-coverage`。

## LSTM 轮次

`-LstmEpochs 40` 表示最多 40 轮。默认 `-LstmPatience 5`，还原到原始目标单位后的验证集 MAE 连续 5 轮未改善会提前停止；日志中的 `Early stopping after 10 epochs` 表示实际完成 10 轮，并加载原始尺度验证 MAE 最好的轮次，不是卡死或跳过训练。训练仍使用标准化 `log1p` 目标上的 `SmoothL1Loss` 做梯度优化，日志会同时显示 `val_loss` 和可直接解释的 `val_mae`。

## 结核病数值与模型诊断

- 结核病主趋势是“每 10 万人年估计发病率”，不是病例总数。美国 2022 年原始值为 `2.6`；前端现按一位小数显示，不再四舍五入成 `3`。
- 原始结核病目录包含多个国家、年份和不同指标。网页主曲线只使用发病率主指标；其余死亡、发现率、治疗、HIV 合并感染等指标保留为辅助字段，不能当作同一目标纵向拼接。
- 年频数据每个国家只有 2000--2022 年 23 个点。当前 LSTM 的样本量和输入信息明显少于日频 COVID-19，最近值基线又很强，因此网页应按测试 MAE 如实显示最佳模型，而不是强行把 LSTM 标成最佳。

强制跑满 40 轮：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_local_real_pipeline.ps1 -EnableLstm -LstmEpochs 40 -DisableLstmEarlyStopping -BuildOnly
```

## 端口

Windows pandas 本地流水线在清洗、特征和训练期间不需要 HDFS/Spark 端口。网页启动后只需要 Flask 的 TCP `5000`。`9870`、`8088`、`8080`、`7077` 分别属于可选的 HDFS/YARN/Spark 环境，在本地模式关闭是正常状态。

## 全链路验证

```powershell
conda run --no-capture-output -n intership python scripts\verify_local_pipeline.py
```

验证器检查 Silver/Gold/模型/serving 文件、所有疾病完整默认日期、主要 Flask API、模型数据覆盖和本机端口，并输出 `data/serving/local_pipeline_verification.json`。任何必需检查失败时命令返回非零退出码。
