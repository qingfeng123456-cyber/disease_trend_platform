const palette = {
  text: '#c8e7f5',
  muted: '#88aabc',
  grid: 'rgba(84, 172, 215, .15)',
  cyan: '#39d5ff',
  blue: '#4387ff',
  green: '#4ce3a4',
  amber: '#ffbd59',
  red: '#ff6b6b'
};

function chartBase() {
  return {
    textStyle: { color: palette.text },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(5, 12, 24, .96)',
      borderColor: palette.cyan,
      textStyle: { color: '#eefaff' }
    },
    grid: { left: 50, right: 22, top: 42, bottom: 42 },
    xAxis: { axisLine: { lineStyle: { color: palette.grid } }, axisLabel: { color: palette.muted } },
    yAxis: { splitLine: { lineStyle: { color: palette.grid } }, axisLabel: { color: palette.muted } }
  };
}

function chartModelName(model) {
  const names = {
    naive_last_value: '最近值',
    moving_average: '移动平均',
    local_sklearn_gbdt: 'GBDT',
    local_pytorch_lstm: 'LSTM'
  };
  if (String(model || '').startsWith('local_pytorch_lstm')) return 'LSTM';
  return names[model] || model;
}

function lineTrendOption(trend) {
  const points = trend.points || [];
  const actualByDate = new Map(points.map(point => [point.date, point]));
  const forecastByDate = new Map();
  points.forEach(point => {
    const targetDate = point.forecast_target_date || point.date;
    if (targetDate && Number.isFinite(point.prediction)) forecastByDate.set(targetDate, point);
  });
  const dates = Array.from(new Set([
    ...points.map(point => point.date),
    ...forecastByDate.keys()
  ])).filter(Boolean).sort();
  const actualName = trend.metric_label || '实际值';
  const rollingName = trend.rolling_label || '移动平均';
  const predictionName = `${trend.forecast_horizon_label || '未来'}预测`;
  const sparseReporting = Boolean(trend.reporting_profile?.sparse_reporting);
  return {
    ...chartBase(),
    legend: {
      type: 'scroll',
      top: 6,
      left: 12,
      right: 12,
      textStyle: { color: palette.text },
      pageTextStyle: { color: palette.muted },
      pageIconColor: palette.cyan,
      pageIconInactiveColor: palette.grid,
      data: [actualName, rollingName, predictionName, '参考下界', '参考上界']
    },
    xAxis: { type: 'category', data: dates, axisLabel: { color: palette.muted, hideOverlap: true } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: palette.muted }, splitLine: { lineStyle: { color: palette.grid } } },
    dataZoom: [
      { type: 'inside', start: 0, end: 100 },
      { type: 'slider', start: 0, end: 100, bottom: 8, height: 16, textStyle: { color: palette.muted } }
    ],
    series: [
      {
        name: actualName,
        type: sparseReporting ? 'bar' : 'line',
        showSymbol: !sparseReporting && points.length < 80,
        barMaxWidth: 7,
        data: dates.map(date => actualByDate.get(date)?.actual ?? null),
        lineStyle: { width: 1, opacity: .55 },
        itemStyle: { color: '#9ab4c5', opacity: sparseReporting ? .7 : 1 }
      },
      { name: rollingName, type: 'line', showSymbol: false, smooth: true, data: dates.map(date => actualByDate.get(date)?.rolling_7 ?? null), lineStyle: { width: 2 }, itemStyle: { color: palette.cyan }, areaStyle: { opacity: .08 } },
      { name: predictionName, type: 'line', showSymbol: false, smooth: true, connectNulls: false, data: dates.map(date => forecastByDate.get(date)?.prediction ?? null), lineStyle: { width: 2, type: 'dashed' }, itemStyle: { color: palette.red } },
      { name: '参考下界', type: 'line', showSymbol: false, data: dates.map(date => forecastByDate.get(date)?.lower ?? null), lineStyle: { opacity: 0 }, stack: 'reference-range', itemStyle: { color: 'transparent' } },
      { name: '参考上界', type: 'line', showSymbol: false, data: dates.map(date => { const point = forecastByDate.get(date); return Number.isFinite(point?.upper) && Number.isFinite(point?.lower) ? point.upper - point.lower : null; }), lineStyle: { opacity: 0 }, areaStyle: { color: 'rgba(255,107,107,.12)' }, stack: 'reference-range', itemStyle: { color: 'transparent' } }
    ]
  };
}

