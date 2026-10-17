'use strict';
// 使用安装包真实的 webpack runtime、TqSdk 和绘图类；网络入口一律抛错。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const adapterPath = path.join(root, 'qf/web/native-history.js');
assert.ok(fs.existsSync(adapterPath), '原生历史适配文件尚未提供');
const adapter = fs.readFileSync(adapterPath, 'utf8');
const sdkWeb = path.join(root, '.venv-tqsdk/Lib/site-packages/tqsdk/web/js');
const nativeApp = fs.readFileSync(path.join(sdkWeb, 'app.70dcf61d.js'), 'utf8');
const nativeVendors = fs.readFileSync(path.join(sdkWeb, 'chunk-vendors.725ede45.js'), 'utf8');
const runtime = nativeApp.slice(0, nativeApp.indexOf('})({0:function'));
const day = 86400000000000;
const minute = 60000000000;
function ns(date) { return Date.parse(date) * 1000000; }
function bar(date, values = {}) {
  return {datetime: ns(date), open: 10, high: 12, low: 9, close: 11, ...values};
}
function fixture() {
  const packets = [];
  const durationWatches = [];
  const control = {selectedPeriod: '', selectedDuration: null,
    $watch: (key, callback) => { durationWatches.push(callback); return () => {}; },
    $nextTick: callback => callback()};
  const document = {readyState: 'complete', scripts: [
    {src: 'http://127.0.0.1:1234/web/js/app.70dcf61d.js'},
    {src: 'http://127.0.0.1:1234/web/js/chunk-vendors.725ede45.js'}],
    querySelector: selector => selector === '.tq-top-view' ? {__vue__: topView} :
      selector === '.tq-button-group-durations' ? {__vue__: control} : null};
  const context = {window: {}, document, console, setTimeout, clearTimeout,
    fetch() { throw new Error('离线测试禁止 fetch'); },
    WebSocket: class { constructor() { throw new Error('离线测试禁止 WebSocket'); } }};
  context.window.webpackJsonp = [];
  vm.createContext(context);
  vm.runInContext(nativeVendors, context);
  vm.runInContext(runtime + '})({0:function(module,exports,require){' +
    'window.NativeSdk=require("0977").a;window.NativeChart=require("6029").a;}})', context);
  const sdk = new context.window.NativeSdk({autoInit: false, accessToken: 'offline-fixture'});
  sdk.quotesWs = {send(packet) { packets.push({...packet}); }};
  const topView = {instrumentId: 'KQ.m@CZCE.OI', duration: day, mainType: 'candle', $tqsdk: sdk};
  const Chart = context.window.NativeChart;
  const nativeDraw = Chart.prototype.draw;
  // canvas 在 Node 中不存在；保留真实类和 setRange，只替换画布操作这一边界。
  Chart.prototype.draw = function () {
    if (!this.mainSeries || !this.mainSeries.last_id || this.mainSeries.last_id === -1) return;
    this.timeAxis.draw(this.chartCtrl.range.leftId, this.chartCtrl.range.rightId,
      this.mainSeries.data);
    this.range = {...this.chartCtrl.range};
  };
  const chart = Object.create(Chart.prototype);
  chart.symbol = topView.instrumentId;
  chart.duration = day;
  chart.mainType = 'candle';
  chart.bar = {fullWidth: 640, barWidth: 7,
    get step() { return this.barWidth + (this.barWidth <= 3 ? 0 : this.barWidth <= 17 ? 1 : 2); },
    setBarWidth(value) { this.barWidth = value; }};
  chart.range = {leftId: -1, rightId: -1};
  chart.chartCtrl = {range: {leftId: -1, rightId: -1},
    setRange(leftId, rightId) { this.range = {leftId, rightId}; }};
  chart.timeAxis = {width: 640, axis: Object.assign(() => {}, {tickFormat(fn) {
    chart.timeAxis.format = fn; return this;
  }}), rootG: {call() {}}, draw() {}};
  vm.runInContext(adapter, context);
  const api = context.window.QfNativeHistory;
  function data(rows, options = {}) {
    const entries = Object.entries(rows);
    const ids = entries.map(([id]) => Number(id));
    const last = options.last_id ?? Math.max(-1, ...ids);
    const series = sdk.getKlines(chart.symbol, chart.duration);
    series.data = [];
    for (const [id, row] of entries) series.data[id] = row;
    series.last_id = last;
    chart.mainSeries = series;
    const left = options.left ?? Math.min(...ids);
    const right = options.right ?? last;
    chart.chartCtrl.range = {leftId: left, rightId: right};
    sdk.dm.setDefault(['charts', 'web_chart'], {});
    Object.assign(sdk.getChart('web_chart'), {left_id: options.requestLeft ?? left,
      right_id: options.requestRight ?? right, more_data: options.more_data ?? false,
      state: {ins_list: chart.symbol, duration: chart.duration}});
    return series;
  }
  return {api, chart, sdk, context, packets, topView, control, durationWatches, data, nativeDraw};
}
function test(name, run) {
  if (process.argv[2] && !name.includes(process.argv[2])) return;
  run(); console.log('PASS ' + name);
}

