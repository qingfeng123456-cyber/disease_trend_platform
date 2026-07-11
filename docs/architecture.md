# 系统架构

## 离线计算链路

```text
Collectors -> data/raw -> HDFS raw -> Spark clean -> silver Parquet
          -> Spark features/statistics -> gold Parquet -> models
          -> data/serving JSON -> Flask -> ECharts
```

## 分层职责

- raw：原始 CSV、JSON、HTML、PDF、Excel，只追加和归档。
- silver：字段统一、类型转换、去重、负数修正、异常标记。
- gold：多源关联、时间序列特征、地区统计、模型训练数据。
- serving：小型 JSON，供 Flask 快速读取。

## 关键约束

- Flask API 不启动 Spark。
- 时间序列按日期切分，不随机打乱。
- `target_t_plus_7` 使用 `lead(target_column, 7)` 构造。
- 风险指数仅为课程项目分析指标。
