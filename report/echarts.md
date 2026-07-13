# 实验报告（五）：ECharts 可视化界面设计与动态渲染

## 1. 设计来源说明

本项目的仪表盘没有复制或套用第三方后台模板。通过 Git 初始版本检查，首个版本已经由项目自身的 `index.html`、`style.css` 和 `charts.js` 构成深色数据大屏，仓库中没有第三方模板名称、模板许可证、模板源码目录或可追溯的模板 URL。

因此“最开始选择了哪些模板”的准确答案是：**没有选择现成页面模板，采用原生 HTML/CSS 网格布局和 ECharts 图表组件自定义实现**。不能为了实验报告好看而虚构“基于某某模板二次开发”。

项目实际使用的第三方前端库是 Apache ECharts 5，HTML 中的 CDN 地址为：

```text
https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js
```

## 2. 参考资料及完整网址

开发和继续维护时可参考以下官方资料：

- Apache ECharts 官网：`https://echarts.apache.org/en/index.html`
- 入门教程：`https://echarts.apache.org/handbook/en/get-started/`
- 官方示例库：`https://echarts.apache.org/examples/en/index.html`
- 配置项手册：`https://echarts.apache.org/en/option.html`
- API 手册：`https://echarts.apache.org/en/api.html`
- 动态数据：`https://echarts.apache.org/handbook/en/how-to/data/dynamic-data/`
- 图表容器与 resize：`https://echarts.apache.org/handbook/en/concepts/chart-size/`
- 下载与引入：`https://echarts.apache.org/handbook/en/basics/download/`
- ECharts GitHub：`https://github.com/apache/echarts`
- jsDelivr 包页面：`https://www.jsdelivr.com/package/npm/echarts`

这些是技术文档和示例参考，不代表项目复制了某一个示例模板。

## 3. 前端文件分工

| 文件 | 作用 |
|---|---|
| `src/web/templates/index.html` | 页面语义结构、筛选栏、KPI、图表容器、免责声明 |
| `src/web/static/css/style.css` | 深色主题、网格、边框、响应式布局、文字层级 |
| `src/web/static/js/api.js` | `fetch` 封装、错误处理、数字/百分比格式化、时钟 |
| `src/web/static/js/app.js` | 全局状态、疾病联动、API 并发、KPI 和术语渲染 |
| `src/web/static/js/charts.js` | 每张图的 ECharts option 构造函数 |
| `src/web/static/js/particles.js` | 历史文件名；当前不绘制粒子，仅配合时钟初始化 |

页面不使用 Vue、React 或 jQuery，减少新手部署依赖。所有动态行为由浏览器原生 JavaScript 和 ECharts 完成。

## 4. 视觉设计原则

### 4.1 信息层级

页面从上到下分为：

1. 标题、技术栈、数据模式、更新时间和时钟；
2. 疾病、地区、开始/结束日期、模型和刷新按钮；
3. 六个关键指标；
4. 主趋势、风险地图、移动平均；
5. 排行、天气关联、模型指标、质量仪表；
6. 增长率、疾病占比、预测误差、数据源状态；
7. 专有名词和口径说明、课程免责声明。

主趋势占据更宽区域，辅助图保持较小尺寸，避免所有图同等抢夺注意力。

### 4.2 色彩语义

- 青色：常规趋势、均值、主要交互；
- 红色：未来预测、高风险和误差警示；
- 绿色：稳定趋势或正常状态；
- 黄色：RMSE、说明或需要注意的数据源；
- 蓝紫：疾病覆盖和质量仪表。

颜色不是唯一编码，图例、标题、标签和小字解释同时表达含义，避免用户把颜色本身误解为官方风险等级。

### 4.3 布局与响应式

CSS 使用 Grid/Flex，而不是绝对定位堆叠。图表容器有稳定高度，筛选控件设置最小宽度和换行规则。窄屏时网格自动变为较少列，文字可以换行，避免图表、标题和说明互相覆盖。

`window.resize` 时调用所有 ECharts 实例的 `resize()`，保证浏览器缩放或窗口变化后重新计算画布。

## 5. 图表及实现函数

`src/web/static/js/charts.js` 为每种图返回独立 option：

| 图表 | 函数 | ECharts 类型 | 展示内容 |
|---|---|---|---|
| 日/周/年趋势和未来预测 | `lineTrendOption` | line + bar + area | 真实观测、滚动均值、预测、上下界 |
| 移动平均 | `avgOption` | line/area | 平滑趋势 |
| 风险地图 | `riskMapOption` | scatter | 经度、纬度、风险、点大小和颜色 |
| 高风险地区排行 | `rankingOption` | horizontal bar | 各地区风险排序 |
| 温湿度关联 | `weatherOption` | scatter + visualMap | 天气与病例/发病率关系 |
| 模型指标对比 | `modelOption` | grouped bar | MAE、RMSE |
| 数据质量 | `qualityOption` | gauge | Serving 完整率 |
| 增长率 | `growthOption` | line/area | 按频率定义的变化率 |
| 疾病覆盖占比 | `shareOption` | donut pie | 各疾病观测占比 |
| 预测误差 | `errorOption` | positive/negative bar | 预测残差随目标日期变化 |

所有图共享 `chartBase()` 的背景透明、网格、坐标轴、tooltip 和字体颜色，减少重复配置并保持风格一致。

## 6. 主趋势图设计

主趋势图同时表达：

