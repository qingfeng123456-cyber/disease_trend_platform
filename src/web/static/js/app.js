const chartIds = [
  'trendChart',
  'riskMapChart',
  'avgChart',
  'rankingChart',
  'weatherChart',
  'modelChart',
  'qualityChart',
  'growthChart',
  'shareChart',
  'errorChart'
];

const charts = {};
const state = { options: null, worldMapReady: false };
let worldMapLoadPromise = null;

const diseaseTerminology = {
  'COVID-19': {
    term: '日新增病例与累计病例',
    definition: '日新增病例是来源按日期发布并经清洗后的新增记录；累计病例是截至最后观测日的来源累计值，二者都不是网页访问当日的实时监测值。',
    latestHint: '来源发布的日频病例指标；批次报告可能形成连续零值与集中高峰。'
  },
  Influenza: {
    term: '流感周新增住院入院人数',
    definition: '来源数据按周汇总流感相关的新住院入院人数，反映住院负担；不等同于社区新增感染人数，也不是当前在院人数。',
    latestHint: '周新增住院入院人数，不是流感感染总数。'
  },
  RSV: {
    term: 'RSV 周新增住院入院人数',
    definition: 'RSV 指呼吸道合胞病毒；本页指标是来源按周汇总的新住院入院人数，不等同于社区新增感染人数或当前在院人数。',
    latestHint: '周新增 RSV 相关住院入院人数，不是感染总数。'
  },
  Tuberculosis: {
    term: '结核病估计发病率（每10万人）',
    definition: '表示某年估计新发和复发结核病例数除以人口后换算到每10万人，是年估计率而非病例人数；例如 2.6 表示约每10万人 2.6 例。',
    latestHint: '年度估计率，不是病例总人数或实时报告数。'
  },
  'HIV/AIDS': {
    term: '年度新增 HIV 感染数',
    definition: '表示该年估计新发生的 HIV 感染，不等同于现存 HIV 感染者人数、HIV 患病率或 AIDS 诊断人数。',
    latestHint: '年度估计新增感染，不是现存感染者总数。'
  },
  'COVID-19 Hospital Admissions': {
    term: '新冠周新增住院入院人数',
    definition: '来源数据按周汇总新冠相关的新住院入院人数，反映住院负担；不等同于新冠新增感染人数，也不是当前在院人数。',
    latestHint: '周新增住院入院人数，不是新增感染或当前在院人数。'
  }
};

const frequencyDescriptions = {
  daily: '日频表示每个自然日一条观测',
  weekly: '周频表示每个报告周一条汇总观测',
  annual: '年频表示每个统计年度一条观测'
};

function modelDisplayName(model) {
  const names = {
    naive_last_value: '最近值基线',
    moving_average: '移动平均基线',
    local_sklearn_gbdt: 'GBDT',
    local_pytorch_lstm: 'LSTM'
  };
  if (String(model || '').startsWith('local_pytorch_lstm')) return 'LSTM';
  return names[model] || model || '--';
}

function diseaseProfile(disease, metricLabel) {
  return diseaseTerminology[disease] || {
    term: metricLabel || '当前指标',
    definition: '当前图表保留来源数据的原始统计口径，不同疾病指标不能直接按数值大小比较。',
    latestHint: metricLabel || '当前指标'
  };
}