function dragFixture() {
  const f = fixture();
  let now = 0, next = 0;
  const timers = new Map();
  f.context.setTimeout = (fn, delay) => { timers.set(++next, {fn, at: now + delay}); return next; };
  f.context.clearTimeout = id => timers.delete(id);
  class Target {
    constructor() { this.listeners = new Map(); }
    addEventListener(type, fn, capture = false) {
      const list = this.listeners.get(type) || [];
      if (!list.some(item => item.fn === fn && item.capture === !!capture)) list.push({fn, capture: !!capture});
      this.listeners.set(type, list);
    }
    removeEventListener(type, fn, capture = false) {
      this.listeners.set(type, (this.listeners.get(type) || []).filter(item => item.fn !== fn || item.capture !== !!capture));
    }
    dispatchEvent(event) {
      if (!event.target) event.target = this;
      const list = [...(this.listeners.get(event.type) || [])].sort((a, b) => Number(b.capture) - Number(a.capture));
      for (const item of list) {
        if (event.target === this || event.bubbles || item.capture) item.fn(event);
      }
      return true;
    }
    count(type) { return (this.listeners.get(type) || []).length; }
  }
  class Mouse {
    constructor(type, options = {}) { Object.assign(this, {type, bubbles: false, buttons: 0, button: 0, target: null}, options); }
    preventDefault() {}
    stopPropagation() { this.stopped = true; }
  }
  const root = new Target(), win = new Target(), doc = new Target();
  doc.hidden = false;
  f.context.MouseEvent = Mouse;
  f.context.window.addEventListener = win.addEventListener.bind(win);
  f.context.document.addEventListener = doc.addEventListener.bind(doc);
  Object.defineProperty(f.context.document, 'hidden', {get: () => doc.hidden});
  // 只在测试内存中导出锁定 SDK 的私有类；产品和安装包均保持原样。
  const factory = f.context.window.webpackJsonp.find(chunk => chunk[1]?.['6029'])[1]['6029'];
  const source = factory.toString().replace('e["a"]=class extends Lr',
    'e.Br=Br;e.Zr=Zr;e.Kr=Kr;e["a"]=class extends Lr');
  const module = {exports: {}};
  vm.runInContext('(' + source + ')', f.context)(module, module.exports, () => {});
  const {Br, Zr, Kr} = module.exports;
  const table = new Br();
  Object.assign(table, {root, isDraging: false, isClick: true, dragTimeout: null});
  table._initEventListeners();
  f.data({0: bar('2016-01-04T01:00:00Z'), 2617: bar('2026-10-16T01:00:00Z')});
  Object.assign(f.chart, {width: 652, margin: {left: 50, right: 50}, bar: new Kr(552),
    boards: {}, tableContainer: table});
  table.chart = f.chart;
  f.chart.timeAxis.showXAnnotation = () => {};
  f.chart.chartCtrl = new Zr(f.chart);
  f.chart.chartCtrl.init();
  f.context.window.NativeChart.prototype._initEventListenners.call(f.chart);
  let ended = 0;
  table.addListener('dragend', () => ended++);
  f.chart.draw();
  const canvas = {nodeName: 'CANVAS', getAttribute: () => 'plot-top-canvas', dataset: {boardId: 'main'}};
  function fire(type, values = {}) {
    root.dispatchEvent(new Mouse(type, {target: canvas, bubbles: type !== 'mouseleave', ...values}));
  }
  function advance(milliseconds) {
    now += milliseconds;
    for (const [id, timer] of [...timers]) if (timer.at <= now) { timers.delete(id); timer.fn(); }
  }
  return {...f, table, root, win, doc, fire, advance, Mouse, ended: () => ended};
}