- 原始观测：COVID 批次报告使用柱/折线组合以显示零值和峰值；
- 移动平均：青色平滑线；
- 未来预测：红色虚线；
- 置信下界和上界：两条边界或透明区域；
- `forecast_target_date`：预测点绘制在真正目标日，而不是模型发起日。

不同疾病标题动态变化：COVID 显示“日新增病例与未来 7 日”，周频显示“周住院与下一周”，TB 显示“每 10 万人估计发病率与下一年”。避免把所有疾病都写成“日新增病例”。

主趋势图配置 `dataZoom`：

- `inside`：鼠标滚轮/触摸缩放和拖动；
- `slider`：底部可见滑块，左右拖动浏览长时间序列；
- 初始范围使用疾病的全部清洗日期，而不是统一固定到 2025 年末。

## 7. 预测误差图设计

`errorOption(predictions)` 将每个测试目标日期的 `prediction - actual` 画成柱形：

- 正误差与负误差使用不同颜色；
- x 轴为连续目标日期；
- y 轴单位沿用当前疾病指标；
- 与主趋势相同配置 `inside + slider dataZoom`；
- 支持鼠标缩放、拖动和底部滑块左右浏览；
- tooltip 显示日期、真实值、预测值和残差。

这样可以查看误差是否集中在某些波峰、某段报告制度变化或特定年份，而不是只看到一个 MAE 数字。

## 8. 温湿度与病例关联图

`weatherOption` 使用散点图：

- x 轴为代表城市温度；
- y 轴为当前疾病值；
- 颜色/visualMap 表示湿度；
- tooltip 显示日期、地区、温度、湿度和疾病值；
- 标题上方显示温度 Pearson `r`、湿度 Pearson `r` 和匹配样本数 `n`。

后端严格关联 `location_code + date/周/年`。如果用户选中的 COVID 日期在 Open-Meteo 范围外，API 会说明所用回退范围；不会用 2012-2017 天气冒充 2024 年同期天气。

相关系数只表示线性共变，不证明温湿度导致病例变化。页面下方专有名词区对此进行小字说明。

## 9. 动态数据加载

`app.js` 的工作顺序：

1. `initCharts()` 对所有容器执行 `echarts.init`。
2. 请求 `/api/options`，保存到 `state.options`。
3. `fillSelect` 填充疾病、地区和模型。
4. `applyDiseaseAvailability` 根据疾病限制地区与模型。
5. `applySeriesDateRange` 将日期设置为该疾病/地区完整范围。
6. `selectedParams` 生成 URLSearchParams。
7. 使用 `Promise.all` 并行请求趋势、风险、排行、天气、指标、质量、占比、预测和来源等接口。
8. `renderKpis`、`renderSources`、`renderTerminology` 更新 DOM。
9. `setCharts` 调用各 option 函数，再执行 `chart.setOption(option, true)`。

采用并行请求可缩短等待时间；使用统一筛选参数可保证一轮刷新中的图表属于同一疾病和日期上下文。

## 10. 疾病专有名词说明

`app.js` 中的 `diseaseTerminology` 和 `frequencyDescriptions` 按疾病/频率生成解释，例如：

- “估计发病率（每 10 万人）”不是病例总数；
- “周新增住院”是住院入院记录，不等于感染人数；
- “最近观测值”是所选地区最后一条真实来源值；
- “移动平均”用于平滑趋势，不表示新增数据；
- “MAE/RMSE”越小通常越好，但要结合单位和测试时段；
- “风险指数”是课程分析指标，不是官方医疗风险分级；
- “代表城市天气”不是全国平均天气。

这些说明放在筛选/KPI 和图表附近的小字号区域，并通过响应式布局自然换行，避免悬浮层遮挡图表。

## 11. 数据源状态显示

数据源状态卡从 `/api/source-status` 动态生成：

- `ok/正常`：已结构化并进入相应用途；
- `info/说明`：数据保留且可查，但没有可靠地作为模型标签；
- `warn/警告`：缺配置、日期不适用或质量问题需要注意；
- 行数同时区分 Raw 与清洗后记录。

例如 WHO 的 122,169 原始行与 117,492 唯一记录会说明 4,677 条为完全重复副本；历史天气会说明 45,253 小时聚合为 1,887 天。状态卡必须解释变化原因，不能只显示一个让用户误以为大量删除的数字。

## 12. 页面性能与稳定性

- ECharts 实例只初始化一次，刷新时更新 option。
- 大趋势使用 `dataZoom` 控制视窗，不在 DOM 中创建数万个节点。
- API JSON 由 Flask 缓存，浏览器不直接解析 CSV。
- 图表容器固定高度，空数据时显示文字说明而不是坐标轴挤压。
- 对 null/NaN 做前端格式化，避免标签出现 `undefined`。
- `setOption(option, true)` 让疾病切换时清除旧系列，防止不同疾病残留叠加。

## 13. 界面验收清单

1. 首次进入每个疾病时，日期为该疾病完整可用范围。
2. 切换疾病后，地区和模型下拉框同步变化。
3. COVID 主趋势日期连续，批次报告峰值与零值均可见。
4. 主趋势和预测误差都能滚轮缩放、拖动、操作底部滑块。
5. TB/HIV 数值旁显示单位，不能被理解为病例人数。
6. 温湿度图有匹配样本 `n`；无同期数据时有原因说明。
7. 图表标题、图例、坐标轴和小字不重叠。
8. 浏览器缩放和窄屏时所有 ECharts 调用 `resize()`。
9. 数据源卡说明聚合、去重、未入模的原因。
10. 页面底部保留“教学演示，不构成医疗建议”的免责声明。
