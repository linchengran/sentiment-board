const state = {
  sources: [],
  tasks: [],
  dashboard: null,
  labelFilter: 'all',
  timeRange: 'today', // 'today' or 'all'
};

const els = {
  apiStatus: document.querySelector('#apiStatus'),
  taskForm: document.querySelector('#taskForm'),
  taskName: document.querySelector('#taskName'),
  sourceType: document.querySelector('#sourceType'),
  query: document.querySelector('#query'),
  intervalMinutes: document.querySelector('#intervalMinutes'),
  maxPages: document.querySelector('#maxPages'),
  topItems: document.querySelector('#topItems'),
  intervalRow: document.querySelector('#intervalRow'),
  modeOnce: document.querySelector('#modeOnce'),
  modeRepeat: document.querySelector('#modeRepeat'),
  taskCookie: document.querySelector('#taskCookie'),
  sourceHint: document.querySelector('#sourceHint'),
  taskFilter: document.querySelector('#taskFilter'),
  refreshBtn: document.querySelector('#refreshBtn'),
  demoBtn: document.querySelector('#demoBtn'),
  runDueBtn: document.querySelector('#runDueBtn'),
  freqSelect: document.querySelector('#freqSelect'),
  taskList: document.querySelector('#taskList'),
  pageTitle: document.querySelector('#pageTitle'),
  lastFetched: document.querySelector('#lastFetched'),
  timeRangeBtn: document.querySelector('#timeRangeBtn'),
  clearBtn: document.querySelector('#clearBtn'),
  metricTotal: document.querySelector('#metricTotal'),
  metricAvg: document.querySelector('#metricAvg'),
  metricLatest: document.querySelector('#metricLatest'),
  metricDelta: document.querySelector('#metricDelta'),
  metricNegative: document.querySelector('#metricNegative'),
  metricPoints: document.querySelector('#metricPoints'),
  trendChart: document.querySelector('#trendChart'),
  trendEmpty: document.querySelector('#trendEmpty'),
  pointList: document.querySelector('#pointList'),
  keywordList: document.querySelector('#keywordList'),
  platformList: document.querySelector('#platformList'),
  taskMetricList: document.querySelector('#taskMetricList'),
  commentTable: document.querySelector('#commentTable'),
  toast: document.querySelector('#toast'),
};

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const contentType = res.headers.get('content-type') || '';
  const payload = contentType.includes('application/json') ? await res.json() : await res.text();
  if (!res.ok) {
    const message = payload && payload.error ? payload.error : `请求失败：${res.status}`;
    throw new Error(message);
  }
  return payload;
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.add('show');
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => els.toast.classList.remove('show'), 3200);
}

