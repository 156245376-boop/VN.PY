// 原生图表的局部交互适配；无账户桥接、不改 SDK 文件。
(() => {
  'use strict';
  if (window.QfNativeTools) return;
  const states = new WeakMap(), names = {pan: '浏览拖动', horizontal: '水平线', trend: '趋势线', rectangle: '矩形'};
  let active = null;
  const groupKey = c => `${c.symbol}|${c.duration}|${c.mainType}`;
  const rangeKey = c => `${groupKey(c)}|${c.chartCtrl.range.leftId}|${c.chartCtrl.range.rightId}`;
  const validDomain = d => d?.length === 2 && d.every(Number.isFinite) && d[1] > d[0];
  function nice(value) {
    const power = 10 ** Math.floor(Math.log10(Math.max(value, 1)));
    return [1, 2, 5, 10].find(n => n * power >= value - 1e-9) * power;
  }
  function ticks(domain, height, tick, coarse) {
    const decimals = Math.min(10, Math.max(0, Math.ceil(-Math.log10(tick)) + 3));
    let base = tick;
    if (coarse) {
      const factor = 10 ** decimals;
      let a = Math.round(tick * factor), b = factor;
      while (b) [a, b] = [b, a % b];
      base = Math.round(tick * factor) / a;
    }
    const minimum = (domain[1] - domain[0]) / Math.max(1, height / (coarse ? 70 : 24));
    const step = base * nice(Math.max(1, minimum / base)), values = [];
    const start = Math.ceil(domain[0] / step - 1e-9), end = Math.floor(domain[1] / step + 1e-9);
    for (let n = start; n <= end && values.length < 512; n++) values.push(Number((n * step).toFixed(decimals)));
    return values;
  }
  function redrawAxes(chart, domain) {
    const board = chart.mainBoard, right = board.rightYAxis, left = board.leftYAxis, tick = chart.price_ticks;
    left.scale.domain(domain);
    if (!(tick > 0 && Number.isFinite(tick))) return;
    const precision = Math.min(10, Math.max(chart.price_decs || 0, 0));
    right.axis.tickValues(ticks(domain, board.height, tick, false)).tickFormat(value => value.toFixed(precision));
    right.rootG.call(right.axis);
    left.axis.tickValues(ticks(domain, board.height, tick, true)).tickFormat(value => value.toFixed(0));
    left.rootG.call(left.axis);
  }
  function finishNative(chart) {
    const table = chart.tableContainer;
    if (table.dragTimeout != null) { clearTimeout(table.dragTimeout); table.dragTimeout = null; }
    if (table.isDraging) table.root.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, button: 0, buttons: 0}));
  }
  function hideMenu(s) { if (s.menu) s.menu.hidden = true; }
  function drawings(c, s) {
    const key = groupKey(c);
    if (!s.groups.has(key)) s.groups.set(key, []);
    return s.groups.get(key);
  }
  function select(mode) {
    const s = states.get(active);
    if (!s || !Object.hasOwn(names, mode)) return false;
    finishNative(active); s.mode = mode; s.pending = null; s.preview = null;
    hideMenu(s); render(active); return true;
  }
  function restore() {
    const s = states.get(active);
    if (!s) return;
    s.domain = null; s.last = null; hideMenu(s); active.draw();
  }
  function undo() {
    const s = states.get(active);
    if (!s) return;
    s.pending = null; s.preview = null; drawings(active, s).pop(); render(active); hideMenu(s);
  }
  function clear() {
    const s = states.get(active);
    if (!s) return;
    s.pending = null; s.preview = null; drawings(active, s).length = 0; render(active); hideMenu(s);
  }
  function point(chart, event) {
    const rect = chart.mainBoard._centerTopCanvas.dom.getBoundingClientRect();
    const x = event.clientX - rect.left, y = event.clientY - rect.top;
    if (x < 0 || x >= rect.width || y < 0 || y > rect.height) return null;
    const id = Math.floor((chart.chartCtrl.pixelLeft + x) / chart.bar.step);
    const row = chart.mainSeries?.data?.[id], tick = chart.price_ticks;
    if (!row?.datetime || !(tick > 0)) return null;
    const raw = chart.mainBoard.rightYAxis.scale.invert(y);
    const price = Number((Math.round(raw / tick) * tick).toFixed(10));
    return Number.isFinite(price) ? {time: row.datetime, price} : null;
  }
  function createUI(chart, s) {
    const canvas = chart.mainBoard._centerTopCanvas.dom, parent = canvas.parentElement;
    if (!parent || typeof document.createElementNS !== 'function') return;
    parent.style.position = 'relative';
    s.svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    Object.assign(s.svg.style, {position: 'absolute', pointerEvents: 'none', zIndex: '4', left: '0', top: '0', overflow: 'hidden'});
    s.svg.setAttribute('aria-label', '当前品种的研究画线'); parent.appendChild(s.svg);
    s.badge = document.createElement('button');
    Object.assign(s.badge.style, {position: 'absolute', top: '24px', left: '8px', zIndex: '5', background: '#edf6f1',
      color: '#196c57', border: '1px solid #c7ddd1', borderRadius: '4px', padding: '3px 8px', fontSize: '12px', cursor: 'pointer'});
    s.badge.addEventListener('click', () => select('pan')); parent.appendChild(s.badge);
    s.menu = document.createElement('div'); s.menu.hidden = true; s.menu.setAttribute('role', 'menu');
    Object.assign(s.menu.style, {position: 'fixed', zIndex: '100000', width: '188px', padding: '5px', background: 'white',
      border: '1px solid #ccd8d1', borderRadius: '6px', boxShadow: '0 4px 18px #0002', fontSize: '13px'});
    const actions = [['水平线', () => select('horizontal')], ['趋势线（两点）', () => select('trend')],
      ['矩形（两个对角点）', () => select('rectangle')], ['撤销上一笔', undo], ['清除本图画线', clear],
      ['取消画图 · 恢复拖动（Esc）', () => select('pan')], ['恢复价格自动适配', restore]];
    for (const [label, action] of actions) {
      const button = document.createElement('button'); button.textContent = label; button.type = 'button';
      Object.assign(button.style, {display: 'block', width: '100%', padding: '8px 6px', border: '0', background: 'white', textAlign: 'left', cursor: 'pointer', color: '#29483c'});
      button.setAttribute('role', 'menuitem'); button.addEventListener('click', action); s.menu.appendChild(button);
    }
    document.body.appendChild(s.menu);
    document.addEventListener('mousedown', event => { if (!s.menu.contains?.(event.target)) hideMenu(s); });
    document.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); select('pan'); } });
    window.addEventListener('blur', () => { s.pending = null; s.preview = null; hideMenu(s); render(chart); });
    window.addEventListener('resize', () => hideMenu(s));
    chart.mainBoard._rightTd?.dom?.addEventListener('dblclick', restore);
  }
  function attach(chart) {
    active = chart;
    if (states.has(chart) || !chart.mainBoard?._centerTopCanvas?.dom || !chart.mainBoard.rightYAxis?.axis?.tickValues) return;
    const s = {mode: 'pan', groups: new Map(), pending: null, preview: null, domain: null, last: null, group: groupKey(chart)};
    states.set(chart, s); createUI(chart, s);
    const board = chart.mainBoard, right = board.rightYAxis, drawRight = right.draw;
    board.leftYAxis.draw = () => {};
    right.draw = function (automatic) {
      const key = rangeKey(chart), height = board.height;
      if (s.last && s.last.key !== key) s.domain = null;
      if (s.last && s.last.group === groupKey(chart) && height > 0 && height !== s.last.height) {
        const previous = s.last;
        s.domain = [previous.domain[0], previous.domain[0] + (previous.domain[1] - previous.domain[0]) * height / previous.height];
      }
      const domain = s.domain || automatic;
      drawRight.call(this, domain);
      if (validDomain(domain) && height > 0) { redrawAxes(chart, domain); s.last = {key, group: groupKey(chart), height, domain: [...domain]}; }
    };
    const root = chart.tableContainer.root, canvas = board._centerTopCanvas.dom;
    root.addEventListener('contextmenu', event => {
      if (event.target !== canvas || !s.menu) return;
      event.preventDefault(); event.stopImmediatePropagation(); finishNative(chart); s.menu.hidden = false;
      s.menu.style.left = Math.max(0, Math.min(event.clientX, (window.innerWidth || 1000) - 198)) + 'px';
      s.menu.style.top = Math.max(0, Math.min(event.clientY, (window.innerHeight || 800) - 310)) + 'px';
    }, true);
    root.addEventListener('mousedown', event => {
      if (event.target !== canvas) return;
      hideMenu(s);
      if (event.button === 0 && s.mode === 'pan') return;
      event.preventDefault(); event.stopImmediatePropagation();
      if (event.button !== 0) return;
      const p = point(chart, event);
      if (!p) return;
      if (s.mode === 'horizontal') drawings(chart, s).push({type: 'horizontal', points: [p]});
      else if (!s.pending) s.pending = p;
      else { drawings(chart, s).push({type: s.mode, points: [s.pending, p]}); s.pending = null; s.preview = null; }
      render(chart);
    }, true);
    root.addEventListener('mousemove', event => {
      if (event.target !== canvas || s.mode === 'pan') return;
      event.preventDefault(); event.stopImmediatePropagation(); s.preview = point(chart, event); render(chart);
    }, true);
  }
  function render(chart) {
    const s = states.get(chart);
    if (!s) return;
    const key = groupKey(chart);
    if (key !== s.group) { s.group = key; s.mode = 'pan'; s.pending = null; s.preview = null; hideMenu(s); }
    if (!s.svg) return;
    const canvas = chart.mainBoard._centerTopCanvas.dom, width = canvas.clientWidth, height = canvas.clientHeight;
    Object.assign(s.svg.style, {width: width + 'px', height: height + 'px'});
    s.svg.setAttribute('viewBox', `0 0 ${width} ${height}`); s.svg.replaceChildren();
    const ids = new Map(Object.entries(chart.mainSeries?.data || {}).filter(([, row]) => row?.datetime > 0)
      .map(([id, row]) => [row.datetime, Number(id)]));
    const xy = p => ids.has(p.time) ? {x: ids.get(p.time) * chart.bar.step + chart.bar.barWidth / 2 - chart.chartCtrl.pixelLeft,
      y: chart.mainBoard.rightYAxis.scale(p.price)} : null;
    const items = [...drawings(chart, s)];
    if (s.pending && s.preview) items.push({type: s.mode, points: [s.pending, s.preview], preview: true});
    for (const item of items) {
      const a = xy(item.points[0]), b = item.points[1] && xy(item.points[1]);
      if (!a || (item.type !== 'horizontal' && !b)) continue;
      const rect = item.type === 'rectangle';
      const shape = document.createElementNS('http://www.w3.org/2000/svg', rect ? 'rect' : 'line');
      const attributes = rect ? {x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), width: Math.abs(b.x - a.x), height: Math.abs(b.y - a.y), fill: '#247cac18'} :
        {x1: item.type === 'horizontal' ? 0 : a.x, y1: a.y, x2: item.type === 'horizontal' ? width : b.x, y2: item.type === 'horizontal' ? a.y : b.y};
      for (const [attr, value] of Object.entries(attributes)) shape.setAttribute(attr, value);
      shape.setAttribute('stroke', '#247cac'); shape.setAttribute('stroke-width', '1.5');
      if (item.preview) shape.setAttribute('stroke-dasharray', '5 4');
      s.svg.appendChild(shape);
    }
    s.badge.hidden = s.mode === 'pan';
    s.badge.textContent = `${names[s.mode]}：${s.pending ? '请选择第二点' : '点击图表绘制'} · 取消画图（Esc）`;
    canvas.style.cursor = s.mode === 'pan' ? '' : 'crosshair';
  }
  function inspect() {
    const s = states.get(active);
    return s ? {mode: s.mode, pending: !!s.pending, domain: s.last?.domain,
      drawings: drawings(active, s).map(item => ({type: item.type, points: item.points.map(p => ({...p}))}))} : null;
  }
  window.QfNativeTools = {attach, render, select, restore, undo, clear, inspect};
})();
