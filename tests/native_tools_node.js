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
function fixture(tick = 1) {
  const body = new Element(), doc = new Element();
  Object.assign(doc, {body, createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag)});
  const win = new Element();
  const context = vm.createContext({window: win, document: doc, console, clearTimeout,
    MouseEvent: class { constructor(type, values) { Object.assign(this, {type}, values); } }});
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
  chart.draw();
  const fire = (type, values = {}) => root.fire(type, {target: canvas, ...values});
  return {api, chart, left, right, root, canvas, doc, win, fire};
}
function test(name, fn) { fn(); console.log('PASS ' + name); }
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
  assert.equal(svg.children[0].attributes.width, '80');
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
console.log('NATIVE_TOOLS_OFFLINE_OK');
