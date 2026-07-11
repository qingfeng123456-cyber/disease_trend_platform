# API 文档

所有 API 返回统一结构：

```json
{
  "ok": true,
  "status": "ok",
  "data": {},
  "error": null
}
```

错误结构：

```json
{
  "ok": false,
  "status": "error",
  "data": null,
  "error": {"code": "validation_error", "message": "参数说明"}
}
```

## GET /api/health

返回服务状态、数据模式、更新时间和版本。

## GET /api/overview

返回地区数量、日期范围、累计病例、累计死亡、高风险地区、最佳模型、数据完整率和免责声明。

## GET /api/trend

参数：

- `location`：ISO3 代码或地区名。
- `disease`：疾病名称。
- `start_date`：YYYY-MM-DD，可选。
- `end_date`：YYYY-MM-DD，可选。
- `model`：模型名称。

示例：

```bash
curl "http://127.0.0.1:5000/api/trend?location=CHN&disease=COVID-19&model=demo_trend_model"
```

## GET /api/risk-map

返回地区经纬度、风险分、风险等级、增长率和预测病例。

## GET /api/rankings

返回风险、增长率和预测病例三类排名。

## GET /api/model-metrics

返回 MAE、RMSE、R2、MAPE、SMAPE、基线 MAE、特征列表和模型对比。

## GET /api/data-quality

返回记录数、日期范围、缺失率、重复数、负数修订、异常值、关联失败数、来源记录数等。

## GET /api/options

返回可选地区、疾病、模型和日期范围。