function setOnline(value) {
  els.apiStatus.classList.toggle('online', value);
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function formatScore(value) {
  const num = Number(value || 0);
  return num.toFixed(3);
}

function formatPct(value) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

function formatDelta(value) {
  const num = Number(value || 0);
  return `${num > 0 ? '+' : ''}${num.toFixed(3)}`;
}

function renderSources() {
  els.sourceType.innerHTML = state.sources
    .map((item) => `<option value="${item.id}">${escapeHtml(item.name)}</option>`)
    .join('');
  updateSourceHint();
}

function updateSourceHint() {
  const source = state.sources.find((item) => item.id === els.sourceType.value);
  if (!source) return;
  els.query.placeholder = source.placeholder || '';
  els.sourceHint.textContent = source.hint || '';
  const sourceName = source.name.replace('评论', '').replace('热点', '').replace('订阅', '');
  if (!els.taskName.value.trim()) {
    els.taskName.placeholder = `${sourceName}监控`;
  }
}

function renderTaskFilter() {
  const selected = els.taskFilter.value || 'all';
  els.taskFilter.innerHTML = '<option value="all">全部任务</option>' + state.tasks
    .map((task) => `<option value="${task.id}">${escapeHtml(task.name)}</option>`)
    .join('');
  els.taskFilter.value = state.tasks.some((task) => task.id === selected) ? selected : 'all';
}

function renderTaskList() {
  if (!state.tasks.length) {
    els.taskList.innerHTML = '<div class="task-card"><small>暂无监控任务</small></div>';
    return;
  }

  els.taskList.innerHTML = state.tasks.map((task) => {
    const source = state.sources.find((item) => item.id === task.source_type);
    const modeLabel = task.run_mode === 'once' ? '单次分析' : '持续监测';
    const enabledText = task.run_mode === 'once'
      ? (task.last_status === '已完成' ? '已完成' : (task.enabled ? '待执行' : '已完成'))
      : (task.enabled ? '运行中' : '已暂停');
    const status = task.last_status || '未运行';
    const nextInfo = task.run_mode === 'once'
      ? `模式：${modeLabel}`
      : `下次：${escapeHtml(task.next_run_at || '-')}`;
    return `
      <article class="task-card">
        <header>
          <div>
            <strong>${escapeHtml(task.name)}</strong>
            <small>${escapeHtml(source ? source.name : task.source_type)} · ${escapeHtml(task.query || '无目标过滤')}</small>
            <small>${nextInfo} · 共采集：${task.total_saved || 0} 条${task.cookie ? ' · <span class="cookie-badge">🔑 Cookie</span>' : ''}</small>
            ${task.last_error ? `<small class="task-error">${escapeHtml(task.last_error)}</small>` : ''}
          </div>
          <span class="task-status">${enabledText} · ${escapeHtml(status)}</span>
        </header>
        <div class="task-actions">
          <button type="button" data-action="run" data-id="${task.id}">执行</button>
          ${task.run_mode !== 'once' ? `<button type="button" data-action="toggle" data-id="${task.id}">${task.enabled ? '暂停' : '启用'}</button>` : ''}
          <button type="button" class="danger" data-action="delete" data-id="${task.id}">删除</button>
        </div>
      </article>
    `;
  }).join('');
}

function renderDashboard() {
  const data = state.dashboard || {};
  const summary = data.summary || {};
  const selectedTask = state.tasks.find((task) => task.id === els.taskFilter.value);

  // 页面标题 + 当前视图状态
  const rangeLabel = state.timeRange === 'today' ? '今日' : '全部历史';
  const taskLabel = selectedTask ? `· 任务：${selectedTask.name}` : '· 全部任务';
  els.pageTitle.textContent = selectedTask ? selectedTask.name : '全局舆情概览';
  els.lastFetched.textContent = summary.last_fetched_at
    ? `最近采集：${summary.last_fetched_at} · 时间范围：${rangeLabel} ${taskLabel}`
    : `时间范围：${rangeLabel} ${taskLabel}`;

  // 清除按钮文字跟着当前筛选变
  if (els.clearBtn) {
    els.clearBtn.textContent = selectedTask ? `🗑 清除「${selectedTask.name}」数据` : '🗑 清除全部数据';
  }

  els.metricTotal.textContent = summary.total_records || 0;
  els.metricAvg.textContent = formatScore(summary.avg_score);
  els.metricLatest.textContent = formatScore(summary.latest_score);
  els.metricDelta.textContent = formatDelta(summary.score_delta);
  els.metricDelta.classList.toggle('up', Number(summary.score_delta) > 0);
  els.metricDelta.classList.toggle('down', Number(summary.score_delta) < 0);
  els.metricNegative.textContent = formatPct(summary.negative_ratio);
  els.metricPoints.textContent = summary.turning_points || 0;

  drawTrendChart(data.trend || [], data.turning_points || []);
  renderTurningPoints(data.turning_points || []);
  renderKeywords(data.keywords || []);
  renderRankList(els.platformList, data.platform_metrics || [], 'platform');
  renderRankList(els.taskMetricList, data.task_metrics || [], 'task_name');
  renderComments(data.comments || []);
}

function drawTrendChart(trend, points) {
  const svg = els.trendChart;
  svg.innerHTML = '';
  els.trendEmpty.style.display = trend.length ? 'none' : 'flex';
  if (!trend.length) return;

  const width = 1000;
  const height = 340;
  const pad = { top: 24, right: 34, bottom: 44, left: 52 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const maxCount = Math.max(...trend.map((d) => Number(d.comment_count || 0)), 1);

  const x = (idx) => pad.left + (trend.length === 1 ? innerW / 2 : (idx / (trend.length - 1)) * innerW);
  const yScore = (score) => pad.top + (1 - Number(score || 0)) * innerH;
  const yCount = (count) => pad.top + (1 - Number(count || 0) / maxCount) * innerH;
  const barWidth = Math.max(6, Math.min(42, innerW / Math.max(trend.length, 1) * 0.52));

  const ns = 'http://www.w3.org/2000/svg';
  const add = (name, attrs, parent = svg) => {
    const el = document.createElementNS(ns, name);
    Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, value));
    parent.appendChild(el);
    return el;
  };

  for (let i = 0; i <= 4; i += 1) {
    const y = pad.top + (i / 4) * innerH;
    add('line', { x1: pad.left, y1: y, x2: width - pad.right, y2: y, class: 'grid-line' });
    add('text', { x: 8, y: y + 4, class: 'axis-label' }).textContent = (1 - i / 4).toFixed(2);
  }

  // 柱状图（带延迟逐个升起）
  trend.forEach((d, idx) => {
    const cx = x(idx);
    const countY = yCount(d.comment_count);
    const barH = Math.max(2, pad.top + innerH - countY);
    const barEl = add('rect', {
      x: cx - barWidth / 2,
      y: countY,
      width: barWidth,
      height: barH,
      fill: '#F5A623',
      opacity: '0.28',
      rx: '2',
      class: 'trend-bar',
    });
    barEl.style.setProperty('--bar-delay', `${idx * 60}ms`);
  });

  // 折线路径（描边动画，从左到右画出）
  const pathD = trend.map((d, idx) => `${idx === 0 ? 'M' : 'L'} ${x(idx)} ${yScore(d.avg_score)}`).join(' ');
  const pathEl = add('path', { d: pathD, fill: 'none', stroke: '#FF7B6B', 'stroke-width': '3', 'stroke-linecap': 'round', class: 'trend-line' });
  // 计算路径总长度，用于 stroke-dasharray
  requestAnimationFrame(() => {
    const len = pathEl.getTotalLength ? pathEl.getTotalLength() : 2000;
    pathEl.style.setProperty('--dash-len', `${len}`);
    pathEl.setAttribute('stroke-dasharray', len);
    pathEl.setAttribute('stroke-dashoffset', len);
  });

  // 数据点（依次弹出，比折线稍晚开始）
  trend.forEach((d, idx) => {
    const dotEl = add('circle', { cx: x(idx), cy: yScore(d.avg_score), r: 4, fill: '#FF7B6B', class: 'trend-dot' });
    dotEl.style.setProperty('--dot-delay', `${400 + idx * 80}ms`);
  });

  const pointTimes = new Set(points.map((item) => item.time));
  trend.forEach((d, idx) => {
    if (pointTimes.has(d.time)) {
      add('circle', { cx: x(idx), cy: yScore(d.avg_score), r: 8, fill: 'none', stroke: '#9E8ED6', 'stroke-width': '3' });
    }
  });

  const labels = [trend[0], trend[Math.floor(trend.length / 2)], trend[trend.length - 1]].filter(Boolean);
  labels.forEach((d) => {
    const idx = trend.indexOf(d);
    add('text', { x: x(idx), y: height - 14, 'text-anchor': idx === 0 ? 'start' : idx === trend.length - 1 ? 'end' : 'middle', class: 'axis-label' })
      .textContent = String(d.time || '').slice(5, 16);
  });
}

