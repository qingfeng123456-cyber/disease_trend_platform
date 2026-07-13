# 实验报告（四）：Flask 后端、API 与前后端交互

## 1. Flask 在项目中的位置

Flask 是本项目的 Web 服务层，负责三件事：

1. 返回首页 HTML、CSS 和 JavaScript 静态资源；
2. 从 `data/serving/*.json` 读取离线流水线结果；
3. 根据疾病、地区、日期和模型参数过滤数据，以统一 JSON API 返回给前端。

Flask **不负责**在线清洗、训练 LSTM 或直接查询 HDFS。正确顺序是先离线生成 Serving JSON，再启动 Flask。这样请求响应快、模型训练失败不会拖垮网页，也便于把数据处理和展示解耦。

## 2. 后端文件结构

```text
src/web/
├─ app.py                         Flask 应用、路由和异常处理
├─ services/
│  └─ data_service.py             Serving JSON 缓存、参数校验、过滤和统计
├─ templates/
│  └─ index.html                  单页仪表盘 HTML
└─ static/
   ├─ css/style.css               页面布局、主题和响应式样式
   └─ js/
      ├─ api.js                   fetch 请求、格式化和时钟
      ├─ app.js                   页面状态、筛选器、并行请求、组件更新
      ├─ charts.js                ECharts option 构造函数
      └─ particles.js             当前只保留时钟初始化，文件名为历史命名
```

通用依赖：

- `src/common/config.py`：从 `config/settings.yaml` 读取 host、port、serving 路径；
- `src/common/exceptions.py`：`ValidationError`、`DataNotReadyError`、`PlatformError`；
- `src/common/logger.py`：日志写入 `logs/platform.log`。

## 3. Flask 应用构建

`src/web/app.py` 创建全局 `Flask(__name__)`，如果安装了 `flask-cors` 则启用 CORS。随后创建一个 `DataService` 实例，并为页面和 API 注册 GET 路由。

启动入口：

```powershell
conda run --no-capture-output -n intership python -m src.web.app
```

默认读取：

- Host：`config/settings.yaml` 的 `web.host`，也可由 `FLASK_HOST` 覆盖；
- Port：默认 5000，也可由 `FLASK_PORT` 覆盖；
- Serving：默认 `data/serving`，Linux 启动脚本可通过 `SERVING_DIR` 指定。

开发服务器适合课程演示，不建议直接暴露到公网生产环境。

## 4. 统一 API 响应格式

成功响应：

```json
{
  "ok": true,
  "status": "ok",
  "data": {},
  "error": null
}
```

失败响应：

```json
{
  "ok": false,
  "status": "error",
  "data": null,
  "error": {
    "code": "validation_error",
    "message": "具体错误说明"
  }
}
```

错误状态：

- 400：疾病、地区、模型或日期参数不合法；
- 503：Serving 文件尚未生成；
- 500：平台内部错误，检查 `logs/platform.log`；
- 未处理异常不会把 Python 堆栈直接返回浏览器。

## 5. API 接口定义

| 方法与路径 | 查询参数 | 返回内容 | 主要 Serving 文件 |
|---|---|---|---|
| `GET /` | 无 | `index.html` | 无 |
| `GET /api/health` | 无 | 服务状态、数据模式、生成时间 | `metadata.json` |
| `GET /api/options` | 无 | 疾病、地区、模型、频率、日期范围 | `options.json` |
| `GET /api/overview` | `disease, location/iso, start_date, end_date` | 顶部 KPI | `overview.json`、趋势/质量数据 |
| `GET /api/trend` | 上述参数加 `model` | 历史值、滚动均值、预测、区间 | `trend.json` |
| `GET /api/predictions` | 上述参数加 `model` | 测试目标、预测、残差 | `predictions.json` |
| `GET /api/risk-map` | `disease` | 各地区经纬度、风险值 | `risk_map.json` |
| `GET /api/rankings` | `disease` | 高风险地区排序 | `rankings.json` |
| `GET /api/model-metrics` | `disease` | 各模型 MAE/RMSE 等 | `model_metrics.json` |
| `GET /api/data-quality` | 无 | 完整率和质量检查 | `data_quality_report.json` |
| `GET /api/weather-correlation` | `disease, location/iso, start_date, end_date` | 同期温度、湿度和病例/发病率散点 | `weather_correlation.json` |
| `GET /api/disease-share` | 无 | 各疾病观测覆盖占比 | `disease_share.json` |
| `GET /api/source-status` | 无 | 各数据源和模型状态 | `source_status.json` |
| `GET /api/who-indicators` | 无 | WHO 80 个指标用途与覆盖摘要 | `who_indicator_summary.json` |
| `GET /api/model-coverage` | 无 | 各疾病训练样本、模型覆盖 | `model_data_coverage.json` |

`location` 与 `iso` 是同义参数，前端目前使用 `location`。日期格式必须能解析为 ISO 日期，且开始日期不能晚于结束日期。

## 6. API 调用示例

获取疾病和日期范围：

```text
http://127.0.0.1:5000/api/options
```

获取中国 COVID LSTM 趋势：

```text
http://127.0.0.1:5000/api/trend?disease=COVID-19&location=CHN&model=local_pytorch_lstm&start_date=2020-01-04&end_date=2025-12-31
```

获取美国流感预测误差：

```text
http://127.0.0.1:5000/api/predictions?disease=Influenza&location=USA&model=local_pytorch_lstm_influenza
```

