# 传染病趋势预测系统完整实施方案

## 一、先把题目做成什么样

根据题目要求，系统应面向疾控、卫生健康部门或医疗机构，整合历史疫情、人口、气象、疫苗接种等多源信息，完成趋势统计、短期预测、风险分级和可视化。

对于五名纯新手，最合理的目标不是“做一个真正能用于疾控决策的系统”，而是完成一个**数据链路完整、技术点覆盖充分、演示效果好、结论不过度夸张**的课程项目。

推荐题目名称：

> **基于 Hadoop、Spark 与机器学习的多源传染病趋势分析与风险预警可视化平台**

建议采用“双层数据”方案：

- **模型主线**：全球/国家级日频 COVID-19 或其他可获得的结构化疫情数据，用于演示大规模清洗、关联和 7 日预测；
- **中国专题**：中国疾控中心法定传染病月报、流感周报、急性呼吸道传染病哨点监测，用于展示中国疫情概览和专题分析；
- **辅助变量**：历史气象、人口、疫苗/健康指标。

这样既容易获得足量数据，也能覆盖题目中的“中国疾控场景”。

---

## 二、五人分工

### 总原则

每个人都有一个主责模块和一个互审模块，避免某个人请假后项目完全停摆。所有人都必须会：拉取 Git、运行一次采集脚本、运行一次 Spark 作业、启动网页。

| 成员 | 主责 | 具体交付物 | 互审对象 |
|---|---|---|---|
| 1号：组长/数据源负责人 | 需求拆解、进度、数据采集 | 数据源清单、采集脚本、原始数据说明、每日站会记录 | 互审前端展示的数据是否真实 |
| 2号：数据工程负责人 | HDFS、Spark ETL、Hive/Parquet | HDFS 分层目录、清洗作业、统一字段、数据质量报告 | 互审采集脚本与原始字段 |
| 3号：算法负责人 | 特征工程、基线模型、评估 | ARIMA/GBT 模型、时间切分、指标、预测结果、模型说明 | 互审后端接口字段 |
| 4号：后端与部署负责人 | Flask API、任务脚本、Linux 部署 | API、日志、启动脚本、服务部署、接口文档 | 互审 Spark 输出与网页接口 |
| 5号：前端与文档负责人 | ECharts 大屏、交互、答辩材料 | 可视化页面、UI、演示视频、PPT/说明书截图 | 互审算法图表是否误导 |

### 每个人第一周必须完成的最低任务

- 1号：下载一份 CSV，并保存采集时间和来源地址；
- 2号：把 CSV 上传到 HDFS，再用 Spark 读出来；
- 3号：用 Pandas 画一条按日期变化的病例曲线；
- 4号：写一个 `/api/health` 返回 JSON 的 Flask 接口；
- 5号：用 ECharts 画一条静态折线图。

第二周再把五条线连起来。

---

## 三、数据从哪里来

### 3.1 核心数据源（建议必须做）

| 数据源 | 数据内容 | 获取方式 | 用途 | 难度 |
|---|---|---|---|---|
| 中国疾控中心健康数据 | 全国法定传染病月度情况、流感周报、急性呼吸道传染病哨点监测 | 低频抓取列表页和详情页；优先下载附件 | 中国专题、病种排行、周/月趋势 | 中 |
| WHO Global Health Observatory | 1000+ 健康指标，国家/年份维度 | OData API | 健康指标、疫苗、疾病负担补充 | 中 |
| OWID COVID 数据目录 | 国家-日期级疫情相关数据 | 直接下载 CSV | 日频模型主数据 | 低 |
| Open-Meteo Historical API | 温度、湿度、降水、风速等历史天气 | API，按地点和年份分块 | 气象特征；可扩充到百万级 | 低 |
| World Bank Indicators API | 人口、城市化、GDP、卫生资源等 | API | 人口归一化、社会经济辅助变量 | 低 |

推荐入口：