test('[ghost_drag] 快速离开后在外松开不能留下100ms定时器或悬停拖图', () => {
  const f = dragFixture(), before = f.chart.chartCtrl.range.leftId;
  f.fire('mousedown', {buttons: 1});
  f.advance(30);
  f.fire('mouseleave', {target: f.root, buttons: 1});
  f.win.dispatchEvent(new f.Mouse('mouseup', {buttons: 0}));
  f.advance(150);
  assert.equal(f.table.isDraging, false, '图外释放不能在100ms后启动拖拽');
  assert.equal(f.table.dragTimeout, null);
  f.fire('mousemove', {buttons: 0, movementX: 400});
  assert.equal(f.chart.chartCtrl.range.leftId, before);
  assert.equal(f.root.count('mouseup'), 1, '只保留原生常驻mouseup监听');
});

test('[drag_lifecycle] 正常按钮拖动与原生dragend和动态mouseup清理保持正常', () => {
  for (const finish of ['mouseup', 'mouseleave', 'blur', 'visibilitychange', 'hover']) {
    const f = dragFixture(), before = f.chart.chartCtrl.range.leftId;
    f.fire('mousedown', {buttons: 1}); f.advance(150);
    assert.equal(f.table.isDraging, true);
    assert.equal(f.root.count('mouseup'), 2);
    f.fire('mousemove', {buttons: 1, movementX: 400});
    assert.equal(f.chart.chartCtrl.range.leftId, before - 50);
    if (finish === 'blur') f.win.dispatchEvent(new f.Mouse('blur'));
    else if (finish === 'visibilitychange') { f.doc.hidden = true; f.doc.dispatchEvent(new f.Mouse('visibilitychange')); }
    else if (finish === 'hover') f.fire('mousemove', {buttons: 0, movementX: 400});
    else f.fire(finish, {buttons: 0, ...(finish === 'mouseleave' ? {target: f.root} : {})});
    assert.equal(f.table.isDraging, false, finish);
    assert.equal(f.table.dragTimeout, null, finish);
    assert.equal(f.ended(), 1, '原生dragend应恰好一次：' + finish);
    assert.equal(f.root.count('mouseup'), 1, '移除原生动态mouseup监听：' + finish);
    f.fire('mousemove', {buttons: 0, movementX: 400});
    assert.equal(f.chart.chartCtrl.range.leftId, before - 50);
  }
});

