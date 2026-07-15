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

const WORLD_RISK_MAP_NAME = 'natural-earth-world';

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

const preferredTrendWindows = {
  'COVID-19:CHN': { start: '2020-12-11', end: '2021-05-14' }
};

function initialTrendZoom(trend, dates) {
  if (dates.length < 2) return { start: 0, end: 100 };

  const key = `${trend.disease || ''}:${trend.location_code || ''}`;
  const preferred = preferredTrendWindows[key];
  if (!preferred) return { start: 0, end: 100 };

  const startValue = dates.find(date => date >= preferred.start);
  const endValue = [...dates].reverse().find(date => date <= preferred.end);
  const startIndex = dates.indexOf(startValue);
  const endIndex = dates.indexOf(endValue);
  if (startIndex < 0 || endIndex <= startIndex || endIndex - startIndex < 30) {
    return { start: 0, end: 100 };
  }

  return { startValue, endValue };
}

function timeSeriesDataZoom(context, dates) {
  const initialZoom = initialTrendZoom(context, dates);
  return [
    { type: 'inside', filterMode: 'filter', ...initialZoom },
    {
      type: 'slider',
      filterMode: 'filter',
      ...initialZoom,
      bottom: 8,
      height: 17,
      borderColor: 'rgba(57,213,255,.28)',
      fillerColor: 'rgba(57,213,255,.14)',
      handleStyle: { color: palette.cyan, borderColor: '#d9f8ff' },
      moveHandleStyle: { color: palette.cyan },
      dataBackground: {
        lineStyle: { color: 'rgba(136,170,188,.72)' },
        areaStyle: { color: 'rgba(67,135,255,.18)' }
      },
      selectedDataBackground: {
        lineStyle: { color: palette.cyan },
        areaStyle: { color: 'rgba(57,213,255,.22)' }
      },
      textStyle: { color: palette.muted }
    }
  ];
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
    animationDuration: 550,
    grid: { left: 64, right: 24, top: 48, bottom: 66, containLabel: true },
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
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: sparseReporting,
      axisLabel: { color: palette.muted, hideOverlap: true }
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { color: palette.muted },
      splitLine: { lineStyle: { color: palette.grid } }
    },
    dataZoom: timeSeriesDataZoom(trend, dates),
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
      { name: rollingName, type: 'line', showSymbol: false, smooth: 0.18, sampling: 'lttb', data: dates.map(date => actualByDate.get(date)?.rolling_7 ?? null), lineStyle: { width: 2 }, itemStyle: { color: palette.cyan }, areaStyle: { opacity: .08 } },
      { name: predictionName, type: 'line', showSymbol: false, smooth: 0.12, sampling: 'lttb', connectNulls: false, data: dates.map(date => forecastByDate.get(date)?.prediction ?? null), lineStyle: { width: 2, type: 'dashed' }, itemStyle: { color: palette.red } },
      { name: '参考下界', type: 'line', showSymbol: false, data: dates.map(date => forecastByDate.get(date)?.lower ?? null), lineStyle: { opacity: 0 }, stack: 'reference-range', itemStyle: { color: 'transparent' } },
      { name: '参考上界', type: 'line', showSymbol: false, data: dates.map(date => { const point = forecastByDate.get(date); return Number.isFinite(point?.upper) && Number.isFinite(point?.lower) ? point.upper - point.lower : null; }), lineStyle: { opacity: 0 }, areaStyle: { color: 'rgba(255,107,107,.12)' }, stack: 'reference-range', itemStyle: { color: 'transparent' } }
    ]
  };
}

function avgOption(trend) {
  const points = trend.points || [];
  const dates = points.map(point => point.date);
  return {
    ...chartBase(),
    animationDuration: 450,
    grid: { left: 64, right: 22, top: 18, bottom: 66, containLabel: true },
    xAxis: { type: 'category', data: dates, boundaryGap: false, axisLabel: { color: palette.muted, hideOverlap: true } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: palette.muted }, splitLine: { lineStyle: { color: palette.grid } } },
    dataZoom: timeSeriesDataZoom(trend, dates),
    series: [{
      name: trend.rolling_label || '移动平均',
      type: 'line',
      smooth: 0.18,
      sampling: 'lttb',
      showSymbol: false,
      data: points.map(point => point.rolling_7),
      lineStyle: { width: 2 },
      areaStyle: { opacity: .18 },
      itemStyle: { color: palette.green }
    }]
  };
}