function renderTerminology(overview, trend) {
  const profile = diseaseProfile(overview.selected_disease, overview.selected_metric_label);
  const frequencyName = { daily: '日频', weekly: '周频', annual: '年频' }[overview.selected_frequency] || '原生频率';
  const frequencyDescription = frequencyDescriptions[overview.selected_frequency] || '按来源原生时间频率保留观测';
  const rollingLabel = trend.rolling_label || overview.selected_rolling_label || '移动平均';
  const horizonLabel = trend.forecast_horizon_label || '下一预测周期';
  const latestDate = overview.latest_date || '--';
  const selectedModel = modelDisplayName(trend.model);
  const items = [
    {
      term: profile.term,
      definition: profile.definition
    },
    {
      term: `${frequencyName}与最新观测`,
      definition: `${frequencyDescription}。“最新”指清洗后序列截至 ${latestDate} 的最后一条记录，不表示今天的实时值。`
    },
    {
      term: `${rollingLabel}与${horizonLabel}`,
      definition: `${rollingLabel}用于平滑已有观测，不是预测；${horizonLabel}由当前所选模型生成。图中参考上下界只是教学波动范围，不是统计置信区间或保证范围。`
    },
    {
      term: `模型与误差（当前：${selectedModel}）`,
      definition: '最近值和移动平均是基线，GBDT 是树模型，LSTM 是序列神经网络。MAE 是最佳模型的主要选择标准；RMSE、R²、MAPE 和 sMAPE 用于辅助诊断。五项指标只在同一疾病内比较。'
    }
  ];
  const list = document.getElementById('terminologyList');
  const nodes = items.map(item => {
    const container = document.createElement('div');
    const term = document.createElement('strong');
    const definition = document.createElement('span');
    container.className = 'terminology-item';
    term.textContent = item.term;
    definition.textContent = item.definition;
    container.append(term, definition);
    return container;
  });
  list.replaceChildren(...nodes);
  document.getElementById('terminologyScope').textContent = [
    overview.selected_disease,
    overview.selected_location,
    frequencyName,
    `数据截至 ${latestDate}`
  ].filter(Boolean).join(' · ');
  const disclaimer = overview.disclaimer || '课程教学与数据工程演示，不构成诊断、医疗建议或官方疫情风险等级。';
  document.getElementById('terminologyDisclaimer').textContent = disclaimer;
  document.getElementById('footerDisclaimer').textContent = disclaimer;
}

function initCharts() {
  if (!window.echarts) {
    setMessage('ECharts CDN 未加载，基础数据仍可通过 API 查看。');
    return;
  }
  chartIds.forEach(id => {
    charts[id] = echarts.init(document.getElementById(id));
  });
}