PowerShell 测试：

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/health
Invoke-RestMethod "http://127.0.0.1:5000/api/options"
Invoke-RestMethod "http://127.0.0.1:5000/api/trend?disease=Tuberculosis&location=CHN&model=naive_last_value"
```

## 7. DataService 设计

`src/web/services/data_service.py` 是 API 和 JSON 文件之间的服务层。

### 7.1 文件缓存

`_read_json` 按文件名缓存解析后的 Python 对象，默认缓存约 30 秒，同时比较文件修改时间。流水线重写 JSON 后，缓存过期或检测到修改便重新读取，无需重启 Flask；浏览器刷新即可看到新数据。

### 7.2 参数规范化

- `_normalize_location`：检查 ISO3 是否存在于当前疾病可用地区；
- `_normalize_disease`：检查疾病名；
- `_normalize_model`：检查模型是否属于该疾病；
- `_parse_optional_date`：解析起止日期；
- `_filter_payload_items`：按疾病、地区和日期统一过滤。

这可以防止前端选择 TB 时仍请求 COVID LSTM，或选择 RSV 时使用没有数据的国家。

### 7.3 趋势服务

`trend()` 执行：

1. 读取可用选项和趋势总表；
2. 使用疾病默认地区、完整日期范围和默认模型补齐缺省参数；
3. 过滤选中疾病/地区/日期；
4. 从记录中的模型预测字典选择当前模型；
5. 返回真实值、移动平均、预测目标日、上下界、增长率、频率和指标说明。

每个疾病默认展示自己的完整清洗日期范围，而不是使用整个项目的统一日期范围。

### 7.4 天气相关服务

`weather_correlation()` 先严格按当前日期筛选同地区同期点；若当前窗口没有匹配点，会返回可用全范围关联并附带说明，而不是显示一个无解释空图。Pearson 相关系数由 `_pearson` 计算。相关不等于因果，网页术语区会提示“代表城市天气”和“探索性相关”。

## 8. 前后端交互流程

页面加载流程：

```text
浏览器 GET /
  -> Flask 渲染 index.html
  -> api.js/app.js/charts.js/style.css
  -> GET /api/options
  -> 填充疾病、地区、日期和模型控件
  -> 根据可用性设置该疾病完整日期范围
  -> Promise.all 并行请求约 10 个 API
  -> app.js 组装 KPI、术语和数据源状态
  -> charts.js 构造 ECharts option
  -> chart.setOption(option, true)
```

点击“刷新”或改变疾病时：

1. `applyDiseaseAvailability` 更换可用地区和模型；
2. `applySeriesDateRange` 使用该疾病/地区的完整起止日期；
3. `selectedParams` 生成 URL 查询参数；
4. 并行重新请求趋势、风险、排行、天气、模型、预测等；
5. 全部成功后一次更新页面，减少图表间状态不一致。

## 9. 页面映射

`index.html` 是单页 Dashboard，没有多个 Flask 页面路由。页面区块和接口映射为：

| 页面区域 | 数据接口 |
|---|---|
| 顶部模式、时间、来源计数 | health/source-status |
| 疾病、地区、日期、模型筛选 | options |
| 最新值、移动平均、死亡/频率、风险、最佳模型、完整率 | overview/model-metrics/data-quality |
| 主趋势和未来预测 | trend |
| 风险地图 | risk-map |
| 移动平均小图 | trend |
| 高风险排行榜 | rankings |
| 温湿度关联 | weather-correlation |
| 模型指标对比 | model-metrics |
| 质量仪表盘 | data-quality |
| 增长率 | trend |
| 疾病覆盖占比 | disease-share |
| 预测误差 | predictions |
| 数据源状态 | source-status |
| 专有名词小字说明 | options + trend + 前端 terminology 字典 |

## 10. 输入数据格式与大文件处理

Flask 输入不是 CSV，而是结构化 JSON。这样避免每个 HTTP 请求都扫描几十 MB 的 CSV。当前 `trend.json` 和 `predictions.json` 较大，但 DataService 通过进程内缓存避免重复磁盘解析。

如果数据规模继续扩大，建议下一阶段将 Serving 改成 SQLite/DuckDB/PostgreSQL 或分疾病、分地区 JSON，并加入分页；不要让浏览器一次接收全部原始观测。当前课程规模使用离线 JSON 便于部署和讲解。

## 11. 安全与部署说明

- `.env`、SSH 密码、Kaggle token 不通过 API 暴露，也不提交 Git。
- API 只读，不提供任意文件路径参数。
- `allow_unknown_host` 在远程配置中默认 false，首次 SSH 应核对主机指纹。
- Flask debug 默认应关闭；公网部署应使用 Waitress/Gunicorn 和反向代理。
- 页面中的“风险”是课程模型指标，不是医疗诊断或官方疫情等级。

Flask 官方文档：

- Quickstart：`https://flask.palletsprojects.com/en/stable/quickstart/`
- API：`https://flask.palletsprojects.com/en/stable/api/`

## 12. 启动与接口验收

```powershell
# 第一步：生成/更新模型和 Serving，完成后自动退出
powershell -ExecutionPolicy Bypass -File .\scripts\run_local_real_pipeline.ps1 -CondaEnv intership -EnableLstm -LstmEpochs 40 -BuildOnly

# 第二步：验证文件和接口前置条件
conda run --no-capture-output -n intership python scripts/verify_local_pipeline.py

# 第三步：启动 Flask
conda run --no-capture-output -n intership python -m src.web.app
```

另一终端验收：

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/health
Invoke-RestMethod http://127.0.0.1:5000/api/options
Invoke-RestMethod "http://127.0.0.1:5000/api/predictions?disease=COVID-19&location=CHN&model=local_pytorch_lstm"
```

最后访问 `http://127.0.0.1:5000`。如果只启动 Flask 而没有先运行流水线，页面会继续展示上一次生成的 JSON，这正是离线 Serving 架构的预期行为。