- 中国疾控中心健康数据：https://www.chinacdc.cn/jksj/
- 中国流感监测周报：https://www.chinacdc.cn/jksj/jksj04_14249/
- 急性呼吸道传染病哨点监测：https://www.chinacdc.cn/jksj/jksj04_14275/
- WHO GHO OData API：https://www.who.int/data/gho/info/gho-odata-api
- OWID COVID 最新目录 CSV：https://catalog.ourworldindata.org/garden/covid/latest/compact/compact.csv
- Open-Meteo 历史天气：https://open-meteo.com/en/docs/historical-weather-api
- World Bank Indicators API：https://datahelpdesk.worldbank.org/knowledgebase/articles/889392-about-the-indicators-api-documentation

### 3.2 “数据量要多”应该怎样做

不要通过重复复制同一份 CSV 来伪造大数据。正确做法是扩展**空间范围、时间范围、时间粒度和变量数**。

推荐三档：

#### 入门档

- 20 个国家；
- 2020 至今的日频疫情；
- 每个国家首都的日频天气；
- 人口指标。

约几十万行，足以跑通。

#### 标准档

- 150+ 国家；
- 日频疫情；
- 150+ 地点的小时级天气，Spark 再聚合为日频；
- 人口、城市化、卫生资源等 5～10 个年度指标。

约千万行，HDFS/Spark 的价值更明显。

#### 挑战档

- 中国 31 个省会或 300 个地级市的小时级历史天气；
- 10 年以上时间范围；
- 中国疾控月报/周报、WHO 指标、人口等关联；
- 生成多层级城市/省份/国家聚合表。

### 3.3 不建议作为主数据源

- 百度指数、微信指数、微博：接口不稳定、登录/反爬严格、合规复杂；
- 爬取医院患者信息：涉及隐私，禁止；
- 随机 Kaggle 数据：可做备用，但答辩时权威性不如官方源；
- 新闻正文大规模抓取：版权与清洗成本高，最多做可选舆情模块。

---

## 四、统一数据模型

多源数据最困难的地方不是模型，而是字段不统一。建议先定义“标准表”，所有数据清洗后都映射到这些字段。

### 4.1 疫情事实表 `fact_epidemic_daily`

| 字段 | 类型 | 示例 | 说明 |
|---|---|---|---|
| date | date | 2026-06-01 | 统计日期 |
| iso_code | string | CHN | 国家代码 |
| region_code | string | CN-SC | 可选省份代码 |
| disease | string | COVID-19 | 病种标准名 |
| new_cases | double | 1234 | 新增病例 |
| new_deaths | double | 12 | 新增死亡 |
| cases_7d_avg | double | 1100 | 7日均值 |
| source | string | OWID/ChinaCDC | 来源 |
| collected_at | timestamp | ... | 采集时间 |

### 4.2 气象表 `fact_weather_daily`

| 字段 | 类型 | 说明 |
|---|---|---|
| date | date | 日期 |
| iso_code / region_code | string | 地域 |
| temp_mean | double | 平均温度 |
| temp_min / temp_max | double | 最低/最高温度 |
| humidity_mean | double | 平均相对湿度 |
| precipitation_sum | double | 降水量 |
| wind_speed_mean | double | 风速 |

### 4.3 人口与社会经济表 `dim_region_yearly`

| 字段 | 类型 | 说明 |
|---|---|---|
| year | int | 年份 |
| iso_code | string | 国家代码 |
| population | long | 人口 |
| urban_rate | double | 城镇化率，可选 |
| hospital_beds | double | 每千人床位，可选 |
| gdp_per_capita | double | 人均 GDP，可选 |

### 4.4 模型特征表 `feature_epidemic_forecast`

建议字段：

```text
iso_code, date, disease,
new_cases,
lag_1, lag_7, lag_14, lag_21,
rolling_mean_7, rolling_mean_14, rolling_std_7,
trend_7, growth_rate_7,
temp_mean, humidity_mean, precipitation_sum,
population, cases_per_million,
month_sin, month_cos, dayofweek,
label_t_plus_7
```