test('[drag_children] 左键跨主图子canvas和坐标轴不能被非冒泡mouseleave提前终止', () => {
  for (const elapsed of [30, 150]) {
    const f = dragFixture(), before = f.chart.chartCtrl.range.leftId;
    f.fire('mousedown', {buttons: 1}); f.advance(elapsed);
    // 子canvas非冒泡mouseleave仍经过root捕获阶段，原生root监听不应接收。
    f.fire('mouseleave', {buttons: 1});
    f.advance(150);
    assert.equal(f.table.isDraging, true, '跨子节点不能取消计时器或已开始的拖拽');
    const axis = {nodeName: 'SVG'};
    f.fire('mousemove', {target: axis, buttons: 1, movementX: 0});
    const volume = {nodeName: 'CANVAS', getAttribute: () => 'plot-top-canvas', dataset: {boardId: 'sub'}};
    f.fire('mousemove', {target: volume, buttons: 1, movementX: 120});
    assert.equal(f.chart.chartCtrl.range.leftId, before - 15);
    assert.equal(f.ended(), 0);
    assert.equal(f.root.count('mouseup'), 2);
    f.fire('mouseleave', {target: f.root, buttons: 1});
    assert.equal(f.table.isDraging, false);
    assert.equal(f.ended(), 1);
    assert.equal(f.root.count('mouseup'), 1);
  }
});

test('[request_generation] 新请求收到完整对应确认之前不能用旧回应报断档', () => {
  const f = fixture();
  f.data({0: bar('2016-01-04T01:00:00Z'), 1: bar('2016-01-05T01:00:00Z'),
    100: bar('2026-10-15T01:00:00Z'), 101: bar('2026-10-16T01:00:00Z')},
  {left: 100, right: 101, requestLeft: 100, requestRight: 101});
  f.chart.draw();
  Object.assign(f.sdk.getChart('web_chart').state, {left_kline_id: 100, view_width: 2});
  assert.equal(f.api.inspect().status, 'ready');
  f.sdk.setChart({chart_id: 'web_chart', symbol: f.chart.symbol, duration: day,
    left_kline_id: 0, view_width: 102});
  f.chart.setRange(0, 101);
  let state = f.api.inspect();
  assert.equal(state.status, 'loading');
  assert.equal(state.protocol?.requested?.left_kline_id, 0);
  assert.equal(state.protocol?.requested?.view_width, 102);
  assert.ok(!state.history.issues.includes('id_sequence'));
  f.sdk.dm.mergeData({charts: {web_chart: {more_data: false,
    state: {...f.packets.at(-1)}}}});
  state = f.api.inspect();
  assert.equal(state.status, 'invalid');
  assert.ok(state.history.issues.includes('id_sequence'));
});

test('[draw_epoch] 分包确认后补一次真实绘图且不把旧画布报成新数据就绪', () => {
  const f = fixture();
  f.data({0: bar('2026-10-15T01:00:00Z'), 1: bar('2026-10-16T01:00:00Z')});
  const draw = f.chart.draw;
  let calls = 0;
  f.chart.draw = function (...args) { calls++; return draw.apply(this, args); };
  f.chart.draw();
  f.sdk.on('rtn_data', () => {
    if (f.sdk.getChart('web_chart').more_data === false && f.sdk.is_changed(f.chart.mainSeries)) f.chart.draw();
  });
  f.sdk.dm.mergeData({charts: {web_chart: {more_data: true}}});
  f.sdk.dm.mergeData({klines: {[f.chart.symbol]: {[day]: {data: {1: {close: 10.5}}}}}});
  assert.equal(f.api.inspect().status, 'loading');
  f.sdk.dm.mergeData({charts: {web_chart: {more_data: false}}});
  assert.equal(calls, 1, '真实原生的 is_changed 门槛错过分包更新');
  const packets = f.packets.length, range = JSON.stringify(f.chart.range);
  assert.equal(f.api.inspect().status, 'ready');
  assert.equal(calls, 2, '适配应在收齐后补一次原生绘图');
  f.api.inspect(); f.api.inspect();
  assert.equal(calls, 2);
  assert.equal(f.packets.length, packets);
  assert.equal(JSON.stringify(f.chart.range), range);
});