function renderTurningPoints(points) {
  if (!points.length) {
    els.pointList.innerHTML = '<div class="point-item"><span>暂未检测到明显拐点</span></div>';
    return;
  }
  els.pointList.innerHTML = points.slice(-8).reverse().map((item) => `
    <div class="point-item">
      <strong>${escapeHtml(item.reason || '情绪变化')}</strong>
      <span>${escapeHtml(item.time)} · 情感分 ${formatScore(item.avg_score)} · 负面 ${formatPct(item.negative_ratio)}</span>
      <span>分数变化 ${formatDelta(item.score_change)}，负面变化 ${(Number(item.negative_ratio_change || 0) * 100).toFixed(1)}%</span>
    </div>
  `).join('');
}

function renderKeywords(keywords) {
  if (!keywords.length) {
    els.keywordList.innerHTML = '<div class="keyword-item"><span>暂无关键词</span></div>';
    return;
  }
  const max = Math.max(...keywords.map((item) => item.count), 1);
  els.keywordList.innerHTML = keywords.map((item) => `
    <div class="keyword-item">
      <strong>${escapeHtml(item.word)}</strong>
      <span>${item.count}</span>
      <div class="keyword-bar"><i style="width:${Math.max(4, item.count / max * 100)}%"></i></div>
    </div>
  `).join('');
}