function riskMapOption(risk) {
  const items = risk.items || [];
  const mapRegistered = Boolean(window.echarts?.getMap?.(WORLD_RISK_MAP_NAME));
  if (!mapRegistered) {
    return {
      title: {
        text: '世界地图资源未加载',
        subtext: '请检查 /static/data/world_countries.geojson',
        left: 'center',
        top: '38%',
        textStyle: { color: palette.text, fontSize: 15 },
        subtextStyle: { color: palette.muted, fontSize: 11 }
      },
      xAxis: { show: false },
      yAxis: { show: false },
      series: []
    };
  }
  return {
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(5, 12, 24, .96)',
      borderColor: palette.cyan,
      textStyle: { color: '#eefaff' },
      formatter: p => `${p.data.location}<br/>风险分：${p.data.value[2]}<br/>等级：${p.data.risk_level}`
    },
    visualMap: {
      type: 'continuous',
      min: 0,
      max: 100,
      dimension: 2,
      seriesIndex: 0,
      right: 4,
      top: 'middle',
      itemWidth: 10,
      itemHeight: 88,
      text: ['高', '低'],
      textGap: 5,
      calculable: false,
      textStyle: { color: palette.muted, fontSize: 10 },
      inRange: { color: [palette.green, palette.amber, palette.red] }
    },
    geo: {
      map: WORLD_RISK_MAP_NAME,
      left: 8,
      right: 38,
      top: 8,
      bottom: 8,
      roam: true,
      scaleLimit: { min: 0.9, max: 8 },
      itemStyle: {
        areaColor: '#0b2b3d',
        borderColor: 'rgba(88, 190, 224, .55)',
        borderWidth: 0.7
      },
      emphasis: {
        disabled: false,
        itemStyle: { areaColor: '#12445a', borderColor: palette.cyan, borderWidth: 1 }
      },
      select: { disabled: true },
      silent: true
    },
    series: [{
      name: '地区风险',
      type: 'effectScatter',
      coordinateSystem: 'geo',
      showEffectOn: 'render',
      rippleEffect: { brushType: 'stroke', scale: 2.4, period: 5 },
      symbolSize: value => Math.max(7, Math.min(20, 7 + Number(value[2] || 0) * 0.13)),
      data: items.map(item => ({ name: item.location_code, location: item.location, risk_level: item.risk_level, value: [item.longitude, item.latitude, item.risk_score] })),
      itemStyle: { shadowBlur: 10, shadowColor: 'rgba(57,213,255,.5)' },
      emphasis: { scale: 1.35 }
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
  const metricRows = [
    { key: 'mae', label: 'MAE', lowerIsBetter: true, description: '平均绝对误差，单位与当前疾病指标相同' },
    { key: 'rmse', label: 'RMSE', lowerIsBetter: true, description: '均方根误差，对较大的预测偏差更敏感' },
    { key: 'r2', label: 'R²', lowerIsBetter: false, description: '相对均值基线的拟合优度，越接近 1 越好，也可能为负' },
    { key: 'mape', label: 'MAPE', lowerIsBetter: true, description: '平均绝对百分比误差，真实值接近 0 时不稳定' },
    { key: 'smape', label: 'sMAPE', lowerIsBetter: true, description: '对称平均绝对百分比误差，仍需结合 MAE 阅读' }
  ];
  const formatMetric = (key, value) => {
    if (!Number.isFinite(value)) return '--';
    if (key === 'mape' || key === 'smape') {
      const percentage = value * 100;
      const digits = Math.abs(percentage) >= 1000 ? 0 : 2;
      return `${percentage.toLocaleString('zh-CN', { maximumFractionDigits: digits })}%`;
    }
    if (key === 'r2') return value.toLocaleString('zh-CN', { maximumFractionDigits: 3 });
    return value.toLocaleString('zh-CN', { maximumFractionDigits: 2 });
  };
  const metricValue = (item, key) => {
    const rawValue = item[key];
    if (rawValue === null || rawValue === undefined || rawValue === '') return Number.NaN;
    return Number(rawValue);
  };
  const rankScores = new Map();
  metricRows.forEach(metric => {
    const rankedValues = Array.from(new Set(
      items.map(item => metricValue(item, metric.key)).filter(Number.isFinite)
    )).sort((left, right) => left - right);
    items.forEach(item => {
      const value = metricValue(item, metric.key);
      if (!Number.isFinite(value)) return;
      if (rankedValues.length <= 1) {
        rankScores.set(`${item.model}:${metric.key}`, 100);
        return;
      }
      const rank = rankedValues.indexOf(value);
      const denominator = rankedValues.length - 1;
      const ascendingScore = rank * 100 / denominator;
      rankScores.set(`${item.model}:${metric.key}`, metric.lowerIsBetter ? 100 - ascendingScore : ascendingScore);
    });
  });
  const heatmapData = [];
  items.forEach((item, modelIndex) => {
    metricRows.forEach((metric, metricIndex) => {
      const value = metricValue(item, metric.key);
      const available = Number.isFinite(value);
      heatmapData.push({
        value: [modelIndex, metricIndex, available ? rankScores.get(`${item.model}:${metric.key}`) : 50],
        rawValue: available ? value : null,
        formatted: formatMetric(metric.key, value),
        model: item.model,
        metricLabel: metric.label,
        description: metric.description,
        direction: metric.lowerIsBetter ? '越低越好' : '越高越好',
        itemStyle: available ? undefined : { color: 'rgba(136, 170, 188, .18)' }
      });
    });
  });
  return {
    animationDuration: 450,
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(5, 12, 24, .96)',
      borderColor: palette.cyan,
      textStyle: { color: '#eefaff' },
      formatter: params => {
        const item = params.data;
        return `<strong>${chartModelName(item.model)}</strong><br/>${item.metricLabel}：${item.formatted}<br/>${item.description}<br/><span style="color:${palette.amber}">${item.direction}</span>`;
      }
    },
    grid: { left: 70, right: 12, top: 8, bottom: 64 },
    xAxis: {
      type: 'category',
      data: items.map(item => chartModelName(item.model)),
      splitArea: { show: true, areaStyle: { color: ['rgba(10, 28, 45, .28)', 'rgba(7, 20, 35, .28)'] } },
      axisLine: { lineStyle: { color: palette.grid } },
      axisLabel: { color: palette.text, interval: 0, fontSize: 10 }
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: metricRows.map(metric => metric.label),
      splitArea: { show: true, areaStyle: { color: ['rgba(10, 28, 45, .28)', 'rgba(7, 20, 35, .28)'] } },
      axisLine: { lineStyle: { color: palette.grid } },
      axisLabel: { color: palette.text, fontWeight: 700 }
    },
    visualMap: {
      min: 0,
      max: 100,
      calculable: false,
      orient: 'horizontal',
      left: 'center',
      bottom: 5,
      itemWidth: 10,
      itemHeight: 100,
      text: ['同项较优', '同项较弱'],
      textStyle: { color: palette.muted, fontSize: 10 },
      inRange: { color: [palette.red, palette.amber, palette.green] }
    },
    series: [{
      name: '测试集指标',
      type: 'heatmap',
      data: heatmapData,
      label: {
        show: true,
        color: '#06131f',
        fontSize: 10,
        fontWeight: 700,
        formatter: params => params.data.formatted
      },
      itemStyle: { borderColor: 'rgba(5, 18, 31, .8)', borderWidth: 2 },
      emphasis: { itemStyle: { borderColor: '#eefaff', borderWidth: 2 } }
    }]
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
  const dates = points.map(point => point.date);
  return {
    ...chartBase(),
    animationDuration: 450,
    grid: { left: 64, right: 22, top: 18, bottom: 66, containLabel: true },
    xAxis: { type: 'category', data: dates, boundaryGap: false, axisLabel: { color: palette.muted, hideOverlap: true } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: palette.muted, formatter: value => `${(value * 100).toFixed(0)}%` }, splitLine: { lineStyle: { color: palette.grid } } },
    dataZoom: timeSeriesDataZoom(trend, dates),
    series: [{
      name: '增长率',
      type: 'line',
      showSymbol: false,
      sampling: 'lttb',
      data: points.map(point => point.growth_rate_7),
      lineStyle: { width: 2 },
      itemStyle: { color: palette.amber },
      areaStyle: { opacity: .12 }
    }]
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
    animationDuration: 450,
    grid: { left: 64, right: 22, top: 18, bottom: 66, containLabel: true },
    xAxis: { type: 'category', data: dates, axisLabel: { color: palette.muted, hideOverlap: true } },
    yAxis: { type: 'value', axisLabel: { color: palette.muted }, splitLine: { lineStyle: { color: palette.grid } } },
    dataZoom: timeSeriesDataZoom(predictions, dates),
    series: [{ name: '预测误差', type: 'bar', barMaxWidth: 8, data: items.map(item => item.error), itemStyle: { color: value => value.data >= 0 ? palette.red : palette.green } }]
  };
}
