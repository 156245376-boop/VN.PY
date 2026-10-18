// 原生图表的局部交互适配；无账户桥接、不改 SDK 文件。
(() => {
  'use strict';
  if (window.QfNativeTools) return;
  const states = new WeakMap(), indexes = new WeakMap();
  const names = {pan: '浏览拖动', horizontal: '水平线', trend: '趋势线', rectangle: '矩形'};
  let active = null;
  let sharedPrefix='';
  const groupKey = c => c.symbol;
  const viewKey = c => `${c.symbol}|${c.duration}|${c.mainType}`;
  const rangeKey = c => `${viewKey(c)}|${c.chartCtrl.range.leftId}|${c.chartCtrl.range.rightId}`;
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
  const copy = items => items.map(item => ({...item, points: item.points.map(p => ({...p}))}));
  function remember(c, s, before = copy(drawings(c, s))) {
    if(sharedPrefix)return;
    const key = groupKey(c);
    if (!s.history.has(key)) s.history.set(key, []);
    s.history.get(key).push(before);
  }
  function cancelEdit(s) {
    if (s.edit) s.groups.set(s.edit.key, s.edit.before);
    s.edit = null;
  }
  function intervals(c) {
    const data = c.mainSeries?.data, epoch = c.mainSeries?._epoch, cached = indexes.get(c);
    if (Number.isFinite(epoch) && cached?.data === data && cached.epoch === epoch && cached.duration === c.duration) return cached.rows;
    const day = 86400e9;
    const rows = Object.entries(data || {}).filter(([, row]) => row?.datetime > 0)
      .map(([id, row]) => {
        let start = row.datetime, end = start + c.duration;
        if (c.duration === day) {
          start -= 6 * 3600e9;
          const weekday = new Date(start / 1e6 + 8 * 3600e3).getUTCDay();
          if (weekday === 0 || weekday === 6) start -= (weekday === 0 ? 2 : 1) * day;
          end = row.datetime + 18 * 3600e9;
        }
        return {id: Number(id), time: row.datetime, start, end};
      }).sort((a, b) => a.id - b.id).map((row, i, rows) => ({...row,
        end: rows[i + 1] ? Math.min(row.end, rows[i + 1].start) : row.end}));
    indexes.set(c, {data, epoch, duration: c.duration, rows});
    return rows;
  }
  function locate(rows, time) {
    let lo = 0, hi = rows.length;
    while (lo < hi) { const mid = (lo + hi) >>> 1; if (rows[mid].start <= time) lo = mid + 1; else hi = mid; }
    return lo - 1;
  }
  function position(rows, p, c) {
    if (!rows.length) return null;
    const i = locate(rows, p.time), last = rows.at(-1);
    if (i < 0) return rows[0].id - 1e6;
    if (p.time > last.end) return last.id + 1e6;
    const row = rows[i];
    if (p.time >= row.end) return rows[i + 1]?.id ?? row.id + 1;
    if (!p.boundary && p.time === row.time) return row.id + c.bar.barWidth / (2 * c.bar.step);
    return row.id + (p.time - row.start) / (row.end - row.start);
  }
  function geometry(c, s) {
    const rows = intervals(c);
    const xy = p => {
      const pos = position(rows, p, c);
      return pos === null ? null : {x: pos * c.bar.step - c.chartCtrl.pixelLeft,
        y: c.mainBoard.rightYAxis.scale(p.price)};
    };
    return {rows, items: drawings(c, s).map(item => ({item, a: xy(item.points[0]), b: item.points[1] && xy(item.points[1])}))};
  }
  function controls(g) {
    if (g.item.type === 'horizontal') return [{x: 20, y: g.a.y}];
    if (g.item.type === 'trend') return [g.a, g.b];
    return [g.a, {x: g.b.x, y: g.a.y}, g.b, {x: g.a.x, y: g.b.y}];
  }
  function hit(c, s, event) {
    const r = c.mainBoard._centerTopCanvas.dom.getBoundingClientRect();
    const x = event.clientX - r.left, y = event.clientY - r.top;
    for (const g of geometry(c, s).items.reverse()) {
      if (!g.a || (g.item.type !== 'horizontal' && !g.b)) continue;
      if (g.item.id === s.selected) {
        const handle = controls(g).findIndex(p => Math.hypot(p.x - x, p.y - y) <= 8);
        if (handle >= 0) return {id: g.item.id, handle};
      }
      let distance;
      if (g.item.type === 'horizontal') distance = Math.abs(y - g.a.y);
      else if (g.item.type === 'rectangle') {
        const l = Math.min(g.a.x, g.b.x), r = Math.max(g.a.x, g.b.x), t = Math.min(g.a.y, g.b.y), b = Math.max(g.a.y, g.b.y);
        distance = x >= l - 6 && x <= r + 6 && y >= t - 6 && y <= b + 6 ?
          Math.min(Math.abs(x - l), Math.abs(x - r), Math.abs(y - t), Math.abs(y - b)) : Infinity;
      } else {
        const dx = g.b.x - g.a.x, dy = g.b.y - g.a.y;
        const u = Math.max(0, Math.min(1, ((x - g.a.x) * dx + (y - g.a.y) * dy) / (dx * dx + dy * dy || 1)));
        distance = Math.hypot(x - g.a.x - u * dx, y - g.a.y - u * dy);
      }
      if (distance <= 6) return {id: g.item.id, handle: -1};
    }
    return null;
  }
  function select(mode) {
    const s = states.get(active);
    if (!s || !Object.hasOwn(names, mode)) return false;
    cancelEdit(s); stopFocus(s); s.navigation = ''; finishNative(active);
    active.mainBoard._centerTopCanvas.dom.style.cursor = mode === 'pan' ? '' : 'crosshair';
    s.mode = mode; s.pending = null; s.preview = null; s.selected = null;
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
    stopFocus(s); s.navigation = ''; cancelEdit(s); s.pending = null; s.preview = null; s.selected = null;
    if(sharedPrefix){window.QfNativeTools.onUndo?.({symbol:active.symbol,version:s.versions?.get(active.symbol)||0});return;}
    const before = s.history.get(groupKey(active))?.pop();
    if (before) s.groups.set(groupKey(active), before);
    render(active); hideMenu(s);
  }
  function clear() {
    const s = states.get(active);
    if (!s) return;
    stopFocus(s); s.navigation = ''; cancelEdit(s); s.pending = null; s.preview = null; s.selected = null;
    if (drawings(active, s).length) { remember(active, s); drawings(active, s).length = 0; }
    render(active); hideMenu(s);
  }
  function removeSelected() {
    const s = states.get(active);
    if (!s?.selected) return;
    stopFocus(s); s.navigation = ''; cancelEdit(s); remember(active, s);
    s.groups.set(groupKey(active), drawings(active, s).filter(item => item.id !== s.selected));
    s.selected = null; render(active); hideMenu(s);
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
    const interval = intervals(chart).find(r => r.id === id);
    return Number.isFinite(price) && interval ? {time: row.datetime, price, start: interval.start, end: interval.end} : null;
  }
  function complete(type, a, b, id) {
    if (type !== 'rectangle') return {id, type, points: [a, b].filter(Boolean).map(p => ({time: p.time, price: p.price}))};
    const [left, right] = a.start <= b.start ? [a, b] : [b, a];
    return {id, type, points: [{time: left.start, price: left.price, boundary: true},
      {time: right.end, price: right.price, boundary: true}]};
  }
  function updateEdit(c, s, event) {
    const edit = s.edit;
    if (!edit) return;
    if (!(event.buttons & 1)) { cancelEdit(s); render(c); return; }
    event.preventDefault(); event.stopImmediatePropagation();
    const p = point(c, event);
    if (!p) return;
    const item = drawings(c, s).find(item => item.id === edit.id);
    if (!item) return;
    const points = edit.original.points.map(p => ({...p}));
    if (edit.handle < 0) {
      const slots = Math.round((event.clientX - edit.x) / c.bar.step), rows = intervals(c);
      const delta = p.time - edit.origin.time;
      for (const anchor of points) {
        const i = locate(rows, anchor.time), row = rows[i], target = rows[i + slots];
        anchor.time = row && target && anchor.time <= row.end ?
          target.start + (anchor.time - row.start) / (row.end - row.start) * (target.end - target.start) : anchor.time + delta;
        anchor.price = Number((anchor.price + p.price - edit.origin.price).toFixed(10));
      }
    } else if (item.type === 'rectangle') {
      const xi = [0, 1, 1, 0][edit.handle], yi = [0, 0, 1, 1][edit.handle];
      const slots = Math.round((event.clientX - edit.x) / c.bar.step);
      if (slots) {
        const rows = intervals(c), boundary = Math.round(position(rows, points[xi], c)) + slots;
        const row = rows.find(row => row.id === boundary - (xi === 1 ? 1 : 0));
        points[xi].time = row ? xi === 0 ? row.start : row.end : points[xi].time + p.time - edit.origin.time;
      }
      points[yi].price = p.price;
    } else {
      points[edit.handle].time = p.time; points[edit.handle].price = p.price;
    }
    item.points = points; render(c);
  }
  function finishEdit(c, s) {
    if (!s.edit) return;
    const item = drawings(c, s).find(item => item.id === s.edit.id);
    if (item && JSON.stringify(item.points) !== JSON.stringify(s.edit.original.points)) remember(c, s, s.edit.before);
    s.edit = null; render(c);
  }
  function stopFocus(s) {
    const focus = s.focus; s.focus = null;
    if (focus?.requested) {
      try { focus.sdk.setChart({chart_id: 'qf_drawing_focus', symbol: '', duration: focus.duration, view_width: 0}); }
      catch (_) { /* 断线期间本地取消仍须立即生效，连接由原生会话清理。 */ }
    }
  }
  function followDrawing(c, s, target) {
    if (typeof setTimeout !== 'function') return;
    stopFocus(s);
    const sdk = document.querySelector?.('.tq-top-view')?.__vue__?.$tqsdk;
    const focus = {key: viewKey(c), duration: c.duration, sdk, ...target, started: Date.now()};
    s.focus = focus; s.navigation = 'loading';
    function locateDate() {
      if (s.focus !== focus || viewKey(c) !== focus.key) return;
      const rows = intervals(c), middle = (focus.from + focus.to) / 2;
      const inside = rows.length && middle >= rows[0].start && middle <= rows.at(-1).end;
      const reply = sdk?.getChart?.('qf_drawing_focus');
      const confirmed = focus.requested && reply?.more_data === false && reply._epoch > focus.requestEpoch &&
        reply.state?.ins_list === c.symbol && reply.state?.duration === c.duration && reply.state?.focus_datetime === Math.round(middle);
      const visible = inside || confirmed ? rows.filter(row => row.end > focus.from && row.start < focus.to) : [];
      if (visible.length) {
        const first = visible[0].id, last = visible.at(-1).id, span = last - first + 1, bars = c.bar;
        if (span * bars.step > bars.fullWidth && bars.setBarWidth) {
          let width = Math.min(35, Math.max(1, Math.floor(bars.fullWidth / span)));
          while (width > 1 && width + (width <= 3 ? 0 : width <= 17 ? 1 : 2) > bars.fullWidth / span) width--;
          bars.setBarWidth(width);
        }
        const count = Math.max(1, Math.floor(bars.fullWidth / bars.step));
        const left = Math.max(0, Math.floor((first + last - count + 1) / 2));
        stopFocus(s); s.navigation = '';
        c.setRange(left, Math.min(c.mainSeries.last_id, left + count - 1));
        return;
      }
      if (!focus.requested && sdk) {
        focus.requested = true; focus.requestEpoch = sdk.dm?._epoch ?? -1;
        try { sdk.setChart({chart_id: 'qf_drawing_focus', symbol: c.symbol, duration: c.duration,
          focus_datetime: Math.round(middle), focus_position: 4482, view_width: 8964}); }
        catch (_) { stopFocus(s); s.navigation = 'unavailable'; render(c); return; }
      }
      if (Date.now() - focus.started >= 30000 || !sdk) {
        stopFocus(s); s.navigation = 'unavailable'; render(c); return;
      }
      setTimeout(locateDate, 200);
    }
    setTimeout(locateDate, 0);
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
      ['矩形（两个对角点）', () => select('rectangle')], ['撤销上次操作', undo], ['删除选中图形（Delete）', removeSelected], ['清除本合约画线', clear],
      ['取消画图 · 恢复拖动（Esc）', () => select('pan')], ['恢复价格自动适配', restore]];
    for (const [label, action] of actions) {
      const button = document.createElement('button'); button.textContent = label; button.type = 'button';
      Object.assign(button.style, {display: 'block', width: '100%', padding: '8px 6px', border: '0', background: 'white', textAlign: 'left', cursor: 'pointer', color: '#29483c'});
      button.setAttribute('role', 'menuitem'); button.addEventListener('click', action); s.menu.appendChild(button);
    }
    document.body.appendChild(s.menu);
    document.addEventListener('mousedown', event => { if (!s.menu.contains?.(event.target)) hideMenu(s); });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); select('pan'); }
      if (['Delete', 'Backspace'].includes(event.key) && s.selected &&
          !['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target?.tagName) && !event.target?.isContentEditable) {
        event.preventDefault(); removeSelected();
      }
    });
    document.addEventListener('mousemove', event => updateEdit(chart, s, event), true);
    window.addEventListener('mouseup', () => finishEdit(chart, s));
    window.addEventListener('blur', () => { cancelEdit(s); s.pending = null; s.preview = null; hideMenu(s); render(chart); });
    document.addEventListener('visibilitychange', () => { if (document.hidden) { cancelEdit(s); render(chart); } });
    window.addEventListener('resize', () => hideMenu(s));
    chart.mainBoard._rightTd?.dom?.addEventListener('dblclick', restore);
  }
  function attach(chart) {
    active = chart;
    if (states.has(chart) || !chart.mainBoard?._centerTopCanvas?.dom || !chart.mainBoard.rightYAxis?.axis?.tickValues) return;
    const s = {mode: 'pan', groups: new Map(), history: new Map(), nextId: 0, selected: null, hover: null,
      edit: null, pending: null, preview: null, domain: null, last: null, group: viewKey(chart), symbol: chart.symbol,
      versions:new Map(),published:new Map(),inFlight:null};
    states.set(chart, s); createUI(chart, s);
    const setRange = chart.setRange;
    if (typeof setRange === 'function') chart.setRange = function (...args) {
      stopFocus(s); s.navigation = ''; return setRange.apply(this, args);
    };
    const board = chart.mainBoard, right = board.rightYAxis, drawRight = right.draw;
    board.leftYAxis.draw = () => {};
    right.draw = function (automatic) {
      const key = rangeKey(chart), height = board.height;
      if (s.last && s.last.key !== key) s.domain = null;
      if (s.last && s.last.group === viewKey(chart) && height > 0 && height !== s.last.height) {
        const previous = s.last;
        s.domain = [previous.domain[0], previous.domain[0] + (previous.domain[1] - previous.domain[0]) * height / previous.height];
      }
      const automaticWithIndicators=validDomain(s.indicatorExtent)?[
        Math.min(automatic[0],s.indicatorExtent[0]),Math.max(automatic[1],s.indicatorExtent[1])]:automatic;
      const domain = s.domain || automaticWithIndicators;
      drawRight.call(this, domain);
      if (validDomain(domain) && height > 0) { redrawAxes(chart, domain); s.last = {key, group: viewKey(chart), height, domain: [...domain]}; }
    };
    const root = chart.tableContainer.root, canvas = board._centerTopCanvas.dom;
    root.addEventListener('contextmenu', event => {
      if (event.target !== canvas || !s.menu) return;
      const target = hit(chart, s, event);
      if (target) s.selected = target.id;
      event.preventDefault(); event.stopImmediatePropagation(); finishNative(chart); s.menu.hidden = false;
      render(chart);
      s.menu.style.left = Math.max(0, Math.min(event.clientX, (window.innerWidth || 1000) - 198)) + 'px';
      s.menu.style.top = Math.max(0, Math.min(event.clientY, (window.innerHeight || 800) - 310)) + 'px';
    }, true);
    root.addEventListener('mousedown', event => {
      if (event.target !== canvas) return;
      hideMenu(s);
      if (event.button === 0 && s.mode === 'pan') {
        stopFocus(s); s.navigation = '';
        const target = hit(chart, s, event), p = point(chart, event);
        if (!target || !p) { stopFocus(s); s.navigation = ''; s.selected = null; render(chart); return; }
        finishNative(chart); event.preventDefault(); event.stopImmediatePropagation();
        const original = drawings(chart, s).find(item => item.id === target.id);
        s.selected = target.id;
        s.edit = {...target, key: groupKey(chart), x: event.clientX, origin: p,
          original: copy([original])[0], before: copy(drawings(chart, s))};
        render(chart); return;
      }
      event.preventDefault(); event.stopImmediatePropagation();
      if (event.button !== 0) return;
      const p = point(chart, event);
      if (!p) return;
      const nextId=()=>sharedPrefix?sharedPrefix+'-'+(++s.nextId):++s.nextId;
      if (s.mode === 'horizontal') { remember(chart, s); drawings(chart, s).push(complete('horizontal', p, null, nextId())); }
      else if (!s.pending) s.pending = p;
      else { remember(chart, s); drawings(chart, s).push(complete(s.mode, s.pending, p, nextId())); s.pending = null; s.preview = null; }
      render(chart);
    }, true);
    root.addEventListener('mousemove', event => {
      if (event.target !== canvas || s.edit) return;
      if (s.mode === 'pan') {
        const target = hit(chart, s, event), id = target?.id;
        canvas.style.cursor = target ? target.handle >= 0 ? 'crosshair' : 'move' : '';
        if (id !== s.hover) { s.hover = id; render(chart); }
        return;
      }
      event.preventDefault(); event.stopImmediatePropagation(); s.preview = point(chart, event); render(chart);
    }, true);
    root.addEventListener('wheel', () => { stopFocus(s); s.navigation = ''; }, true);
  }
  function render(chart) {
    const s = states.get(chart);
    if (!s) return;
    const key = viewKey(chart);
    if (key !== s.group) {
      stopFocus(s); s.navigation = ''; cancelEdit(s); s.group = key; s.symbol = chart.symbol;
      s.mode = 'pan'; s.selected = null; s.hover = null;
      s.pending = null; s.preview = null; hideMenu(s); }
    if (key !== s.focusView) {
      if (chart.mainType === 'candle' && s.focusView && s.focusSymbol === chart.symbol && s.lastDrawingFocus)
        followDrawing(chart, s, s.lastDrawingFocus);
      s.focusView = key; s.focusSymbol = chart.symbol;
    }
    if(sharedPrefix&&!s.edit&&!s.pending&&!s.inFlight&&s.versions.has(chart.symbol)){
      const items=copy(drawings(chart,s)),encoded=JSON.stringify(items);
      if(encoded!==s.published.get(chart.symbol)){
        s.inFlight={symbol:chart.symbol,encoded,base:s.versions.get(chart.symbol)};
        window.QfNativeTools.onCommit?.({symbol:chart.symbol,version:s.inFlight.base,drawings:items});
      }
    }
    if (!s.svg) return;
    const canvas = chart.mainBoard._centerTopCanvas.dom, width = canvas.clientWidth, height = canvas.clientHeight;
    Object.assign(s.svg.style, {width: width + 'px', height: height + 'px'});
    s.svg.setAttribute('viewBox', `0 0 ${width} ${height}`); s.svg.replaceChildren();
    const geo = geometry(chart, s), items = geo.items;
    if (s.pending && s.preview) {
      const item = complete(s.mode, s.pending, s.preview, 0);
      const xy = p => ({x: position(geo.rows, p, chart) * chart.bar.step - chart.chartCtrl.pixelLeft,
        y: chart.mainBoard.rightYAxis.scale(p.price)});
      items.push({item: {...item, preview: true}, a: xy(item.points[0]), b: item.points[1] && xy(item.points[1])});
    }
    for (const g of items) {
      const {item, a, b} = g;
      if (!a || (item.type !== 'horizontal' && !b)) continue;
      const rect = item.type === 'rectangle';
      const shape = document.createElementNS('http://www.w3.org/2000/svg', rect ? 'rect' : 'line');
      const attributes = rect ? {x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), width: Math.abs(b.x - a.x), height: Math.abs(b.y - a.y), fill: '#247cac18'} :
        {x1: item.type === 'horizontal' ? 0 : a.x, y1: a.y, x2: item.type === 'horizontal' ? width : b.x, y2: item.type === 'horizontal' ? a.y : b.y};
      for (const [attr, value] of Object.entries(attributes)) shape.setAttribute(attr, value);
      shape.setAttribute('stroke', item.id === s.selected || item.id === s.hover ? '#c07813' : '#247cac'); shape.setAttribute('stroke-width', '1.5');
      if (item.preview) shape.setAttribute('stroke-dasharray', '5 4');
      s.svg.appendChild(shape);
      if (item.id === s.selected) for (const p of controls(g)) {
        const handle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        for (const [key, value] of Object.entries({cx: p.x, cy: p.y, r: 4, fill: 'white', stroke: '#c07813'})) handle.setAttribute(key, value);
        s.svg.appendChild(handle);
      }
    }
    const visibleDrawing = [...items].reverse().find(g => !g.item.preview && g.b && g.a &&
      Math.max(g.a.x, g.b.x) >= 0 && Math.min(g.a.x, g.b.x) <= width);
    s.lastDrawingFocus = visibleDrawing ? {from: Math.min(...visibleDrawing.item.points.map(p => p.time)),
      to: Math.max(...visibleDrawing.item.points.map(p => p.time)) + 1} : null;
    s.badge.hidden = s.mode === 'pan' && !s.navigation;
    s.badge.textContent = s.mode !== 'pan' ? `${names[s.mode]}：${s.pending ? '请选择第二点' : '点击图表绘制'} · 取消画图（Esc）` :
      s.navigation === 'loading' ? '正在定位画线所在日期…（点击取消）' : '该周期尚未返回画线日期的数据，画线已保留（点击关闭）';
    if (s.mode !== 'pan') canvas.style.cursor = 'crosshair';
  }
  function inspect() {
    const s = states.get(active);
    return s ? {mode: s.mode, pending: !!s.pending, selected: s.selected, editing: !!s.edit, domain: s.last?.domain,
      drawings: drawings(active, s).map(item => ({type: item.type, points: item.points.map(p => ({...p}))}))} : null;
  }
  function cancelInteraction(){
    const s=states.get(active);if(!s)return false;
    const used=s.mode!=='pan'||!!s.edit||!!s.pending||!!s.focus||!!s.navigation;
    stopFocus(s);s.navigation='';cancelEdit(s);s.pending=null;s.preview=null;s.mode='pan';
    hideMenu(s);finishNative(active);render(active);return used;
  }
  function dispose(){cancelInteraction();const s=states.get(active);if(s){s.svg?.remove();s.menu?.remove();s.badge?.remove();}}
  function exportDrawings(symbol){const s=states.get(active);return s?copy(s.groups.get(symbol)||[]):[];}
  function applyDrawings(symbol,version,items,own=false,ok=true){
    const s=states.get(active);if(!s||!Number.isSafeInteger(version)||version<(s.versions.get(symbol)||0)||!Array.isArray(items))return false;
    const flight=s.inFlight,local=s.groups.get(symbol)||[];
    if(s.versions.has(symbol)&&version===s.versions.get(symbol)&&!flight&&JSON.stringify(local)===JSON.stringify(items))return true;
    const keep=own&&ok&&flight?.symbol===symbol&&version===flight.base+1&&
      (JSON.stringify(local)!==flight.encoded||!!s.edit||!!s.pending);
    const interrupted=!own&&symbol===active.symbol&&(s.edit||s.pending||s.inFlight);
    if(symbol===active.symbol&&(!own||!ok)){stopFocus(s);cancelEdit(s);s.pending=null;s.preview=null;}
    s.inFlight=null;s.versions.set(symbol,version);s.published.set(symbol,JSON.stringify(items));
    if(!keep)s.groups.set(symbol,copy(items));
    if(interrupted)window.QfNativeTools.onConflict?.();
    if(symbol===active.symbol)render(active);return true;
  }
  window.QfNativeTools = {attach, render, select, restore, undo, clear, inspect,cancelInteraction,dispose,intervals,
    setIndicatorPriceExtent(chart,extent){const s=states.get(chart);if(s)s.indicatorExtent=validDomain(extent)?extent.slice():null;},
    exportDrawings,applyDrawings,configureShared(prefix){if(!sharedPrefix)sharedPrefix=prefix+'-'+Math.random().toString(36).slice(2,10);}};
})();