function avgOption(trend) {
  const points = trend.points || [];
  return {
    ...chartBase(),
    xAxis: { type: 'category', data: points.map(p => p.date), axisLabel: { color: palette.muted, hideOverlap: true } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: palette.muted }, splitLine: { lineStyle: { color: palette.grid } } },
    series: [{ name: trend.rolling_label || '移动平均', type: 'line', smooth: true, showSymbol: points.length < 80, data: points.map(p => p.rolling_7), areaStyle: { opacity: .25 }, itemStyle: { color: palette.green } }]
  };
}

function riskMapOption(risk) {
  const items = risk.items || [];
  return {
    tooltip: { trigger: 'item', formatter: p => `${p.data.location}<br/>风险分：${p.data.value[2]}<br/>等级：${p.data.risk_level}` },
    grid: { left: 38, right: 20, top: 20, bottom: 34 },
    visualMap: { min: 0, max: 100, right: 8, top: 10, textStyle: { color: palette.text }, inRange: { color: [palette.green, palette.amber, palette.red] } },
    xAxis: { type: 'value', min: -180, max: 180, name: '经度', axisLabel: { color: palette.muted }, splitLine: { lineStyle: { color: palette.grid } } },
    yAxis: { type: 'value', min: -60, max: 80, name: '纬度', axisLabel: { color: palette.muted }, splitLine: { lineStyle: { color: palette.grid } } },
    series: [{
      type: 'scatter',
      symbolSize: item => Math.max(10, item[2] / 3),
      data: items.map(item => ({ name: item.location_code, location: item.location, risk_level: item.risk_level, value: [item.longitude, item.latitude, item.risk_score] })),
      itemStyle: { shadowBlur: 12, shadowColor: 'rgba(57,213,255,.4)' }
    }]
  };
}

function rankingOption(rankings) {
  const items = (rankings.risk || []).slice(0, 12).reverse();
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 80, right: 20, top: 18, bottom: 26 },
    xAxis: { type: 'value', max: 100, axisLabel: { color: palette.muted }, splitLine: { lineStyle: { color: palette.grid } } },
    yAxis: { type: 'category', data: items.map(x => x.location_code), axisLabel: { color: palette.text } },
    series: [{ type: 'bar', data: items.map(x => x.risk_score), barWidth: 10, itemStyle: { color: palette.red } }]
  };
}

function weatherOption(data) {
  const items = (data.items || []).filter(item => [item.temperature_mean, item.relative_humidity_mean, item.new_cases_smoothed].every(Number.isFinite));
  const metricLabel = data.metric_label || '病例指标';
  const correlationText = value => value == null ? '--' : Number(value).toFixed(3);
  if (!items.length) {
    return {
      title: { text: '无同期天气匹配点', subtext: data.message || '', left: 'center', top: '38%', textStyle: { color: palette.text, fontSize: 15 }, subtextStyle: { color: palette.muted, fontSize: 11 } },
      xAxis: { show: false },
      yAxis: { show: false },
      series: []
    };
  }
  const humidityValues = items.map(item => Number(item.relative_humidity_mean));
  const maxValue = Math.max(1, ...items.map(item => Number(item.new_cases_smoothed) || 0));
  const fallbackRange = data.matched_date_range
    ? `${data.matched_date_range.start} 至 ${data.matched_date_range.end}`
    : '';
  return {
    title: {
      text: `温度 r=${correlationText(data.temperature_correlation)}  湿度 r=${correlationText(data.humidity_correlation)}  n=${data.sample_size || items.length}`,
      subtext: data.fallback_used ? `回退至天气覆盖期：${fallbackRange}` : '',
      left: 10,
      top: 2,
      textStyle: { color: palette.muted, fontSize: 11, fontWeight: 'normal' },
      subtextStyle: { color: palette.amber, fontSize: 10 }
    },
    tooltip: { trigger: 'item', formatter: p => `${p.data.location} ${p.data.date}<br/>温度：${p.value[0]}℃<br/>湿度：${p.value[2]}%<br/>${metricLabel}：${fmtNumber(p.value[1], 1)}` },
    grid: { left: 62, right: 48, top: data.fallback_used ? 48 : 34, bottom: 42 },
    xAxis: { type: 'value', name: '温度', axisLabel: { color: palette.muted }, splitLine: { lineStyle: { color: palette.grid } } },
    yAxis: { type: 'value', name: metricLabel, scale: true, axisLabel: { color: palette.muted }, splitLine: { lineStyle: { color: palette.grid } } },
    visualMap: { dimension: 2, min: Math.min(...humidityValues), max: Math.max(...humidityValues), right: 2, top: 36, text: ['湿', '干'], textStyle: { color: palette.text }, inRange: { color: [palette.amber, palette.cyan, palette.blue] } },
    series: [{
      type: 'scatter',
      data: items.map(item => ({ value: [Number(item.temperature_mean), Number(item.new_cases_smoothed), Number(item.relative_humidity_mean)], date: String(item.date).slice(0, 10), location: item.location })),
      symbolSize: value => 6 + Math.min(14, Math.sqrt(Math.max(0, value[1]) / maxValue) * 14),
      itemStyle: { opacity: .78 }
    }]
  };
}