---

## 五、数据清洗规则

### 5.1 通用规则

1. 保留原始文件，永远不要直接改 raw；
2. 每次采集记录来源、采集时间、HTTP 状态和文件哈希；
3. 日期统一为 `yyyy-MM-dd`；
4. 地区统一为 ISO 代码或统一字典；
5. 病种建立别名字典，例如“新冠肺炎”“新型冠状病毒感染”“COVID-19”统一；
6. 数值字段去除逗号、百分号、中文单位后再转换；
7. 不把缺失值全部粗暴填 0：缺失、确实为 0、未报告是三种含义；
8. 检测负数、累计值倒退、突增、重复上报；
9. 保存清洗前后行数、空值率、异常数；
10. 所有预测特征只能使用预测日期以前的信息。

### 5.2 重复数据

推荐主键：

```text
source + disease + iso_code + region_code + date
```

同一主键重复时：

- 来源更新时间更晚的记录优先；
- 如果数值冲突，保留两份到异常表，不要静默覆盖；
- 记录 `is_revised` 和 `revision_time`。

### 5.3 异常值

先标记，不要直接删除：

- `new_cases < 0`；
- 单日数值超过过去 28 天中位数的 10 倍；
- 累计病例突然下降；
- 连续大量 0 后突然集中补报。

可生成字段：`quality_flag = normal / missing / revised / outlier / backlog`。

### 5.4 中国疾控网页的清洗策略

中国疾控页面可能出现 HTML 表格、附件、正文数字等不同形式。正确流程：

1. 爬虫先完整保存 HTML、标题、发布日期和附件 URL；
2. 统计页面结构类型；
3. 每种结构写一个解析器；
4. 无法可靠解析的记录进入 `manual_review.csv`；
5. PDF 中如果是文本表格，优先 `pdfplumber`；扫描件才考虑 OCR；
6. 解析结果抽样 20 页人工核对。

---

## 六、Hadoop 与 Spark 怎样协调

### 6.1 HDFS 分层

```text
/disease_platform/
├── raw/                 # 原始文件，只追加，不覆盖
│   ├── owid/
│   ├── china_cdc/
│   ├── open_meteo/
│   └── world_bank/
├── bronze/              # 基础解析、字段类型转换
├── silver/              # 去重、标准化、关联字典、质量标记
├── gold/                # 面向分析的宽表、聚合表、模型特征
├── models/              # Spark ML 模型
└── serving/             # 给 Flask/网页使用的小型结果
```

### 6.2 为什么原始 CSV 后续要转 Parquet

- CSV 没有可靠类型信息；
- Parquet 列式存储，读取少量列更快；
- 支持压缩和分区裁剪；
- Spark/Hive 使用更方便。

建议 gold 表按 `disease`、`year` 分区：

```text
/gold/features/disease=COVID-19/year=2025/part-....parquet
```

### 6.3 Spark 负责什么

- 批量读取多个 CSV/JSON；
- 去重、字段转换；
- 按国家/日期关联疫情、天气和人口；
- 窗口函数计算 lag、滚动均值、增长率；
- 分组统计；
- MLlib 训练 GBT/随机森林/聚类模型；
- 导出前端使用的聚合 JSON。

### 6.4 Pandas 负责什么

- 小样本快速检查；
- 单个页面解析调试；
- 画图和模型原型；
- ARIMA 等单序列模型；
- 不要用 Pandas 一次读取千万行小时级天气。

### 6.5 Hive 是否必须

不是必须。课程要求若明确出现 Hive，可以为 silver/gold 的 Parquet 创建外部表；否则先用 Spark SQL 即可。工程提供了 `hive/schema.sql` 示例。

---

## 七、模型方案

### 7.1 不要先做 LSTM

先做三个层级：

1. **朴素基线**：未来 7 天等于最近 7 天均值；
2. **ARIMA/SARIMAX**：单地区单病种时间序列；
3. **Spark GBT 回归**：使用 lag、滚动统计、气象、人口等特征。

