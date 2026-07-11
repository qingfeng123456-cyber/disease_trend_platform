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
const state = { options: null };

function initCharts() {
  if (!window.echarts) {
    setMessage('ECharts CDN 未加载，基础数据仍可通过 API 查看。');
    return;
  }
  chartIds.forEach(id => {
    charts[id] = echarts.init(document.getElementById(id));
  });
}

function setMessage(text = '') {
  document.getElementById('message').textContent = text;
}

function fillSelect(id, items, valueKey, labelKey, preferredValue = null) {
  const select = document.getElementById(id);
  select.innerHTML = items.map(item => {
    const value = typeof item === 'string' ? item : item[valueKey];
    const label = typeof item === 'string' ? item : `${item[labelKey]} ${item[valueKey]}`;
    return `<option value="${value}">${label}</option>`;
  }).join('');
  if (preferredValue && Array.from(select.options).some(option => option.value === preferredValue)) {
    select.value = preferredValue;
  }
}

async function loadOptions() {
  state.options = await apiGet('/api/options');
  fillSelect('diseaseSelect', state.options.diseases || [], 'code', 'name', 'COVID-19');
  applyDiseaseAvailability(true);
}

function applyDiseaseAvailability(preferDefaultLocation = false) {
  const disease = document.getElementById('diseaseSelect').value;
  const availability = state.options?.availability?.[disease] || {};
  const locationSelect = document.getElementById('locationSelect');
  const currentLocation = locationSelect.value;
  const preferredLocation = preferDefaultLocation ? 'CHN' : currentLocation;
  fillSelect('locationSelect', availability.locations || state.options.locations || [], 'code', 'name', preferredLocation);
  if (!locationSelect.value && locationSelect.options.length) locationSelect.selectedIndex = 0;
  const modelSelect = document.getElementById('modelSelect');
  const currentModel = modelSelect.value;
  fillSelect('modelSelect', availability.models || state.options.models || [], 'code', 'name', currentModel);
  document.getElementById('startDate').value = availability.date_range?.start || state.options.date_range?.start || '';
  document.getElementById('endDate').value = availability.date_range?.end || state.options.date_range?.end || '';
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

function renderKpis(overview, metrics, quality) {
  document.getElementById('dataMode').textContent = `数据模式：${overview.data_mode || '--'}`;
  document.getElementById('lastUpdate').textContent = `更新时间：${overview.last_update || '--'}`;
  document.getElementById('demoBadge').classList.toggle('active', Boolean(overview.demo_mode));
  const metricLabel = overview.selected_metric_label || '日新增病例';
  const frequencyNames = { daily: '日频', weekly: '周频', annual: '年频' };
  const isCaseSeries = overview.selected_metric === 'new_cases';
  document.getElementById('kpiCasesLabel').textContent = isCaseSeries ? '累计病例' : '最新观测值';
  document.getElementById('kpiCases').textContent = fmtNumber(isCaseSeries ? overview.current_total_cases : overview.current_new_cases);
  document.getElementById('kpiCasesHint').textContent = metricLabel;
  document.getElementById('kpiNewCasesLabel').textContent = overview.selected_rolling_label || '当前指标';
  document.getElementById('kpiNewCases').textContent = fmtNumber(overview.current_rolling_value ?? overview.current_new_cases);
  document.getElementById('kpiNewCasesHint').textContent = `${frequencyNames[overview.selected_frequency] || '--'} · ${overview.latest_date || '--'}`;
  document.getElementById('kpiDeathsLabel').textContent = overview.current_total_deaths == null ? '数据频率' : '累计/年度死亡';
  document.getElementById('kpiDeaths').textContent = overview.current_total_deaths == null ? (frequencyNames[overview.selected_frequency] || '--') : fmtNumber(overview.current_total_deaths);
  document.getElementById('kpiDeathsHint').textContent = overview.current_total_deaths == null ? (frequencyNames[overview.selected_frequency] || '--') : '同一来源辅助指标';
  document.getElementById('kpiHighRisk').textContent = fmtNumber(overview.high_risk_regions);
  document.getElementById('kpiBestModel').textContent = `${overview.best_model || '--'} / ${fmtNumber(metrics.mae, 2)}`;
  document.getElementById('kpiQuality').textContent = fmtPercent(overview.data_completeness ?? 0);
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
  document.getElementById('trendPanelTitle').textContent = `${trend.metric_label || '指标'}与${trend.forecast_horizon_label || '预测'}`;
  document.getElementById('averagePanelTitle').textContent = trend.rolling_label || '移动平均';
  document.getElementById('weatherPanelTitle').textContent = `温湿度与${trend.metric_label || '指标'}关联`;
  document.getElementById('growthPanelTitle').textContent = `${trend.metric_label || '指标'}增长率`;
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
      apiGet('/api/weather-correlation', params),
      apiGet('/api/model-metrics'),
      apiGet('/api/data-quality'),
      apiGet('/api/disease-share'),
      apiGet('/api/predictions', params),
      apiGet('/api/source-status')
    ]);
    renderKpis(overview, metrics, quality);
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
  await loadOptions();
  await refreshDashboard();
  document.getElementById('diseaseSelect').addEventListener('change', async () => {
    applyDiseaseAvailability(false);
    await refreshDashboard();
  });
  ['locationSelect', 'startDate', 'endDate', 'modelSelect'].forEach(id => {
    document.getElementById(id).addEventListener('change', refreshDashboard);
  });
  document.getElementById('refreshBtn').addEventListener('click', refreshDashboard);
}

window.addEventListener('resize', () => Object.values(charts).forEach(chart => chart.resize()));
bootstrap().catch(error => {
  console.error(error);
  setMessage(`初始化失败：${error.message}`);
});