function modelOption(metrics) {
  const items = metrics.comparison?.items || [];
  return {
    tooltip: { trigger: 'axis' },
    legend: { top: 5, textStyle: { color: palette.text } },
    grid: { left: 50, right: 18, top: 48, bottom: 38 },
    xAxis: { type: 'category', data: items.map(x => chartModelName(x.model)), axisLabel: { color: palette.muted } },
    yAxis: { type: 'value', axisLabel: { color: palette.muted }, splitLine: { lineStyle: { color: palette.grid } } },
    series: [
      { name: 'MAE', type: 'bar', data: items.map(x => x.mae), itemStyle: { color: palette.cyan } },
      { name: 'RMSE', type: 'bar', data: items.map(x => x.rmse), itemStyle: { color: palette.amber } }
    ]
  };
}

function qualityOption(report) {
  const complete = 1 - Math.max(...Object.values(report.missing_rate_by_column || { none: 0 }).map(Number));
  return {
    series: [{
      type: 'gauge',
      min: 0,
      max: 100,
      progress: { show: true, width: 10 },
      axisLine: { lineStyle: { width: 10, color: [[0.7, palette.red], [0.9, palette.amber], [1, palette.green]] } },
      axisLabel: { color: palette.muted },
      pointer: { width: 4 },
      detail: { formatter: '{value}%', color: palette.text, fontSize: 24 },
      data: [{ value: Math.round(complete * 100), name: '完整率' }]
    }]
  };
}

function growthOption(trend) {
  const points = trend.points || [];
  return {
    ...chartBase(),
    xAxis: { type: 'category', data: points.map(p => p.date), axisLabel: { color: palette.muted, hideOverlap: true } },
    yAxis: { type: 'value', axisLabel: { color: palette.muted, formatter: value => `${(value * 100).toFixed(0)}%` }, splitLine: { lineStyle: { color: palette.grid } } },
    series: [{ type: 'line', showSymbol: false, data: points.map(p => p.growth_rate_7), itemStyle: { color: palette.amber }, areaStyle: { opacity: .12 } }]
  };
}

function shareOption(data) {
  const items = data.items || [];
  return {
    tooltip: { trigger: 'item' },
    legend: {
      type: 'scroll',
      left: 8,
      right: 8,
      bottom: 3,
      textStyle: { color: palette.text },
      pageTextStyle: { color: palette.muted },
      pageIconColor: palette.cyan,
      pageIconInactiveColor: palette.grid
    },
    series: [{
      type: 'pie',
      radius: ['42%', '68%'],
      center: ['50%', '44%'],
      avoidLabelOverlap: true,
      label: {
        color: palette.text,
        fontSize: 11,
        width: 96,
        overflow: 'truncate'
      },
      labelLine: { length: 8, length2: 6 },
      labelLayout: { hideOverlap: true },
      data: items.map(x => ({ name: x.disease, value: x.record_count ?? x.total_cases ?? 0 }))
    }]
  };
}

function errorOption(predictions) {
  const items = predictions.items || [];
  if (!items.length) {
    return {
      title: { text: '当前序列没有可计算的预测误差', left: 'center', top: '42%', textStyle: { color: palette.muted, fontSize: 13, fontWeight: 'normal' } },
      xAxis: { show: false },
      yAxis: { show: false },
      series: []
    };
  }
  const dates = items.map(item => String(item.date || '').slice(0, 10));
  return {
    ...chartBase(),
    xAxis: { type: 'category', data: dates, axisLabel: { color: palette.muted, hideOverlap: true } },
    yAxis: { type: 'value', axisLabel: { color: palette.muted }, splitLine: { lineStyle: { color: palette.grid } } },
    dataZoom: [
      { type: 'inside', start: 0, end: 100 },
      { type: 'slider', start: 0, end: 100, bottom: 8, height: 16, textStyle: { color: palette.muted } }
    ],
    series: [{ name: '预测误差', type: 'bar', data: items.map(x => x.error), itemStyle: { color: value => value.data >= 0 ? palette.red : palette.green } }]
  };
}
