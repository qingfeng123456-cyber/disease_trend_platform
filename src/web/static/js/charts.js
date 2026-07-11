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

function lineTrendOption(trend) {
  const points = trend.points || [];
  const dates = points.map(p => p.date);
  const actualName = trend.metric_label || '实际值';
  const rollingName = trend.rolling_label || '移动平均';
  const predictionName = `${trend.forecast_horizon_label || '未来'}预测`;
  return {
    ...chartBase(),
    legend: { top: 8, textStyle: { color: palette.text }, data: [actualName, rollingName, predictionName, '置信下界', '置信上界'] },
    xAxis: { type: 'category', data: dates, axisLabel: { color: palette.muted, hideOverlap: true } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: palette.muted }, splitLine: { lineStyle: { color: palette.grid } } },
    dataZoom: [{ type: 'inside', start: 68, end: 100 }, { type: 'slider', bottom: 8, height: 16, textStyle: { color: palette.muted } }],
    series: [
      { name: actualName, type: 'line', showSymbol: points.length < 80, data: points.map(p => p.actual), lineStyle: { width: 1, opacity: .55 }, itemStyle: { color: '#9ab4c5' } },
      { name: rollingName, type: 'line', showSymbol: false, smooth: true, data: points.map(p => p.rolling_7), lineStyle: { width: 2 }, itemStyle: { color: palette.cyan }, areaStyle: { opacity: .08 } },
      { name: predictionName, type: 'line', showSymbol: false, smooth: true, data: points.map(p => p.prediction), lineStyle: { width: 2, type: 'dashed' }, itemStyle: { color: palette.red } },
      { name: '置信下界', type: 'line', showSymbol: false, data: points.map(p => p.lower), lineStyle: { opacity: 0 }, stack: 'confidence', itemStyle: { color: 'transparent' } },
      { name: '置信上界', type: 'line', showSymbol: false, data: points.map((p, i) => p.upper && p.lower ? p.upper - p.lower : null), lineStyle: { opacity: 0 }, areaStyle: { color: 'rgba(255,107,107,.12)' }, stack: 'confidence', itemStyle: { color: 'transparent' } }
    ]
  };
}

function avgOption(trend) {
  const points = (trend.points || []).slice(-365);
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
  return {
    title: { text: `温度 r=${correlationText(data.temperature_correlation)}  湿度 r=${correlationText(data.humidity_correlation)}  n=${data.sample_size || items.length}`, left: 10, top: 2, textStyle: { color: palette.muted, fontSize: 11, fontWeight: 'normal' } },
    tooltip: { trigger: 'item', formatter: p => `${p.data.location} ${p.data.date}<br/>温度：${p.value[0]}℃<br/>湿度：${p.value[2]}%<br/>${metricLabel}：${fmtNumber(p.value[1], 1)}` },
    grid: { left: 62, right: 48, top: 34, bottom: 42 },
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
    xAxis: { type: 'category', data: items.map(x => x.model), axisLabel: { color: palette.muted } },
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
  const points = (trend.points || []).slice(-240);
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
    legend: { bottom: 5, textStyle: { color: palette.text } },
    series: [{
      type: 'pie',
      radius: ['42%', '68%'],
      center: ['50%', '44%'],
      label: { color: palette.text },
      data: items.map(x => ({ name: x.disease, value: x.record_count ?? x.total_cases ?? 0 }))
    }]
  };
}

function errorOption(predictions) {
  const items = (predictions.items || []).slice(-180);
  if (!items.length) {
    return {
      title: { text: '该序列未进入 COVID 日频模型', left: 'center', top: '42%', textStyle: { color: palette.muted, fontSize: 13, fontWeight: 'normal' } },
      xAxis: { show: false },
      yAxis: { show: false },
      series: []
    };
  }
  return {
    ...chartBase(),
    xAxis: { type: 'category', data: items.map(x => x.date), axisLabel: { color: palette.muted, hideOverlap: true } },
    yAxis: { type: 'value', axisLabel: { color: palette.muted }, splitLine: { lineStyle: { color: palette.grid } } },
    series: [{ name: '预测误差', type: 'bar', data: items.map(x => x.error), itemStyle: { color: value => value.data >= 0 ? palette.red : palette.green } }]
  };
}