test('[request_fields] 普通非零、同参重发和focus请求必须等待本次完整回应', () => {
  const f = fixture();
  f.data({0: bar('2026-10-15T01:00:00Z'), 1: bar('2026-10-16T01:00:00Z')});
  f.chart.draw();
  const variants = [
    {left_kline_id: 1, view_width: 2}, {left_kline_id: 1, view_width: 2},
    {focus_datetime: ns('2026-10-15T01:00:00Z'), focus_position: 1, view_width: 2},
    {trading_day_start: 0, trading_day_count: day},
  ];
  for (const [index, fields] of variants.entries()) {
    f.sdk.setChart({chart_id: 'web_chart', symbol: f.chart.symbol, duration: day, ...fields});
    assert.equal(f.api.inspect().status, index === 1 ? 'ready' : 'loading',
      '已确认的完全相同配置允许服务端不重复发送charts差异');
    // 真实服务对已移除的可选字段发送 null tombstone，缺省字段保持原值。
    const acknowledged = {...f.packets.at(-1)};
    for (const field of ['left_kline_id', 'view_width', 'focus_datetime', 'focus_position',
      'trading_day_start', 'trading_day_count']) if (!(field in acknowledged)) acknowledged[field] = null;
    f.sdk.dm.mergeData({charts: {web_chart: {more_data: false, state: acknowledged}}});
    assert.equal(f.api.inspect().status, 'ready');
  }
});

test('[late_request] 晚安装仍需匹配socket保存的最新实际请求', () => {
  const f = fixture();
  f.data({0: bar('2026-10-15T01:00:00Z'), 1: bar('2026-10-16T01:00:00Z')});
  f.chart.draw();
  f.sdk.quotesWs.charts = {web_chart: {aid: 'set_chart', chart_id: 'web_chart',
    ins_list: f.chart.symbol, duration: day, left_kline_id: 0, view_width: 2}};
  assert.equal(f.api.inspect().status, 'loading');
  f.sdk.dm.mergeData({charts: {web_chart: {more_data: false,
    state: {...f.sdk.quotesWs.charts.web_chart}}}});
  assert.equal(f.api.inspect().status, 'ready');
});

test('[socket_resend] 重连绕过setChart直接重发同样要求新回应', () => {
  const f = fixture();
  f.data({0: bar('2026-10-15T01:00:00Z'), 1: bar('2026-10-16T01:00:00Z')});
  f.chart.draw();
  assert.equal(f.api.inspect().status, 'ready');
  f.sdk.quotesWs.send({aid: 'set_chart', chart_id: 'web_chart', ins_list: f.chart.symbol,
    duration: day, left_kline_id: 0, view_width: 2});
  assert.equal(f.api.inspect().status, 'loading');
  f.sdk.dm.mergeData({charts: {web_chart: {more_data: false, state: {...f.packets.at(-1)}}}});
  assert.equal(f.api.inspect().status, 'ready');
});

test('[first_inspect] 响应listener同步同参重发早于首次inspect仍可确认', () => {
  const f = fixture();
  f.data({0: bar('2026-10-15T01:00:00Z'), 1: bar('2026-10-16T01:00:00Z')});
  const request = {chart_id: 'web_chart', symbol: f.chart.symbol, duration: day, view_width: 8964};
  f.sdk.setChart(request);
  const packet = {...f.packets.at(-1)};
  f.sdk.on('rtn_data', () => { f.chart.draw(); f.sdk.setChart(request); });
  f.sdk.dm.mergeData({charts: {web_chart: {more_data: false, state: packet}}});
  assert.equal(f.api.inspect().status, 'ready');
});

test('[state_patch] full确认后null增量只删除指定字段并保留合约周期', () => {
  const f = fixture();
  f.data({0: bar('2026-10-15T01:00:00Z'), 1: bar('2026-10-16T01:00:00Z')});
  f.sdk.setChart({chart_id: 'web_chart', symbol: f.chart.symbol, duration: day, view_width: 8964});
  f.sdk.dm.mergeData({charts: {web_chart: {more_data: false, state: {...f.packets.at(-1)}}}});
  f.chart.draw();
  f.sdk.dm.mergeData({charts: {web_chart: {state: {left_kline_id: null}}}});
  const state = f.api.inspect();
  assert.equal(state.status, 'ready');
  assert.equal(state.protocol.responded.ins_list, f.chart.symbol);
  assert.equal(state.protocol.responded.duration, day);
  assert.ok(!Object.hasOwn(state.protocol.responded, 'left_kline_id'));
});