function renderRankList(container, rows, labelKey) {
  if (!rows.length) {
    container.innerHTML = '<div class="rank-item"><span>暂无数据</span></div>';
    return;
  }
  container.innerHTML = rows.map((item) => `
    <div class="rank-item">
      <strong>${escapeHtml(item[labelKey] || '未命名')}</strong>
      <span>${item.count || 0} 条 · 均分 ${formatScore(item.avg_score)}${item.negative_ratio !== undefined ? ` · 负面 ${formatPct(item.negative_ratio)}` : ''}</span>
    </div>
  `).join('');
}

function renderComments(comments) {
  const filtered = comments.filter((item) => state.labelFilter === 'all' || item.label === state.labelFilter);
  if (!filtered.length) {
    els.commentTable.innerHTML = '<tr><td colspan="6">暂无明细数据</td></tr>';
    return;
  }
  els.commentTable.innerHTML = filtered.map((item) => {
    const isPositive = item.label === '正面';
    const title = item.target_url
      ? `<a href="${escapeHtml(item.target_url)}" target="_blank" rel="noreferrer">${escapeHtml(item.target_title || '-')}</a>`
      : escapeHtml(item.target_title || '-');
    return `
      <tr>
        <td>${escapeHtml(item.published_at || '-')}</td>
        <td>${escapeHtml(item.platform || '-')}<br>${title}</td>
        <td>${escapeHtml(item.task_name || '-')}</td>
        <td><span class="badge ${isPositive ? 'positive' : 'negative'}">${escapeHtml(item.label)} ${formatScore(item.score)}</span></td>
        <td class="text-cell">${escapeHtml(item.text || '')}</td>
        <td>${item.like_count || 0}</td>
      </tr>
    `;
  }).join('');
}

async function loadSources() {
  const data = await api('/api/sources');
  state.sources = data.sources || [];
  renderSources();
}

async function loadTasks() {
  const data = await api('/api/tasks');
  state.tasks = data.tasks || [];
  renderTaskFilter();
  renderTaskList();
}

async function loadDashboard() {
  const params = new URLSearchParams({
    task_id: els.taskFilter.value || 'all',
    freq: els.freqSelect.value || '30min',
  });
  if (state.timeRange === 'today') {
    const now = new Date();
    const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')} 00:00:00`;
    params.set('since', today);
  }
  state.dashboard = await api(`/api/dashboard?${params.toString()}`);
  renderDashboard();
}

async function refreshAll() {
  try {
    await loadTasks();
    await loadDashboard();
    setOnline(true);
  } catch (err) {
    setOnline(false);
    showToast(err.message);
  }
}

async function init() {
  try {
    await loadSources();
    await refreshAll();
    setOnline(true);
  } catch (err) {
    setOnline(false);
    showToast(err.message);
  }
}

els.sourceType.addEventListener('change', updateSourceHint);

// 模式切换：单次分析时隐藏间隔分钟输入
function updateRunMode() {
  const isOnce = els.modeOnce && els.modeOnce.checked;
  if (els.intervalRow) {
    els.intervalRow.style.display = isOnce ? 'none' : '';
  }
}
if (els.modeOnce) els.modeOnce.addEventListener('change', updateRunMode);
if (els.modeRepeat) els.modeRepeat.addEventListener('change', updateRunMode);

els.taskForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const runMode = (els.modeOnce && els.modeOnce.checked) ? 'once' : 'repeat';
  const payload = {
    name: els.taskName.value.trim(),
    source_type: els.sourceType.value,
    query: els.query.value.trim(),
    run_mode: runMode,
    cookie: els.taskCookie ? els.taskCookie.value.trim() : '',
    interval_minutes: Number(els.intervalMinutes.value || 10),
    max_pages: Number(els.maxPages.value || 3),
    top_items: Number(els.topItems.value || 5),
    enabled: true,
  };
  try {
    const data = await api('/api/tasks', { method: 'POST', body: JSON.stringify(payload) });
    els.taskForm.reset();
    if (els.modeRepeat) els.modeRepeat.checked = true;
    updateRunMode();
    els.intervalMinutes.value = 10;
    els.maxPages.value = 3;
    els.topItems.value = 5;
    updateSourceHint();
    await refreshAll();
    showToast(`已创建任务：${data.task.name}`);
  } catch (err) {
    showToast(err.message);
  }
});

