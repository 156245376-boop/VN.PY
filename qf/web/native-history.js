// 仅适配当前锁定的 TqSdk 3.10.2 原生资源，不读取认证对象或接入业务桥。
(() => {
  'use strict';
  if (window.QfNativeHistory) return;
  const DAY = 86400000000000, MINUTE = 60000000000;
  const records = new WeakMap(), axes = new WeakSet(), controls = new WeakSet();
  const gestures = new WeakSet();
  const requests = new WeakMap(), responses = new WeakMap(), recovered = new WeakMap();
  const sockets = new WeakMap();
  const requestFields = ['ins_list', 'duration', 'left_kline_id', 'view_width',
    'focus_datetime', 'focus_position', 'trading_day_start', 'trading_day_count'];
  let queued = false, installed = false, unsupported = false, current = null;
  const issuesForDraw = new WeakSet();
  const periods = new Map([[MINUTE, '1m'], [5 * MINUTE, '5m'], [15 * MINUTE, '15m'],
    [30 * MINUTE, '30m'], [60 * MINUTE, '1h'], [DAY, '1d']]);
  const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
  function beijing(datetime) {
    if (!Number.isFinite(datetime) || datetime <= 0) return '';
    const date = new Date(datetime / 1000000 + 8 * 3600000);
    return Number.isFinite(date.getTime()) ? date.toISOString().slice(0, 19).replace('T', ' ') : '';
  }
  function resourcesMatch() {
    const sources = Array.from(document.scripts || [], script => script.src || '');
    return ['app.70dcf61d.js', 'chunk-vendors.725ede45.js'].every(name =>
      sources.some(source => source.split(/[?#]/)[0].endsWith('/' + name)));
  }
  function topView() { return document.querySelector('.tq-top-view')?.__vue__; }
  function syncPeriod() {
    const view = topView(), control = document.querySelector('.tq-button-group-durations')?.__vue__;
    if (!view || !control) return;
    if (!controls.has(control) && typeof control.$watch === 'function') {
      controls.add(control);
      control.$watch('duration', () => {
        if (typeof control.$nextTick === 'function') control.$nextTick(syncPeriod);
        else syncPeriod();
      });
    }
    const period = view.duration === MINUTE && view.mainType === 'close' ? '分时' : periods.get(view.duration);
    if (period && control.selectedPeriod !== period) {
      control.selectedDuration = view.duration;
      control.selectedPeriod = period;
    }
  }
  function patchSetChart(proto) {
    const original = proto.setChart;
    function corrected(options) {
      const tracked = observeSocket(this);
      if (!tracked) return original.call(this, options);
      const previous = tracked.options;
      tracked.options = options;
      try { return original.call(this, options); }
      finally { tracked.options = previous; }
    }
    proto.setChart = proto.set_chart = corrected;
  }
  function observeSocket(sdk) {
    const socket = sdk.quotesWs;
    if (!socket || typeof socket.send !== 'function') return null;
    if (sockets.has(socket)) return sockets.get(socket);
    const tracked = {options: null}, send = socket.send;
    sockets.set(socket, tracked);
    socket.send = function (packet) {
      const options = tracked.options;
      if (options && packet?.aid === 'set_chart' &&
          packet.chart_id === (options.chart_id || sdk._prefix + 'kline_chart')) {
        if (options.left_kline_id === 0) packet.left_kline_id = 0;
        if (options.view_width === 0) packet.view_width = 0;
      }
      const epoch = sdk.dm._epoch;
      const state = packet?.aid === 'set_chart' && packet.chart_id === 'web_chart' ? requestState(packet) : null;
      const previous = requests.get(sdk), response = state && sdk.getChart('web_chart');
      // 同参导航不一定再收到 charts 差异；仅复用已完成的同参确认，重连直接重发除外。
      const reuse = !!(options && state && previous && response?.more_data === false &&
        sameState(state, previous.state) && requestAcknowledged(sdk, response, previous));
      const result = send.call(this, packet);
      if (state) requests.set(sdk, {state, epoch, reuse});
      return result;
    };
    return tracked;
  }
  function requestState(packet) {
    const state = {};
    for (const field of requestFields) if (own(packet, field)) state[field] = packet[field];
    return state;
  }
  function sameState(expected, actual) {
    return !!actual && requestFields.every(field => own(expected, field) === own(actual, field) &&
      (!own(expected, field) || expected[field] === actual[field]));
  }
  function requestAcknowledged(sdk, response, request) {
    return sameState(request.state, responses.get(sdk.dm) || response?.state) &&
      (request.epoch < 0 || request.reuse || response._epoch > request.epoch);
  }
  function patchResponses(proto) {
    const merge = proto.mergeData;
    proto.mergeData = function (data, ...args) {
      for (const diff of Array.isArray(data) ? data : [data]) {
        const state = diff?.charts?.web_chart?.state;
        // state 是增量协议：缺省保留，只有显式 null 才删除上一请求可选字段。
        if (state && typeof state === 'object') {
          const merged = {...(responses.get(this) || {})};
          for (const field of requestFields) if (own(state, field)) {
            if (state[field] === null) delete merged[field];
            else merged[field] = state[field];
          }
          responses.set(this, merged);
        }
      }
      return merge.call(this, data, ...args);
    };
  }
  function responseReason(sdk, response, chart) {
    observeSocket(sdk);
    let request = requests.get(sdk);
    // 允许在页面已经运行后安装；SDK 自有 socket.charts 保存实际最近请求。
    if (!request && sdk.quotesWs?.charts?.web_chart) {
      request = {state: requestState(sdk.quotesWs.charts.web_chart), epoch: -1};
      requests.set(sdk, request);
    }
    if (!response?.state || typeof response.state !== 'object') return 'response_missing';
    const state = responses.get(sdk.dm) || response.state;
    if (state?.ins_list !== chart.symbol || state?.duration !== chart.duration) return 'response_selection_pending';
    if (!request) return '';
    if (!sameState(request.state, state)) return 'response_state_pending';
    return requestAcknowledged(sdk, response, request) ? '' : 'response_epoch_pending';
  }
  function responseMatches(sdk, response, chart) { return responseReason(sdk, response, chart) === ''; }
  function patchGestures(chart) {
    const table = chart.tableContainer, root = table?.root;
    if (!root || gestures.has(table) || typeof root.addEventListener !== 'function' ||
        typeof root.dispatchEvent !== 'function') return;
    gestures.add(table);
    let finishing = false;
    function finish(event) {
      if (finishing) return;
      if (table.dragTimeout != null) { clearTimeout(table.dragTimeout); table.dragTimeout = null; }
      table.isClick = false;
      if (!table.isDraging) return;
      // 由原生mouseup闭包结束拖拽、发送dragend并移除动态监听；不提前改状态。
      finishing = true;
      try {
        root.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, cancelable: true,
          button: 0, buttons: 0, clientX: event?.clientX ?? 0, clientY: event?.clientY ?? 0}));
      } finally { finishing = false; }
    }
    root.addEventListener('mousedown', finish, true);
    root.addEventListener('mouseleave', event => { if (event.target === root) finish(event); }, true);
    root.addEventListener('mousemove', event => { if ((event.buttons & 1) === 0) finish(event); }, true);
    window.addEventListener('mouseup', finish);
    window.addEventListener('blur', finish);
    document.addEventListener('visibilitychange', event => { if (document.hidden) finish(event); });
  }
  function patchAxis(chart) {
    const axis = chart.timeAxis;
    if (!axis || axes.has(axis)) return;
    if (typeof axis.draw !== 'function' || typeof axis.axis?.tickFormat !== 'function' ||
        typeof axis.rootG?.call !== 'function') return;
    axes.add(axis);
    const original = axis.draw;
    axis.draw = function (left, right, data) {
      const result = original.call(this, left, right, data);
      if (chart.duration >= DAY) {
        this.axis.tickFormat(id => beijing(data?.[id]?.datetime).slice(0, 10));
        this.rootG.call(this.axis);
      }
      // 记录实际传入横轴绘制的数据，调用 draw 但提前返回不算已绘制。
      chart.__qfHistoryDrawing = {symbol: chart.symbol, duration: chart.duration,
        series: chart.mainSeries, epoch: chart.mainSeries?._epoch, data, left, right,
        visibleRight: Number.isFinite(this.width) && chart.bar?.step > 0 ?
          Math.min(right, left + Math.ceil(this.width / chart.bar.step) - 1) : right};
      return result;
    };
  }
  function queueInstall() {
    if (installed || queued || unsupported) return;
    if (!resourcesMatch() && document.readyState !== 'loading') { unsupported = true; return; }
    const chunks = window.webpackJsonp = window.webpackJsonp || [];
    if (!Array.isArray(chunks) || typeof chunks.push !== 'function') { unsupported = true; return; }
    queued = true;
    const id = 'qf-native-history-v3102';
    chunks.push([[id], {[id]: function (module, exports, require) {
      if (!resourcesMatch()) { unsupported = true; return; }
      try {
        const chartProto = require('6029').a?.prototype, sdkClass = require('0977').a;
        const sdkProto = sdkClass?.prototype, dataProto = sdkClass?.DataManager?.prototype;
        if (!chartProto || !sdkProto || ['draw', 'init', 'setRange'].some(key =>
          typeof chartProto[key] !== 'function') || ['setChart', 'set_chart', 'getByPath', 'getChart'].some(key =>
          typeof sdkProto[key] !== 'function') || typeof dataProto?.mergeData !== 'function') { unsupported = true; return; }
        patchSetChart(sdkProto);
        patchResponses(dataProto);
        const draw = chartProto.draw;
        chartProto.draw = function (...args) {
          current = this;
          patchGestures(this);
          patchAxis(this);
          delete this.__qfHistoryDrawing;
          try {
            const result = draw.apply(this, args);
            if (this.__qfHistoryDrawing) records.set(this, this.__qfHistoryDrawing);
            else records.delete(this);
            issuesForDraw.delete(this);
            return result;
          } catch (error) { records.delete(this); issuesForDraw.add(this); throw error; }
          finally { delete this.__qfHistoryDrawing; }
        };
        installed = true;
      } catch (_) { unsupported = true; }
    }}, [[id, 'chunk-vendors']]]);
  }
  function analyze(chart, response, drawn, complete) {
    const valid = [], issues = new Set(), years = {}, present = new Set();
    const data = chart.mainSeries?.data || [];
    let malformed = 0;
    for (const key of Object.keys(data)) {
      const id = Number(key);
      if (!Number.isInteger(id) || id < 0) continue;
      present.add(id);
      const row = data[id], date = beijing(row?.datetime);
      if (!row || !date || !['open', 'high', 'low', 'close'].every(field => Number.isFinite(row[field])) ||
          row.high < Math.max(row.open, row.close, row.low) || row.low > Math.min(row.open, row.close, row.high)) {
        malformed++; continue;
      }
      valid.push({id, datetime: row.datetime, date});
    }
    valid.sort((a, b) => a.id - b.id);
    if (malformed) issues.add('invalid_bar');
    if (!valid.length) issues.add('empty');
    for (let index = 0; index < valid.length; index++) {
      const row = valid[index], year = row.date.slice(0, 4);
      years[year] = (years[year] || 0) + 1;
      if (!index) continue;
      const previous = valid[index - 1];
      if (row.datetime <= previous.datetime) issues.add('time_order');
      // 尚未请求的两个稀疏缓存窗口之间不推断缺失；相邻真实 id 的日期必须可信。
      if (chart.duration >= DAY && row.id === previous.id + 1 &&
          row.datetime - previous.datetime > 31 * DAY) issues.add('long_gap');
    }
    let missing = 0;
    const ranges = complete ? [[response?.left_id, response?.right_id], [drawn?.left, drawn?.right]] : [];
    const checked = new Set();
    for (const [left, right] of ranges) {
      if (!Number.isInteger(left) || !Number.isInteger(right) || left < 0 || right < left) continue;
      if (right - left > 100000) { issues.add('id_sequence'); continue; }
      for (let id = left; id <= right && id <= chart.mainSeries.last_id; id++) {
        if (!checked.has(id) && !present.has(id)) missing++;
        checked.add(id);
      }
    }
    if (missing) issues.add('id_sequence');
    const visible = valid.filter(row => row.id >= drawn?.left && row.id <= drawn?.visibleRight);
    return {valid, history: {valid_count: valid.length, first: valid[0]?.date || '',
      last: valid.at(-1)?.date || '', years, issues: [...issues], invalid_count: malformed,
      missing_count: missing}, visible: {first: visible[0]?.date || '', last: visible.at(-1)?.date || ''}};
  }
  function inspect() {
    queueInstall();
    syncPeriod();
    const view = topView(), chart = current;
    const snapshot = {status: unsupported ? 'unsupported' : 'loading',
      symbol: typeof view?.instrumentId === 'string' ? view.instrumentId : '',
      period: periods.get(view?.duration) || '', duration: Number.isFinite(view?.duration) ? view.duration : 0,
      history: {valid_count: 0, first: '', last: '', years: {}, issues: []},
      visible: {first: '', last: ''}, yearOptions: []};
    const loading = reason => { snapshot.reason = reason; return snapshot; };
    if (unsupported) return loading('unsupported_resources');
    if (!installed) return loading('adapter_loading');
    if (!view) return loading('view_loading');
    if (!chart) return loading('renderer_loading');
    if (!chart.mainSeries) return loading('series_loading');
    if (chart.symbol !== view.instrumentId || chart.duration !== view.duration) return loading('selection_pending');
    const sdk = view.$tqsdk, source = sdk?.getByPath?.(['klines', chart.symbol, chart.duration]);
    if (source !== chart.mainSeries) return loading('source_mismatch');
    const response = sdk.getChart('web_chart');
    let drawn = records.get(chart);
    const complete = responseMatches(sdk, response, chart) && response.more_data === false;
    snapshot.protocol = {requested: requestState(requests.get(sdk)?.state || {}),
      responded: requestState(responses.get(sdk.dm) || {})};
    const checked = analyze(chart, response, drawn, complete);
    snapshot.history = checked.history; snapshot.visible = checked.visible;
    snapshot.yearOptions = Object.keys(checked.history.years).sort();
    if (issuesForDraw.has(chart)) { snapshot.status = 'invalid'; snapshot.history.issues.push('invalid_bar'); return snapshot; }
    if (checked.history.issues.some(code => ['invalid_bar', 'time_order', 'long_gap'].includes(code))) {
      snapshot.status = 'invalid'; return snapshot;
    }
    if (!complete) return loading(responseReason(sdk, response, chart) || 'response_more_data');
    if (checked.history.issues.includes('empty')) {
      snapshot.status = 'invalid'; snapshot.reason = 'empty'; return snapshot;
    }
    if (source.last_id === 0 && checked.valid.length === 1 && checked.valid[0].id === 0 && !drawn) {
      snapshot.status = 'unsupported'; snapshot.reason = 'single_bar_renderer'; return snapshot;
    }
    // charts 和 klines 可分包到达，原生 is_changed(bt) 会错过绘制；仅修复已绘制的原位置。
    if (drawn && drawn.epoch !== source._epoch && drawn.series === source &&
        drawn.left === chart.range?.leftId && drawn.right === chart.range?.rightId &&
        drawn.left === chart.chartCtrl?.range?.leftId && drawn.right === chart.chartCtrl?.range?.rightId &&
        source.last_id - drawn.right !== 1) {
      const previous = recovered.get(chart), request = requests.get(sdk);
      if (!previous || previous.source !== source || previous.epoch !== source._epoch || previous.request !== request) {
        recovered.set(chart, {source, epoch: source._epoch, request});
        try { chart.draw(); } catch (_) { snapshot.status = 'invalid'; snapshot.history.issues.push('invalid_bar'); return snapshot; }
        drawn = records.get(chart);
      }
    }
    const drawnMatches = drawn && drawn.symbol === chart.symbol && drawn.duration === chart.duration &&
      drawn.series === chart.mainSeries && drawn.data === source.data && drawn.epoch === source._epoch &&
      drawn.left === chart.range?.leftId && drawn.right === chart.range?.rightId;
    if (!drawnMatches) {
      if (!drawn) return loading('draw_pending');
      if (drawn.symbol !== chart.symbol || drawn.duration !== chart.duration) return loading('draw_selection_pending');
      if (drawn.series !== source || drawn.data !== source.data) return loading('draw_source_pending');
      if (drawn.epoch !== source._epoch) return loading('draw_stale');
      return loading('draw_range_pending');
    }
    if (!responseMatches(sdk, response, chart) || response.more_data !== false)
      return loading(responseReason(sdk, response, chart) || 'response_more_data');
    snapshot.status = checked.history.issues.length ? 'invalid' : checked.visible.first ? 'ready' : 'loading';
    if (snapshot.status === 'loading') snapshot.reason = 'visible_empty';
    return snapshot;
  }
  function navigate(year) {
    const state = inspect();
    if (!['ready', 'invalid'].includes(state.status) || !current) return false;
    const data = current.mainSeries?.data || [];
    const rows = Object.keys(data).map(Number).filter(id => Number.isInteger(id) && id >= 0)
      .filter(id => {
        const row = data[id], date = beijing(row?.datetime);
        return date && (year === null || date.startsWith(year + '-')) &&
          ['open', 'high', 'low', 'close'].every(key => Number.isFinite(row[key])) &&
          row.high >= Math.max(row.open, row.close, row.low) && row.low <= Math.min(row.open, row.close, row.high);
      }).sort((a, b) => a - b);
    if (!rows.length) return false;
    const last = rows.at(-1), first = year === null ? rows[Math.max(0, rows.length - 100)] : rows[0];
    // 原生 candle.setRange 不缩放柱宽；年导航需主动让真实日线落入画布。
    const bars = current.bar, span = last - first + 1;
    if (bars?.fullWidth > 0 && typeof bars.setBarWidth === 'function') {
      const limit = bars.fullWidth / span;
      let width = Math.min(35, Math.max(1, Math.floor(limit)));
      while (width > 1 && width + (width <= 3 ? 0 : width <= 17 ? 1 : 2) > limit) width--;
      bars.setBarWidth(width);
    }
    current.setRange(first, last);
    return true;
  }
  window.QfNativeHistory = {inspect,
    jumpToYear: year => /^\d{4}$/.test(String(year)) && navigate(String(year)),
    navigateLatest: () => navigate(null)};
  queueInstall();
})();