test('[single_bar] 真实原生 draw 对 last_id=0 早退且应明确说明限制', () => {
  const f = fixture();
  const probe = {mainType: 'candle', plots: {mainkline: {type: 'candle'}},
    mainSeries: {last_id: 0, data: [bar('2026-10-16T01:00:00Z')]},
    timeAxis: {draw() { throw Error('仅 id=0 时真实 SDK 不会到达横轴绘制'); }}};
  assert.doesNotThrow(() => f.nativeDraw.call(probe));
  f.data({0: bar('2026-10-16T01:00:00Z')});
  f.chart.draw();
  const state = f.api.inspect();
  assert.equal(state.status, 'unsupported');
  assert.equal(state.reason, 'single_bar_renderer');
  assert.equal(f.chart.mainSeries.last_id, 0);
});

test('[empty_response] 当前请求已确认无数据时明确empty而非永久等待绘图', () => {
  const f = fixture();
  f.data({}, {last_id: -1, left: 0, right: -1, requestLeft: -1, requestRight: -1, more_data: true});
  f.chart.draw();
  assert.equal(f.api.inspect().status, 'loading');
  f.sdk.dm.mergeData({charts: {web_chart: {more_data: false}}});
  const state = f.api.inspect();
  assert.equal(state.status, 'invalid');
  assert.equal(state.reason, 'empty');
  assert.deepEqual(Array.from(state.history.issues), ['empty']);
});

test('无数据或未经真实绘制时不可就绪，适配检查不发行情请求', () => {
  const f = fixture();
  assert.equal(f.api.inspect().status, 'loading');
  assert.equal(f.api.inspect().reason, 'renderer_loading');
  f.data({0: bar('2025-12-31T01:00:00Z'), 1: bar('2026-01-02T01:00:00Z')});
  assert.equal(f.api.inspect().status, 'loading');
  f.chart.draw();
  const state = f.api.inspect();
  assert.equal(state.status, 'ready');
  assert.equal(state.symbol, 'KQ.m@CZCE.OI');
  assert.equal(state.period, '1d');
  assert.equal(state.visible.first, '2025-12-31 09:00:00');
  assert.equal(state.visible.last, '2026-01-02 09:00:00');
  assert.deepEqual(Array.from(state.yearOptions), ['2025', '2026']);
  assert.equal(f.packets.length, 0);
  assert.ok(!JSON.stringify(state).includes('offline-fixture'));
  assert.ok(!JSON.stringify(state).includes('close'));
});

test('真实 SDK setChart 与 set_chart 保留 left_kline_id=0 且只发送一次', () => {
  const f = fixture();
  f.api.inspect();
  for (const method of ['setChart', 'set_chart']) {
    f.sdk[method]({chart_id: 'web_chart', symbol: f.chart.symbol, duration: day,
      left_kline_id: 0, view_width: 8964});
    assert.equal(f.packets.at(-1).left_kline_id, 0);
  }
  assert.equal(f.packets.length, 2);
  f.sdk.set_chart({chart_id: 'web_chart_focus', symbol: '', duration: day, view_width: 0});
  assert.equal(f.packets.at(-1).view_width, 0);
  f.sdk.set_chart({chart_id: 'other', symbol: f.chart.symbol, duration: minute,
    left_kline_id: 7, view_width: 20});
  assert.equal(f.packets.at(-1).left_kline_id, 7);
});

test('日线横轴包含年且周期控件选中真实日线或分钟', () => {
  const f = fixture();
  f.data({1: bar('2025-12-31T17:00:00Z')});
  f.chart.draw();
  f.api.inspect();
  assert.equal(f.chart.timeAxis.format(1), '2026-01-01');
  assert.equal(f.control.selectedPeriod, '1d');
  f.topView.duration = minute;
  f.chart.duration = minute;
  f.durationWatches.forEach(callback => callback(minute));
  assert.equal(f.control.selectedPeriod, '1m');
});