els.taskList.addEventListener('click', async (event) => {
  const button = event.target.closest('button[data-action]');
  if (!button) return;
  const id = button.dataset.id;
  const action = button.dataset.action;
  const task = state.tasks.find((item) => item.id === id);
  if (!task) return;

  button.disabled = true;
  try {
    if (action === 'run') {
      const origText = button.textContent;
      button.textContent = '执行中…';
      try {
        const result = await api(`/api/tasks/${id}/run`, { method: 'POST' });
        showToast(`采集完成：新增 ${result.added || 0} 条，重复 ${result.skipped || 0} 条`);
      } finally {
        button.textContent = origText;
      }
    }
    if (action === 'toggle') {
      await api(`/api/tasks/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ enabled: !task.enabled }),
      });
      showToast(task.enabled ? '任务已暂停' : '任务已启用');
    }
    if (action === 'delete') {
      await api(`/api/tasks/${id}`, { method: 'DELETE' });
      showToast('任务已删除');
    }
    await refreshAll();
  } catch (err) {
    showToast(err.message);
  } finally {
    button.disabled = false;
  }
});

els.refreshBtn.addEventListener('click', refreshAll);
els.taskFilter.addEventListener('change', loadDashboard);
els.freqSelect.addEventListener('change', loadDashboard);

els.timeRangeBtn.addEventListener('click', async () => {
  state.timeRange = state.timeRange === 'today' ? 'all' : 'today';
  els.timeRangeBtn.textContent = state.timeRange === 'today' ? '查看全部历史' : '只看今日';
  await loadDashboard();
});

els.runDueBtn.addEventListener('click', async () => {
  els.runDueBtn.disabled = true;
  try {
    const data = await api('/api/run-due', { method: 'POST' });
    await refreshAll();
    showToast(`执行完成：${(data.results || []).length} 个任务`);
  } catch (err) {
    showToast(err.message);
  } finally {
    els.runDueBtn.disabled = false;
  }
});

els.demoBtn.addEventListener('click', async () => {
  els.demoBtn.disabled = true;
  try {
    const data = await api('/api/demo', { method: 'POST' });
    await refreshAll();
    els.taskFilter.value = data.task.id;
    await loadDashboard();
    showToast(`演示数据已就绪：新增 ${data.added || 0} 条`);
  } catch (err) {
    showToast(err.message);
  } finally {
    els.demoBtn.disabled = false;
  }
});

els.clearBtn.addEventListener('click', async () => {
  const selectedTask = state.tasks.find((t) => t.id === els.taskFilter.value);
  const label = selectedTask ? `「${selectedTask.name}」的采集数据` : '全部采集数据';
  if (!confirm(`确认清除 ${label}？此操作不可撤销。`)) return;
  els.clearBtn.disabled = true;
  try {
    await api('/api/clear', {
      method: 'POST',
      body: JSON.stringify({ task_id: selectedTask ? selectedTask.id : '' }),
    });
    await refreshAll();
    showToast(`已清除 ${label}`);
  } catch (err) {
    showToast(err.message);
  } finally {
    els.clearBtn.disabled = false;
  }
});

document.querySelectorAll('.nav-pill').forEach((pill) => {
  pill.addEventListener('click', () => {
    document.querySelectorAll('.nav-pill').forEach((p) => p.classList.remove('active'));
    pill.classList.add('active');
    const view = pill.textContent.trim();
    const viewMap = { '看板': 'dashboard', '任务': 'tasks', '趋势': 'trend', '明细': 'details' };
    const activeView = viewMap[view] || 'dashboard';
    document.querySelectorAll('[data-section]').forEach((section) => {
      const views = (section.dataset.section || '').split(' ');
      section.classList.toggle('hidden', !views.includes(activeView));
    });
  });
});

document.querySelectorAll('.tab-btn').forEach((button) => {
  button.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach((item) => item.classList.remove('active'));
    button.classList.add('active');
    state.labelFilter = button.dataset.label;
    renderComments((state.dashboard && state.dashboard.comments) || []);
  });
});

window.setInterval(refreshAll, 30000);
init();