三者跑通以后再加 LSTM。答辩中“复杂模型不一定更好”本身就是有价值的结论。

### 7.2 预测目标

推荐预测：

```text
第 t 天可获得的数据 -> 第 t+7 天新增病例/7日均值
```

也可以输出未来 7 日累计值，但必须清楚写出标签定义。

### 7.3 时间切分

禁止 `train_test_split(shuffle=True)`。

例如：

```text
训练集：最早日期 ~ 2024-12-31
验证集：2025-01-01 ~ 2025-06-30
测试集：2025-07-01 ~ 最新可用日期
```

若不同数据源更新时间不同，可按数据实际时间动态切 70%/15%/15%。

### 7.4 评价指标

- MAE：容易解释；
- RMSE：对大误差更敏感；
- sMAPE：适合不同量级地区比较，但接近 0 时需谨慎；
- 峰值日期误差；
- 趋势方向准确率；
- 与“最近 7 日均值”基线比较。

### 7.5 风险分级

不要假装是官方风险等级。命名为“教学模型风险指数”。例如：

```text
risk_score =
  0.45 * 预测每百万人病例分位数
+ 0.25 * 近7日增长率分位数
+ 0.20 * 模型异常分数
+ 0.10 * 数据质量惩罚
```

按分位数分成低、中、较高、高四档，并在前端写出规则。

### 7.6 聚类模块

使用 KMeans 对地区按以下字段聚类：

```text
cases_per_million_7d,
growth_rate_7d,
forecast_per_million_7d,
temp_mean,
humidity_mean,
population_density
```

聚类结果叫“相似传播特征组”，不要直接称为官方高风险区域。

---

## 八、Flask API 设计

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/health` | 服务健康检查 |
| GET | `/api/overview` | 总览卡片 |
| GET | `/api/trend?iso=CHN` | 历史与预测趋势 |
| GET | `/api/risk-map` | 地区风险和排名 |
| GET | `/api/model-metrics` | 模型评价 |
| GET | `/api/source-status` | 数据源更新时间和质量 |

不要让 Flask 每次请求都启动 Spark。Spark 是离线批处理，结果先导出为 Parquet/JSON/MySQL；Flask 只读轻量结果。

---

## 九、炫酷 HTML 大屏设计

推荐视觉：深蓝黑背景、青蓝色主色、橙红风险强调色、半透明玻璃面板、细网格背景。

页面布局：

```text
顶部：项目标题 + 数据更新时间 + 当前时间
左上：累计地区数、最新日期、模型 MAE、有效记录数
中间：世界/中国风险地图
右上：高风险地区排名
左下：历史 + 预测折线，含置信区间
中下：日历热力图/病种趋势
右下：影响因素雷达图 + 数据源状态
底部：免责声明
```

适合的 ECharts 图：

- 地图着色；
- 历史实线 + 预测虚线；
- 置信区间带；
- 横向排名条形图；
- 日历热力图；
- 雷达图；
- 仪表盘或环图显示数据质量；
- 动态数字卡片。

不建议堆太多 3D 柱状图，容易遮挡且信息表达差。

工程中的 `src/web` 已给出一套可运行页面。地图脚本使用 CDN；若服务器无法访问外网，应将 ECharts 与地图 GeoJSON 下载到 `static/vendor` 和 `static/data`。

---

## 十、项目目录

```text
disease_trend_platform/
├── README.md
├── requirements.txt
├── .env.example
├── config/
│   ├── settings.yaml
│   ├── locations.csv
│   └── disease_aliases.json
├── scripts/
│   ├── init_hdfs.sh
│   ├── upload_raw_to_hdfs.sh
│   ├── run_pipeline.sh
│   └── start_web.sh
├── src/
│   ├── common/
│   │   ├── config.py
│   │   └── http.py
│   ├── collectors/
│   │   ├── owid_covid.py
│   │   ├── world_bank.py
│   │   ├── open_meteo.py
│   │   ├── china_cdc.py
│   │   └── run_all.py
│   ├── spark_jobs/
│   │   ├── clean_epidemic.py
│   │   ├── clean_weather.py
│   │   ├── build_features.py
│   │   ├── train_gbt.py
│   │   └── export_dashboard.py
│   ├── models/
│   │   ├── arima_baseline.py
│   │   └── lstm_optional.py
│   └── web/
│       ├── app.py
│       ├── templates/index.html
│       └── static/
├── hive/schema.sql
├── data/
│   ├── raw/
│   ├── serving/
│   └── sample/
├── logs/
└── tests/
```

---

## 十一、本机 PyCharm + Xshell + Ubuntu 的工作方式

### 推荐方式 A：代码放服务器，PyCharm 用 SFTP/SSH 解释器

1. 在服务器创建项目目录并初始化 Git；
2. PyCharm 配置 SSH Interpreter；
3. 配置 Deployment/SFTP 自动上传；
4. 数据和 Spark 作业在 Ubuntu 上执行；
5. 本机浏览器通过 SSH 端口转发访问 Flask。

### 推荐方式 B：本机写代码，Git 推送，服务器拉取

```bash
# 本机
 git add .
 git commit -m "add spark feature job"
 git push