test('原生行情回调需同时确认 chart 并更新当前 K 线 epoch 才真正绘制', () => {
  const f = fixture();
  f.data({0: bar('2026-10-15T01:00:00Z'), 1: bar('2026-10-16T01:00:00Z')}, {more_data: true});
  f.sdk.on('rtn_data', () => {
    if (f.sdk.getChart('web_chart').more_data === false && f.sdk.is_changed(f.chart.mainSeries)) f.chart.draw();
  });
  f.sdk.dm.mergeData({charts: {web_chart: {more_data: false}}});
  assert.equal(f.api.inspect().status, 'loading', '只有 charts 确认没有触发原生绘图');
  f.sdk.dm.mergeData({charts: {web_chart: {more_data: false}}, klines: {
    [f.chart.symbol]: {[day]: {data: {1: {close: 10.5}}}}
  }});
  assert.equal(f.api.inspect().status, 'ready');
});

test('真实数据按北京时间归年，选择年份只使用该年缓存 id', () => {
  const f = fixture();
  f.data({10: bar('2025-12-30T17:00:00Z'), 11: bar('2025-12-31T17:00:00Z'),
    12: bar('2026-01-02T01:00:00Z')});
  f.chart.draw();
  assert.equal(f.api.inspect().history.years['2026'], 2);
  assert.equal(f.api.jumpToYear('2026'), true);
  assert.equal(f.chart.range.leftId, 11);
  assert.equal(f.chart.range.rightId, 12);
  assert.equal(f.api.jumpToYear('2024'), false);
  assert.equal(f.api.navigateLatest(), true);
  assert.equal(f.chart.range.rightId, 12);
});

test('2016 到 2026 的相邻日线断档与时间倒序均明确无效', () => {
  for (const rows of [
    {0: bar('2016-01-04T01:00:00Z'), 1: bar('2026-10-16T01:00:00Z')},
    {0: bar('2026-10-16T01:00:00Z'), 1: bar('2016-01-04T01:00:00Z')},
  ]) {
    const f = fixture(); f.data(rows); f.chart.draw();
    const state = f.api.inspect();
    assert.equal(state.status, 'invalid');
    assert.ok(state.history.issues.length > 0);
  }
});

test('请求范围内缺 id 或无效 OHLC 不可就绪，31天内休市不误报', () => {
  const missing = fixture();
  missing.data({0: bar('2026-10-08T01:00:00Z'), 2: bar('2026-10-12T01:00:00Z')});
  missing.chart.draw();
  assert.equal(missing.api.inspect().status, 'invalid');
  for (const values of [{close: NaN}, {high: 8}, {datetime: 0}, {datetime: 1e300}]) {
    const f = fixture(); f.data({0: bar('2026-10-08T01:00:00Z', values)}); f.chart.draw();
    assert.equal(f.api.inspect().status, 'invalid');
  }
  const holiday = fixture();
  holiday.data({0: bar('2026-09-30T01:00:00Z'), 1: bar('2026-10-08T01:00:00Z')});
  holiday.chart.draw();
  assert.equal(holiday.api.inspect().status, 'ready');
});

test('允许历史与当前两个已请求缓存窗口之间尚未请求的空隙', () => {
  const f = fixture();
  f.data({0: bar('2016-01-04T01:00:00Z'), 1: bar('2016-01-05T01:00:00Z'),
    2000: bar('2026-10-15T01:00:00Z'), 2001: bar('2026-10-16T01:00:00Z')},
  {left: 2000, right: 2001, requestLeft: 2000, requestRight: 2001});
  f.chart.draw();
  assert.equal(f.api.inspect().status, 'ready');
  assert.equal(f.api.inspect().history.valid_count, 4);
});