async function ensureWorldRiskMap() {
  if (!window.echarts) return false;
  if (echarts.getMap?.(WORLD_RISK_MAP_NAME)) return true;
  if (!worldMapLoadPromise) {
    worldMapLoadPromise = fetch('/static/data/world_countries.geojson')
      .then(response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then(geoJson => {
        if (!Array.isArray(geoJson?.features) || !geoJson.features.length) {
          throw new Error('GeoJSON 中没有国家边界');
        }
        geoJson.features.forEach(feature => {
          const properties = feature.properties || (feature.properties = {});
          properties.name = properties.NAME_ZH || properties.NAME || properties.ADMIN || properties.ISO_A3;
        });
        echarts.registerMap(WORLD_RISK_MAP_NAME, geoJson);
        return true;
      })
      .catch(error => {
        console.error('世界地图加载失败', error);
        return false;
      });
  }
  return worldMapLoadPromise;
}

function setMessage(text = '') {
  document.getElementById('message').textContent = text;
}

function fillSelect(id, items, valueKey, labelKey, preferredValue = null) {
  const select = document.getElementById(id);
  select.innerHTML = items.map(item => {
    const value = typeof item === 'string' ? item : item[valueKey];
    const label = id === 'modelSelect'
      ? modelDisplayName(value)
      : (typeof item === 'string' ? item : `${item[labelKey]} ${item[valueKey]}`);
    return `<option value="${value}">${label}</option>`;
  }).join('');
  if (preferredValue && Array.from(select.options).some(option => option.value === preferredValue)) {
    select.value = preferredValue;
  }
}

async function loadOptions() {
  state.options = await apiGet('/api/options');
  fillSelect('diseaseSelect', state.options.diseases || [], 'code', 'name', 'COVID-19');
  applyDiseaseAvailability(true, true);
}

function applyDiseaseAvailability(preferDefaultLocation = false, preferDefaultModel = false) {
  const disease = document.getElementById('diseaseSelect').value;
  const availability = state.options?.availability?.[disease] || {};
  const locationSelect = document.getElementById('locationSelect');
  const currentLocation = locationSelect.value;
  const preferredLocation = preferDefaultLocation ? 'CHN' : currentLocation;
  fillSelect('locationSelect', availability.locations || state.options.locations || [], 'code', 'name', preferredLocation);
  if (!locationSelect.value && locationSelect.options.length) locationSelect.selectedIndex = 0;
  const modelSelect = document.getElementById('modelSelect');
  const currentModel = modelSelect.value;
  const preferredModel = preferDefaultModel
    ? availability.default_model
    : ((availability.models || []).includes(currentModel) ? currentModel : availability.default_model);
  fillSelect('modelSelect', availability.models || state.options.models || [], 'code', 'name', preferredModel);
  applySeriesDateRange();
}

function applySeriesDateRange() {
  const disease = document.getElementById('diseaseSelect').value;
  const location = document.getElementById('locationSelect').value;
  const availability = state.options?.availability?.[disease] || {};
  const range = availability.location_date_ranges?.[location] || {};
  const fullStart = range.full_start || availability.date_range?.start || state.options?.date_range?.start || '';
  const fullEnd = range.full_end || availability.date_range?.end || state.options?.date_range?.end || '';
  const startInput = document.getElementById('startDate');
  const endInput = document.getElementById('endDate');
  startInput.min = fullStart;
  startInput.max = fullEnd;
  endInput.min = fullStart;
  endInput.max = fullEnd;
  startInput.value = range.default_start || fullStart;
  endInput.value = range.default_end || fullEnd;
}

function selectedParams() {
  return {
    disease: document.getElementById('diseaseSelect').value,
    location: document.getElementById('locationSelect').value,
    start_date: document.getElementById('startDate').value,
    end_date: document.getElementById('endDate').value,
    model: document.getElementById('modelSelect').value
  };
}

async function loadWeatherCorrelation(params) {
  const selected = await apiGet('/api/weather-correlation', params);
  if ((selected.items || []).length || !params.location || !params.disease) return selected;

  const fallback = await apiGet('/api/weather-correlation', {
    location: params.location,
    disease: params.disease
  });
  const items = fallback.items || [];
  if (!items.length) return selected;

  const dates = items.map(item => String(item.date || '').slice(0, 10)).filter(Boolean);
  return {
    ...fallback,
    fallback_used: true,
    matched_date_range: fallback.matched_date_range || {
      start: dates[0] || '',
      end: dates[dates.length - 1] || ''
    },
    message: '所选日期窗口没有同期天气，已自动展示该疾病和地区的可匹配天气期。'
  };
}

function renderKpis(overview, metrics, quality) {
  document.getElementById('dataMode').textContent = `数据模式：${overview.data_mode || '--'}`;
  document.getElementById('lastUpdate').textContent = `更新时间：${overview.last_update || '--'}`;
  document.getElementById('demoBadge').classList.toggle('active', Boolean(overview.demo_mode));
  const metricLabel = overview.selected_metric_label || '日新增病例';
  const frequencyNames = { daily: '日频', weekly: '周频', annual: '年频' };
  const isCaseSeries = overview.selected_metric === 'new_cases';
  const metricDigits = overview.selected_metric === 'incidence_per_100k' ? 1 : 0;
  const profile = diseaseProfile(overview.selected_disease, metricLabel);
  document.getElementById('kpiCasesLabel').textContent = isCaseSeries ? '累计病例' : '最新观测值';
  document.getElementById('kpiCases').textContent = fmtNumber(
    isCaseSeries ? overview.current_total_cases : overview.current_new_cases,
    metricDigits
  );
  document.getElementById('kpiCasesHint').textContent = isCaseSeries
    ? `来源截至 ${overview.latest_date || '--'} 的累计值，非实时值`
    : profile.latestHint;
  document.getElementById('kpiNewCasesLabel').textContent = overview.selected_rolling_label || '当前指标';
  document.getElementById('kpiNewCases').textContent = fmtNumber(
    overview.current_rolling_value ?? overview.current_new_cases,
    metricDigits
  );
  const rollingValue = overview.current_rolling_value ?? overview.current_new_cases;
  const trailingZeroPeriods = Number(overview.trailing_zero_periods || 0);
  const rollingWindowIsZero = Number(rollingValue) === 0 && trailingZeroPeriods > 0;
  const latestNonzeroText = overview.last_nonzero_date ? `，最近非零报告 ${overview.last_nonzero_date}` : '';
  const rollingHint = rollingWindowIsZero
    ? `${frequencyNames[overview.selected_frequency] || '--'} · ${overview.latest_date || '--'} · 当前平滑窗口来源均为0${latestNonzeroText}`
    : `${frequencyNames[overview.selected_frequency] || '--'} · ${overview.latest_date || '--'} · 平滑已有观测`;
  document.getElementById('kpiNewCasesHint').textContent = rollingHint;
  document.getElementById('kpiNewCasesHint').title = overview.reporting_stale
    ? `来源已连续 ${trailingZeroPeriods} 个观测周期为0；这可能表示停止或批量上报，不等于真实没有病例。`
    : rollingHint;
  document.getElementById('kpiDeathsLabel').textContent = overview.current_total_deaths == null ? '数据频率' : '累计/年度死亡';
  document.getElementById('kpiDeaths').textContent = overview.current_total_deaths == null ? (frequencyNames[overview.selected_frequency] || '--') : fmtNumber(overview.current_total_deaths);
  document.getElementById('kpiDeathsHint').textContent = overview.current_total_deaths == null
    ? '当前序列的原生时间频率'
    : `${overview.selected_frequency === 'daily' ? '来源累计' : '同年度'}死亡辅助指标，不是当前预测目标`;
  document.getElementById('kpiHighRisk').textContent = fmtNumber(overview.high_risk_regions);
<<<<<<< HEAD
  document.getElementById('kpiHighRiskHint').textContent = overview.risk_comparable === false
    ? `仅 ${overview.risk_comparison_regions || 0} 个地区，无法进行同病种横向分级`
    : `${overview.risk_comparison_regions || 0} 个地区的0-100相对分，非官方预警等级`;
=======
  document.getElementById('kpiHighRiskHint').textContent = '仅供项目评分，非官方预警等级';
>>>>>>> f67094a0affde5abcc1024ff0a550042455f473a
  const bestModelText = `${modelDisplayName(overview.best_model)} / ${fmtNumber(metrics.mae, 2)}`;
  document.getElementById('kpiBestModel').textContent = bestModelText;
  document.getElementById('kpiBestModel').title = `${overview.best_model || '--'} / MAE ${fmtNumber(metrics.mae, 2)}`;
  document.getElementById('kpiBestModelHint').textContent = '同病种测试集 MAE，越低越好';
  document.getElementById('kpiQuality').textContent = fmtPercent(overview.data_completeness ?? 0);
  document.getElementById('kpiQualityHint').textContent = '流水线关键字段完整率，不代表所有可选字段';
  if (quality?.warnings?.length) setMessage(quality.warnings[0]);
}

function renderSources(sourceStatus) {
  const items = sourceStatus.items || [];
  const statusLabels = {
    ok: '正常',
    info: '说明',
    not_configured: '未配置',
    excluded: '未入模',
    warn: '需检查',
    pending: '处理中'
  };
  const okCount = items.filter(item => item.status === 'ok').length;
  const warnCount = items.filter(item => item.status === 'warn').length;
  const noticeCount = items.filter(item => ['info', 'not_configured', 'excluded'].includes(item.status)).length;
  document.getElementById('sourceHealth').textContent = `数据源：${okCount} 正常 · ${noticeCount} 说明 · ${warnCount} 警告`;
  document.getElementById('sourceList').innerHTML = items.map(item => {
    const status = statusLabels[item.status] ? item.status : 'warn';
    const rowText = item.raw_rows != null && item.raw_rows !== item.rows
      ? `清洗 ${fmtNumber(item.rows)} / 原始 ${fmtNumber(item.raw_rows)} 行`
      : `${fmtNumber(item.rows)} 行`;
    return `
    <div class="source-item">
      <strong title="${item.name}">${item.name}</strong>
      <span class="${status}">${statusLabels[status]}</span>
      <span>更新：${item.updated_at || '--'}</span>
      <span>${rowText}</span>
      ${item.detail ? `<span class="source-detail">${item.detail}</span>` : ''}
    </div>
  `;
  }).join('');
}

function setCharts({ trend, risk, rankings, weather, metrics, quality, share, predictions }) {
  if (!window.echarts) return;
  const reportingSuffix = trend.reporting_profile?.sparse_reporting ? '（日期连续，批次报告）' : '';
  const trendPanelTitle = document.getElementById('trendPanelTitle');
  trendPanelTitle.textContent = `${trend.metric_label || '指标'}与${trend.forecast_horizon_label || '预测'}${reportingSuffix}`;
  trendPanelTitle.title = [trend.source, trend.reporting_profile?.note].filter(Boolean).join('；');
  document.getElementById('trendPanelNote').textContent = trend.reporting_profile?.note
    || '观测值和移动平均来自历史数据，虚线为所选模型对下一目标周期的预测。';
  document.getElementById('averagePanelTitle').textContent = trend.rolling_label || '移动平均';
  document.getElementById('averagePanelNote').textContent = `${trend.rolling_label || '移动平均'}仅用于平滑已有观测，不是新增数据或未来预测。`;
  document.getElementById('weatherPanelTitle').textContent = `温湿度与${trend.metric_label || '指标'}关联`;
  document.getElementById('weatherPanelNote').textContent = weather.fallback_used
    ? '所选窗口无同期天气，图中已回退到可匹配期；r 表示线性相关，相关不代表因果。'
    : 'r 为皮尔逊线性相关系数，n 为匹配样本数；相关不代表因果。';
  document.getElementById('growthPanelTitle').textContent = `${trend.metric_label || '指标'}增长率`;
  const periodName = { daily: '日', weekly: '周', annual: '年' }[trend.frequency] || '原生周期';
  document.getElementById('growthPanelNote').textContent = `按相邻${periodName}度观测计算变化率；不同频率之间不能直接比较。`;
  charts.trendChart.setOption(lineTrendOption(trend), true);
  charts.riskMapChart.setOption(riskMapOption(risk), true);
  charts.avgChart.setOption(avgOption(trend), true);
  charts.rankingChart.setOption(rankingOption(rankings), true);
  charts.weatherChart.setOption(weatherOption(weather), true);
  charts.modelChart.setOption(modelOption(metrics), true);
  charts.qualityChart.setOption(qualityOption(quality), true);
  charts.growthChart.setOption(growthOption(trend), true);
  charts.shareChart.setOption(shareOption(share), true);
  charts.errorChart.setOption(errorOption(predictions), true);
  window.requestAnimationFrame(() => {
    Object.values(charts).forEach(chart => chart.resize());
  });
}

async function refreshDashboard() {
  const button = document.getElementById('refreshBtn');
  button.disabled = true;
  setMessage('正在加载数据...');
  try {
    const params = selectedParams();
    const [overview, trend, risk, rankings, weather, metrics, quality, share, predictions, sources] = await Promise.all([
      apiGet('/api/overview', params),
      apiGet('/api/trend', params),
      apiGet('/api/risk-map', params),
      apiGet('/api/rankings', params),
      loadWeatherCorrelation(params),
      apiGet('/api/model-metrics', { disease: params.disease }),
      apiGet('/api/data-quality'),
      apiGet('/api/disease-share'),
      apiGet('/api/predictions', params),
      apiGet('/api/source-status')
    ]);
    renderKpis(overview, metrics, quality);
    renderTerminology(overview, trend);
    renderSources(sources);
    setCharts({ trend, risk, rankings, weather, metrics, quality, share, predictions });
    if (!quality?.warnings?.length) setMessage('');
  } catch (error) {
    console.error(error);
    setMessage(`加载失败：${error.message}`);
  } finally {
    button.disabled = false;
  }
}

async function bootstrap() {
  startClock();
  initCharts();
  state.worldMapReady = await ensureWorldRiskMap();
  await loadOptions();
  await refreshDashboard();
  document.getElementById('diseaseSelect').addEventListener('change', async () => {
    applyDiseaseAvailability(false, true);
    await refreshDashboard();
  });
  document.getElementById('locationSelect').addEventListener('change', async () => {
    applySeriesDateRange();
    await refreshDashboard();
  });
  ['startDate', 'endDate', 'modelSelect'].forEach(id => {
    document.getElementById(id).addEventListener('change', refreshDashboard);
  });
  document.getElementById('refreshBtn').addEventListener('click', refreshDashboard);
}

window.addEventListener('resize', () => Object.values(charts).forEach(chart => chart.resize()));
bootstrap().catch(error => {
  console.error(error);
  setMessage(`初始化失败：${error.message}`);
});