# 服务器
 git pull
 spark-submit src/spark_jobs/build_features.py
```

不要通过 QQ/微信反复传 zip 覆盖代码。

### Git 分支建议

```text
main        可演示版本
feature/data
feature/spark
feature/model
feature/backend
feature/frontend
```

每天至少一次合并，避免最后一天出现五套互不兼容代码。

---

## 十二、建议实施顺序（四周版）

### 第 1 周：跑通最小链路

- 确认 Hadoop/Spark 正常；
- 下载 OWID CSV；
- 上传 HDFS；
- Spark 读取并输出 Parquet；
- Flask 返回样例 JSON；
- ECharts 显示样例折线。

验收：网页上能显示一条来自真实 CSV 的趋势。

### 第 2 周：多源关联

- Open-Meteo 和 World Bank 采集；
- 统一地区代码；
- Spark 计算 lag/rolling；
- 数据质量报告；
- 中国疾控原始页面采集。

验收：gold 特征表可查询，字段说明完整。

### 第 3 周：模型和风险分级

- 朴素基线；
- ARIMA；
- Spark GBT；
- 时间切分与指标；
- 风险指数与排名。

验收：至少两个模型对比，测试集指标可复现。

### 第 4 周：大屏、部署和答辩

- 接口和前端联调；
- 地图、预测、排名、数据源状态；
- 异常处理和日志；
- 录制演示；
- 整理报告、PPT、分工和 Git 提交记录。

---

## 十三、可直接交给 AI 的提示词

### 13.1 拿到原始文件后生成清洗代码

```text
你是数据工程师。下面是我从【数据源名称】下载的原始文件字段、前50行、空值统计和异常样例。
目标是将它清洗为以下标准字段：date、iso_code、region_code、disease、new_cases、new_deaths、source、collected_at。

要求：
1. 先分析每个原始字段含义，不确定之处明确标注，不要猜；
2. 给出数据质量问题清单；
3. 使用 PySpark DataFrame API 编写清洗代码；
4. 日期解析失败、负数、重复主键、累计值倒退分别输出到 quarantine 表；
5. 不得随机填充缺失值；
6. 输出 Parquet，按 disease 和 year 分区；
7. 给出输入输出行数、空值率、重复数的统计代码；
8. 代码必须可以由 spark-submit 运行，参数使用 argparse；
9. 最后给出5条人工抽样核对方法。

原始字段和样例：
【粘贴 df.printSchema()、df.show(50, truncate=False)、空值统计】
```

### 13.2 中国疾控页面解析器

```text
我已合法、低频地保存了一批中国疾控中心公开页面的 HTML，不需要你写绕过反爬代码。
请根据下面三种 HTML 样例，设计稳定的解析器，将标题、发布日期、统计周期、病种、发病数、死亡数、附件URL解析为结构化记录。