test('切换内部品种或周期后必须重新匹配数据和真实绘制', () => {
  const f = fixture();
  f.data({1: bar('2026-10-16T01:00:00Z')}); f.chart.draw();
  f.topView.instrumentId = 'KQ.m@DCE.m';
  assert.equal(f.api.inspect().status, 'loading');
  f.chart.symbol = f.topView.instrumentId;
  f.data({1: bar('2026-10-16T01:00:00Z')});
  assert.equal(f.api.inspect().status, 'loading');
  f.chart.draw();
  assert.equal(f.api.inspect().status, 'ready');
  assert.equal(f.api.inspect().symbol, 'KQ.m@DCE.m');
  f.sdk.getChart('web_chart').more_data = true;
  assert.equal(f.api.inspect().status, 'loading');
});

test('2016至2026每个真实年份均能定位且全年日线可容纳在画布内', () => {
  const f = fixture(), rows = {};
  let id = 0;
  for (let time = Date.parse('2016-01-04T01:00:00Z'); time <= Date.parse('2026-10-16T01:00:00Z'); time += 86400000) {
    const weekday = new Date(time).getUTCDay();
    if (weekday !== 0 && weekday !== 6) rows[id++] = bar(new Date(time).toISOString());
  }
  f.data(rows, {left: id - 64, right: id - 1, requestLeft: 0, requestRight: id - 1});
  f.chart.draw();
  assert.equal(f.api.inspect().status, 'ready');
  for (let year = 2016; year <= 2026; year++) {
    assert.equal(f.api.jumpToYear(String(year)), true);
    const state = f.api.inspect();
    assert.equal(state.status, 'ready');
    assert.ok(state.visible.first.startsWith(String(year)));
    assert.ok(state.visible.last.startsWith(String(year)));
    const span = f.chart.range.rightId - f.chart.range.leftId + 1;
    assert.ok(span * f.chart.bar.step <= f.chart.bar.fullWidth, '全年真实日线不应裁出画布');
    const before = JSON.stringify(f.chart.range), packetCount = f.packets.length;
    f.api.inspect(); f.api.inspect();
    assert.equal(JSON.stringify(f.chart.range), before, '轮询检查不能跳回最新');
    assert.equal(f.packets.length, packetCount);
  }
});

test('适配可在document创建时先排队，再在真实SDK bootstrap之前安装', () => {
  const document = {readyState: 'loading', scripts: [], querySelector: () => null};
  const context = {window: {}, document, setTimeout, clearTimeout,
    fetch() { throw new Error('禁止 fetch'); }, WebSocket: class { constructor() { throw new Error('禁止联网'); } }};
  vm.createContext(context); vm.runInContext(adapter, context);
  assert.equal(context.window.QfNativeHistory.inspect().status, 'loading');
  document.scripts = [{src: '/web/js/app.70dcf61d.js'}, {src: '/web/js/chunk-vendors.725ede45.js'}];
  vm.runInContext(nativeVendors, context);
  vm.runInContext(runtime + '})({0:function(module,exports,require){window.Sdk=require("0977").a;}})', context);
  assert.equal(context.window.Sdk.prototype.setChart.name, 'corrected');
  assert.equal(context.window.Sdk.prototype.setChart, context.window.Sdk.prototype.set_chart);
});

test('不受支持的 SDK 资源不修改原生代码，重复 inspect 不重复包装', () => {
  const f = fixture();
  f.api.inspect();
  const draw = Object.getPrototypeOf(f.chart).draw;
  f.api.inspect(); f.api.inspect();
  assert.equal(Object.getPrototypeOf(f.chart).draw, draw);
  const unknown = fixture();
  unknown.context.document.scripts = [{src: '/web/js/app.unknown.js'}];
  // 重新评估独立页面，避免复用前一页面已经安装的适配。
  const context = {window: {}, document: unknown.context.document};
  vm.createContext(context); vm.runInContext(adapter, context);
  assert.equal(context.window.QfNativeHistory.inspect().status, 'unsupported');
});
console.log('NATIVE_HISTORY_OFFLINE_OK');
