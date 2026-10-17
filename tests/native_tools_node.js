'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const file = path.resolve(__dirname, '../qf/web/native-tools.js');
assert.ok(fs.existsSync(file), '图表价格与绘图适配尚未实现');
class Element {
  constructor(tag = 'div') { this.tagName = tag; this.style = {}; this.children = []; this.listeners = {}; this.attributes = {}; this.clientWidth = 640; this.clientHeight = 200; }
  appendChild(el) { this.children.push(el); el.parentElement = this; return el; }
  replaceChildren(...els) { this.children = []; els.forEach(el => this.appendChild(el)); }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  fire(type, values = {}) {
    const event = {type, target: this, button: 0, buttons: 0, clientX: 100, clientY: 100,
      preventDefault() {}, stopImmediatePropagation() { this.stopped = true; }, ...values};
    for (const fn of this.listeners[type] || []) { fn(event); if (event.stopped) break; }
    return event;
  }
  getBoundingClientRect() { return {left: 50, top: 20, width: 640, height: this.clientHeight}; }
}
function scale() {
  let d = [100, 120], r = [200, 0];
  const fn = value => r[0] + (value - d[0]) * (r[1] - r[0]) / (d[1] - d[0]);
  fn.domain = value => value ? (d = [...value], fn) : [...d];
  fn.range = value => value ? (r = [...value], fn) : [...r];
  fn.invert = value => d[0] + (value - r[0]) * (d[1] - d[0]) / (r[1] - r[0]);
  return fn;
}
function fixture(tick = 1, focusEnabled = false) {
  const body = new Element(), doc = new Element();
  Object.assign(doc, {body, createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag)});
  const win = new Element();
  const context = vm.createContext({window: win, document: doc, console, clearTimeout,
    MouseEvent: class { constructor(type, values) { Object.assign(this, {type}, values); } }});
  const callbacks = [], packets = [], replies = {};
  if (focusEnabled) {
    context.setTimeout = fn => { callbacks.push(fn); return callbacks.length; };
    doc.querySelector = () => ({__vue__: {$tqsdk: {setChart: packet => packets.push(packet), getChart: id => replies[id]}}});
  }
  vm.runInContext(fs.readFileSync(file, 'utf8'), context);
  const root = new Element(), parent = new Element(), canvas = parent.appendChild(new Element('canvas'));
  function axis() {
    const a = {height: 200, scale: scale(), values: [], labels: [], rootG: {call(fn) { fn(); }}};
    a.axis = () => { a.labels = a.values.map(a.format); };
    a.axis.tickValues = values => { a.values = [...values]; return a.axis; };
    a.axis.tickFormat = fn => { a.format = fn; return a.axis; };
    a.draw = values => a.scale.domain(values);
    return a;
  }
  const left = axis(), right = axis();
  const series = {data: Array.from({length: 100}, (_, id) => ({datetime: 1e18 + id * 6e10}))};
  const chart = {symbol: 'TEST.a', duration: 6e10, mainType: 'candle', price_ticks: tick, price_decs: 3,
    mainSeries: series, bar: {step: 8, barWidth: 7}, chartCtrl: {pixelLeft: 0, range: {leftId: 0, rightId: 79}},
    tableContainer: {root, isDraging: false}, mainBoard: {height: 200, leftYAxis: left, rightYAxis: right,
      _centerTopCanvas: {dom: canvas}, _rightTd: {dom: new Element()}}};
  const api = win.QfNativeTools;
  chart.draw = () => { api.attach(chart); left.draw([Infinity, -Infinity]); right.draw([100, 120]); api.render(chart); };
  chart.setRange = (leftId, rightId) => { chart.chartCtrl.range = {leftId, rightId}; chart.draw(); };
  chart.bar.fullWidth = 640;
  chart.bar.setBarWidth = width => { chart.bar.barWidth = width; chart.bar.step = width + (width <= 3 ? 0 : width <= 17 ? 1 : 2); };
  chart.draw();
  const fire = (type, values = {}) => root.fire(type, {target: canvas, ...values});
  return {api, chart, left, right, root, canvas, doc, win, fire, packets, replies, flush: () => callbacks.shift()?.()};
}
function test(name, fn) {
  if (process.argv[2] && !name.includes(process.argv[2])) return;
  fn(); console.log('PASS ' + name);
}
test('resize expands upper price range without stretching the price scale', () => {
  const f = fixture();
  f.chart.mainBoard.height = f.right.height = f.left.height = f.canvas.clientHeight = 300;
  // 原生 resize/resetByKlineId 会同时把左边界从 109 修正到 110。
  f.chart.chartCtrl.range.leftId = 1;
  f.right.scale.range([300, 0]); f.left.scale.range([300, 0]); f.chart.draw();
  assert.deepEqual(f.right.scale.domain(), [100, 130]);
  assert.equal(f.right.scale(110) - f.right.scale(105), -50);
  assert.deepEqual(f.left.scale.domain(), [100, 130]);
  f.api.restore(); assert.deepEqual(f.right.scale.domain(), [100, 120]);
});
test('axes use the same domain, integer coarse labels and valid fine tick multiples', () => {
  const f = fixture(0.5);
  assert.ok(f.left.values.length > 0 && f.right.values.length > f.left.values.length);
  assert.ok(f.left.labels.every(text => /^\d+$/.test(text)));
  assert.ok(f.right.values.every(value => Number.isInteger(value / 0.5)));
  f.chart.mainBoard.height = f.right.height = f.left.height = 2000;
  // Restore at the taller size so a single tick has enough space for a label.
  f.api.restore();
  assert.equal(f.right.values[1] - f.right.values[0], 0.5);
});
test('drawing consumes left clicks, anchors prices and time, cancel restores panning', () => {
  const f = fixture();
  f.api.select('trend');
  assert.equal(f.fire('mousedown', {clientX: 130, clientY: 120}).stopped, true);
  f.fire('mousemove', {clientX: 210, clientY: 70});
  f.fire('mousedown', {clientX: 210, clientY: 70});
  let state = f.api.inspect();
  assert.equal(state.drawings.length, 1);
  assert.equal(state.drawings[0].points[0].price, 110);
  assert.equal(state.drawings[0].points[0].time, f.chart.mainSeries.data[10].datetime);
  assert.equal(state.drawings[0].points[1].price, 115);
  f.api.select('pan');
  assert.equal(f.fire('mousedown').stopped, undefined);
  assert.equal(f.api.inspect().drawings.length, 1);
  f.api.undo(); assert.equal(f.api.inspect().drawings.length, 0);
});
test('right click does not start native dragging; menu has tools and cancel', () => {
  const f = fixture();
  assert.equal(f.fire('mousedown', {button: 2}).stopped, true);
  assert.equal(f.fire('contextmenu', {button: 2}).stopped, true);
  const menu = f.doc.body.children.find(el => el.attributes.role === 'menu');
  assert.ok(menu && !menu.hidden);
  assert.ok(menu.children.some(el => el.textContent.includes('取消画图')));
});
test('escape discards pending stroke, symbol change isolates completed drawings', () => {
  const f = fixture();
  f.api.select('horizontal'); f.fire('mousedown');
  f.api.select('rectangle'); f.fire('mousedown');
  f.doc.fire('keydown', {key: 'Escape'});
  assert.equal(f.api.inspect().mode, 'pan');
  assert.equal(f.api.inspect().pending, false);
  assert.equal(f.api.inspect().drawings.length, 1);
  f.chart.symbol = 'TEST.b'; f.chart.draw();
  assert.equal(f.api.inspect().drawings.length, 0);
  f.chart.symbol = 'TEST.a'; f.chart.draw();
  assert.equal(f.api.inspect().drawings.length, 1);
  f.api.clear(); assert.equal(f.api.inspect().drawings.length, 0);
});
test('rectangles and trend lines remain anchored after panning and bar ids change', () => {
  const f = fixture();
  f.api.select('rectangle');
  f.fire('mousedown', {clientX: 130, clientY: 120});
  f.fire('mousedown', {clientX: 210, clientY: 70});
  const svg = f.canvas.parentElement.children.find(el => el.tagName === 'svg');
  assert.equal(svg.children[0].attributes.width, '88');
  assert.equal(svg.children[0].attributes.height, '50');
  const x = Number(svg.children[0].attributes.x);
  f.chart.chartCtrl.pixelLeft = 80; f.api.render(f.chart);
  assert.equal(Number(svg.children[0].attributes.x), x - 80);
  const earlier = Array.from({length: 10}, (_, id) => ({datetime: 1e18 + (id - 10) * 6e10}));
  f.chart.mainSeries.data = [...earlier, ...f.chart.mainSeries.data];
  f.chart.chartCtrl.pixelLeft = 160; f.api.render(f.chart);
  assert.equal(Number(svg.children[0].attributes.x), x - 80, '时间锚点不随缓存编号变化而漂移');
  f.api.clear(); assert.equal(svg.children.length, 0);
});
test('rectangle corner can be edited, escape rolls back and undo restores the last edit', () => {
  const f = fixture();
  f.api.select('rectangle');
  f.fire('mousedown', {clientX: 130, clientY: 120});
  f.fire('mousedown', {clientX: 210, clientY: 70});
  f.api.select('pan');
  f.fire('mousedown', {clientX: 130, clientY: 120}); f.win.fire('mouseup');
  assert.ok(f.api.inspect().selected, '点击图形应选中并显示控制点');
  const before = f.api.inspect().drawings[0].points[0];
  f.fire('mousedown', {clientX: 130, clientY: 120});
  f.doc.fire('mousemove', {buttons: 1, clientX: 146, clientY: 130});
  f.win.fire('mouseup');
  let p = f.api.inspect().drawings[0].points[0];
  assert.equal(p.time, before.time + 120e9);
  assert.equal(p.price, 109);
  f.api.undo();
  assert.deepEqual(f.api.inspect().drawings[0].points[0], before);
  f.fire('mousedown', {clientX: 130, clientY: 120}); f.win.fire('mouseup');
  f.fire('mousedown', {clientX: 130, clientY: 120});
  f.doc.fire('mousemove', {buttons: 1, clientX: 154, clientY: 140});
  f.doc.fire('keydown', {key: 'Escape'});
  assert.deepEqual(f.api.inspect().drawings[0].points[0], before);
  assert.equal(f.chart.chartCtrl.pixelLeft, 0, '编辑不得同时拖动K线');
});
test('moving rectangle border translates both anchors and delete removes only selection', () => {
  const f = fixture();
  f.api.select('rectangle');
  f.fire('mousedown', {clientX: 130, clientY: 120});
  f.fire('mousedown', {clientX: 210, clientY: 70}); f.api.select('pan');
  const before = f.api.inspect().drawings[0].points.map(p => ({...p}));
  f.fire('mousedown', {clientX: 170, clientY: 120});
  f.doc.fire('mousemove', {buttons: 1, clientX: 178, clientY: 130}); f.win.fire('mouseup');
  const after = f.api.inspect().drawings[0].points;
  for (let i = 0; i < 2; i++) {
    assert.equal(after[i].time, before[i].time + 60e9);
    assert.equal(after[i].price, before[i].price - 1);
  }
  f.doc.fire('keydown', {key: 'Delete'});
  assert.equal(f.api.inspect().drawings.length, 0);
  f.api.undo(); assert.equal(f.api.inspect().drawings.length, 1);
});
test('two full hourly candles become exactly 120 minute candles on the same symbol', () => {
  const f = fixture(), start = Date.parse('2026-10-19T09:00:00+08:00') * 1e6;
  f.chart.duration = 3600e9;
  f.chart.mainSeries.data = [0, 1].map(i => ({datetime: start + i * 3600e9}));
  f.chart.chartCtrl.range = {leftId: 0, rightId: 1}; f.chart.draw();
  f.api.select('rectangle');
  f.fire('mousedown', {clientX: 51, clientY: 30});
  f.fire('mousedown', {clientX: 59, clientY: 120});
  const anchors = f.api.inspect().drawings[0].points;
  assert.equal(anchors[0].time, start);
  assert.equal(anchors[1].time, start + 7200e9);
  f.chart.duration = 60e9; f.chart.bar.step = 4; f.chart.bar.barWidth = 3;
  f.chart.mainSeries.data = Array.from({length: 120}, (_, i) => ({datetime: start + i * 60e9}));
  f.chart.chartCtrl.range = {leftId: 0, rightId: 119}; f.chart.draw();
  assert.equal(f.api.inspect().drawings.length, 1);
  const svg = f.canvas.parentElement.children.find(el => el.tagName === 'svg');
  assert.equal(svg.children[0].attributes.x, '0');
  assert.equal(svg.children[0].attributes.width, '480');
});
test('Monday daily rectangle covers Friday night and Monday sessions across periods', () => {
  const f = fixture(), day = Date.parse('2026-10-19T00:00:00+08:00') * 1e6;
  f.chart.duration = 86400e9; f.chart.mainSeries.data = [{datetime: day}];
  f.chart.chartCtrl.range = {leftId: 0, rightId: 0}; f.chart.draw();
  f.api.select('rectangle'); f.fire('mousedown', {clientX: 51, clientY: 30});
  f.fire('mousedown', {clientX: 51, clientY: 120});
  const anchors = f.api.inspect().drawings[0].points;
  assert.equal(anchors[0].time, Date.parse('2026-10-16T18:00:00+08:00') * 1e6);
  assert.equal(anchors[1].time, Date.parse('2026-10-19T18:00:00+08:00') * 1e6);
  const night = Date.parse('2026-10-16T21:00:00+08:00') * 1e6;
  const morning = Date.parse('2026-10-19T09:00:00+08:00') * 1e6;
  f.chart.duration = 60e9;
  f.chart.mainSeries.data = [night, morning].flatMap(t => Array.from({length: 60}, (_, i) => ({datetime: t + i * 60e9})));
  f.chart.chartCtrl.range = {leftId: 0, rightId: 119}; f.chart.draw();
  assert.equal(f.api.inspect().drawings.length, 1);
  const shape = f.canvas.parentElement.children.find(el => el.tagName === 'svg').children[0];
  assert.ok(Number(shape.attributes.x) <= 0);
  assert.ok(Number(shape.attributes.x) + Number(shape.attributes.width) >= 120 * 8);
});
test('uncached period requests the drawing date and releases its temporary subscription after loading', () => {
  const f = fixture(1, true), start = Date.parse('2025-03-03T09:00:00+08:00') * 1e6;
  f.chart.duration = 3600e9; f.chart.mainSeries.data = [0, 1].map(i => ({datetime: start + i * 3600e9}));
  f.chart.chartCtrl.range = {leftId: 0, rightId: 1}; f.chart.draw();
  f.api.select('rectangle'); f.fire('mousedown', {clientX: 51}); f.fire('mousedown', {clientX: 59});
  f.chart.duration = 60e9;
  f.chart.mainSeries.data = Array.from({length: 220}, (_, i) => ({datetime: start + 300 * 86400e9 + i * 60e9}));
  f.chart.draw(); f.flush();
  assert.equal(f.packets[0].focus_datetime, start + 3600e9);
  assert.equal(f.packets[0].symbol, 'TEST.a');
  assert.equal(f.packets[0].duration, 60e9);
  f.chart.mainSeries.data = Array.from({length: 120}, (_, i) => ({datetime: start + i * 60e9}));
  f.chart.mainSeries.last_id = 119; f.flush();
  assert.equal(f.chart.chartCtrl.range.leftId, 0);
  assert.equal(f.chart.chartCtrl.range.rightId, 119);
  assert.equal(f.packets.at(-1).symbol, '');
  assert.equal(f.packets.at(-1).view_width, 0);
});
test('confirmed daily focus may start after a closed weekend without inventing night bars', () => {
  const f = fixture(1, true), day = Date.parse('2026-10-19T00:00:00+08:00') * 1e6;
  f.chart.duration = 86400e9; f.chart.mainSeries.data = [{datetime: day}];
  f.chart.chartCtrl.range = {leftId: 0, rightId: 0}; f.chart.draw();
  f.api.select('rectangle'); f.fire('mousedown', {clientX: 51, clientY: 30});
  f.fire('mousedown', {clientX: 51, clientY: 120});
  f.chart.duration = 60e9;
  f.chart.mainSeries.data = Array.from({length: 120}, (_, i) => ({datetime: day + 9 * 3600e9 + i * 60e9}));
  f.chart.mainSeries.last_id = 119; f.chart.draw(); f.flush();
  const request = f.packets[0];
  f.replies.qf_drawing_focus = {_epoch: 1, more_data: false,
    state: {...request, ins_list: request.symbol}};
  f.flush();
  assert.equal(f.chart.chartCtrl.range.leftId, 0);
  assert.equal(f.chart.chartCtrl.range.rightId, 119);
  assert.equal(f.packets.at(-1).view_width, 0);
});
test('manual browsing cancels pending historical focus so late data cannot steal the viewport', () => {
  const f = fixture(1, true), start = Date.parse('2025-03-03T09:00:00+08:00') * 1e6;
  f.chart.duration = 3600e9; f.chart.mainSeries.data = [0, 1].map(i => ({datetime: start + i * 3600e9}));
  f.chart.chartCtrl.range = {leftId: 0, rightId: 1}; f.chart.draw();
  f.api.select('rectangle'); f.fire('mousedown', {clientX: 51}); f.fire('mousedown', {clientX: 59});
  f.chart.duration = 60e9;
  f.chart.mainSeries.data = Array.from({length: 220}, (_, i) => ({datetime: start + 300 * 86400e9 + i * 60e9}));
  f.chart.draw(); f.flush();
  f.fire('wheel');
  const requestCount = f.packets.length;
  f.chart.chartCtrl.range = {leftId: 100, rightId: 180};
  f.chart.mainSeries.data = Array.from({length: 120}, (_, i) => ({datetime: start + i * 60e9}));
  f.chart.mainSeries.last_id = 119; f.flush();
  assert.equal(f.chart.chartCtrl.range.leftId, 100);
  assert.equal(f.packets.length, requestCount);
  assert.equal(f.packets.at(-1).view_width, 0);
});
test('native current-day close chart keeps its own viewport instead of following old candle dates', () => {
  const f = fixture(1, true);
  f.api.select('trend'); f.fire('mousedown', {clientX: 130}); f.fire('mousedown', {clientX: 210});
  f.chart.mainType = 'close'; f.chart.chartCtrl.range = {leftId: 40, rightId: 99};
  f.chart.draw(); f.flush();
  assert.equal(f.packets.length, 0);
  assert.equal(f.chart.chartCtrl.range.leftId, 40);
});
test('vertical drag of rectangle right corner cannot add another candle to its time span', () => {
  const f = fixture(); f.api.select('rectangle');
  f.fire('mousedown', {clientX: 130, clientY: 120});
  f.fire('mousedown', {clientX: 210, clientY: 70}); f.api.select('pan');
  const before = f.api.inspect().drawings[0].points.map(p => ({...p}));
  const x = 50 + 21 * 8;
  f.fire('mousedown', {clientX: x, clientY: 70}); f.win.fire('mouseup');
  f.fire('mousedown', {clientX: x, clientY: 70});
  f.doc.fire('mousemove', {clientX: x, clientY: 80, buttons: 1}); f.win.fire('mouseup');
  const after = f.api.inspect().drawings[0].points;
  assert.equal(after[1].time, before[1].time);
  assert.notEqual(after[1].price, before[1].price);
});
test('explicit year/latest-style range navigation cancels pending focus before late data arrives', () => {
  const f = fixture(1, true), start = Date.parse('2025-03-03T09:00:00+08:00') * 1e6;
  f.chart.duration = 3600e9; f.chart.mainSeries.data = [0, 1].map(i => ({datetime: start + i * 3600e9}));
  f.chart.chartCtrl.range = {leftId: 0, rightId: 1}; f.chart.draw();
  f.api.select('rectangle'); f.fire('mousedown', {clientX: 51}); f.fire('mousedown', {clientX: 59});
  f.chart.duration = 60e9;
  f.chart.mainSeries.data = Array.from({length: 220}, (_, i) => ({datetime: start + 300 * 86400e9 + i * 60e9}));
  f.chart.draw(); f.flush();
  f.chart.setRange(100, 180);
  f.chart.mainSeries.data = Array.from({length: 120}, (_, i) => ({datetime: start + i * 60e9}));
  f.chart.mainSeries.last_id = 119; f.flush();
  assert.equal(f.chart.chartCtrl.range.leftId, 100);
});
test('clearing the drawing also cancels its pending historical focus', () => {
  const f = fixture(1, true), start = Date.parse('2025-03-03T09:00:00+08:00') * 1e6;
  f.chart.duration = 3600e9; f.chart.mainSeries.data = [0, 1].map(i => ({datetime: start + i * 3600e9}));
  f.chart.chartCtrl.range = {leftId: 0, rightId: 1}; f.chart.draw();
  f.api.select('rectangle'); f.fire('mousedown', {clientX: 51}); f.fire('mousedown', {clientX: 59});
  f.chart.duration = 60e9;
  f.chart.mainSeries.data = Array.from({length: 220}, (_, i) => ({datetime: start + 300 * 86400e9 + i * 60e9}));
  f.chart.draw(); f.flush(); f.api.clear();
  f.chart.mainSeries.data = Array.from({length: 120}, (_, i) => ({datetime: start + i * 60e9}));
  f.chart.mainSeries.last_id = 119; f.flush();
  assert.equal(f.chart.chartCtrl.range.rightId, 1);
  assert.equal(f.api.inspect().drawings.length, 0);
  assert.equal(f.packets.at(-1).view_width, 0);
});
console.log('NATIVE_TOOLS_OFFLINE_OK');