要求：
1. 先判断页面存在几种结构模板；
2. 每个模板单独写解析函数；
3. 不能可靠解析的字段返回 None，并写入 parse_warning；
4. 不使用仅针对某一个页面位置的脆弱 CSS 选择器；
5. 数值支持中文逗号、空格、百分号；
6. 输出单元测试；
7. 给出至少10条人工核验规则；
8. 不要通过页面正文推断未明确给出的数字。

样例HTML：
【粘贴三个典型页面片段】
```

### 13.3 让 AI 检查时间序列数据泄漏

```text
请审查下面的 PySpark 特征工程和模型代码是否存在时间序列数据泄漏。
重点检查：
- rolling window 是否包含当前标签或未来数据；
- lead/lag 方向是否写反；
- 气象和人口数据发布时间是否晚于预测时点；
- 标准化器是否在全量数据上 fit；
- 是否随机划分训练测试集；
- 是否在测试集上选择超参数；
- 缺失值填充是否使用了未来值。

逐行指出问题，给出修正版代码，并用一个10行的小型时间序列例子证明修复后没有未来信息进入特征。
代码：
【粘贴代码】
```

### 13.4 让 AI 根据接口生成前端

```text
请基于以下 Flask API 返回样例，生成一个 1920x1080 深色疾控数据大屏。
技术仅使用 HTML、CSS、原生 JavaScript、ECharts 5，不使用前端框架。

要求：
1. 顶部标题、数据更新时间和时钟；
2. 4个KPI卡片；
3. 地区风险地图；
4. 历史实线、预测虚线和置信区间；
5. 高风险地区排名；
6. 日历热力图；
7. 数据源状态；
8. 页面宽度自适应；
9. API失败时显示错误状态，不允许整页白屏；
10. 明确显示“教学演示，不构成公共卫生决策或医疗建议”。
11. 不伪造接口不存在的字段。

API样例：
【粘贴真实JSON】
```

### 13.5 报错修复提示词

```text
我在 Ubuntu 上通过 spark-submit 运行项目。请只根据我提供的版本信息、完整命令、完整报错和相关代码定位问题，不要凭空猜测。
先给出最可能的3个原因及证据，再给最小修改方案；每次只改一个变量，并给验证命令。

版本：
python3 --version: ...
java -version: ...
hadoop version: ...
spark-submit --version: ...

执行命令：...
完整报错：...
相关代码：...
HDFS输入路径及 hdfs dfs -ls 输出：...
```

---

## 十四、答辩时重点展示什么

1. 数据来源权威、可追溯；
2. raw/silver/gold 分层；
3. Spark 窗口函数和多源关联；
4. 时间序列切分防止数据泄漏；
5. 模型与朴素基线比较；
6. 风险分级规则透明；
7. 网页不是静态假数据，而是读取 Flask API；
8. 数据源更新时间和质量状态可见；
9. Git 提交记录证明五人协作；
10. 清楚说明局限：上报延迟、数据修订、不同国家定义差异、预测不能替代专家判断。

---

## 十五、最终验收清单

- [ ] 公开数据源和许可证/使用说明已记录；
- [ ] raw 数据可追溯且未被覆盖；
- [ ] HDFS 目录截图；
- [ ] Spark 作业日志和运行时间；
- [ ] silver/gold 表字段说明；
- [ ] 数据质量统计；
- [ ] 时间切分说明；
- [ ] 至少两个模型和朴素基线；
- [ ] MAE/RMSE/sMAPE；
- [ ] Flask API 文档；
- [ ] ECharts 大屏；
- [ ] 风险等级规则；
- [ ] 免责声明；
- [ ] 五人 Git 提交与分工；
- [ ] 一键运行或清晰启动脚本；
- [ ] 演示视频和故障备用截图。
