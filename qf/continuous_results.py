"""连续回测只读结果与索引分页；绝不创建行情会话。"""

import json
import sqlite3
from contextlib import closing
from decimal import Decimal

import pandas as pd
from tqsdk.tafunc import ma

from qf.continuous_journal import logical_from_dict
from qf.continuous_risk import logical_stop
from qf.research_config import decimal_value as dec
from qf.research_config import public_values, validate_research_config
from qf.research_journal import integrity_manifest
from qf.trade_risk import ContractSpec


def schema_at(path):
    with closing(sqlite3.connect((path/'journal.sqlite3').as_uri()+'?mode=ro', uri=True)) as db:
        row = db.execute("SELECT value FROM state WHERE key='research_schema'").fetchone()
        return json.loads(row[0]) if row else None


class ContinuousReader:
    """调用方先校验完整性；每页单独只读事务，关闭的运行文件不会变化。"""
    def __init__(self, path):
        self.path = path

    def connect(self):
        return sqlite3.connect((self.path/'journal.sqlite3').as_uri()+'?mode=ro', uri=True)

    @staticmethod
    def _selection(db, series, symbol):
        if series == 'signal' and symbol is None:
            return 'signal_bars', '', ()
        if series == 'actual' and isinstance(symbol, str):
            if db.execute('SELECT 1 FROM research_bars WHERE symbol=? LIMIT 1',
                          (symbol,)).fetchone():
                return 'research_bars', 'WHERE symbol=?', (symbol,)
        raise ValueError('请选择信号连续图或保存过的实际合约')

    def bars(self, offset, limit, *, series='signal', symbol=None):
        if (type(offset) is not int or offset < 0 or type(limit) is not int
                or not 1 <= limit <= 10000):
            raise ValueError('复盘分页范围无效')
        with closing(self.connect()) as db:
            table, where, params = self._selection(db, series, symbol)
            total = db.execute(f'SELECT count(*) FROM {table} {where}', params).fetchone()[0]
            rows = db.execute(f'SELECT data FROM {table} {where} ORDER BY time_ns '
                              'LIMIT ? OFFSET ?', (*params, limit, offset)).fetchall()
            bars = [json.loads(row[0]) | {'global_id': offset+i} for i, row in enumerate(rows)]
        return dict(bars=bars, total_bars=total, offset=offset, next_offset=offset+len(bars),
                    series=series, actual_symbol=symbol)

    def initial(self, *, series='signal', symbol=None):
        with closing(self.connect()) as db:
            table, where, params = self._selection(db, series, symbol)
            count = db.execute(f'SELECT count(*) FROM {table} {where}', params).fetchone()[0]
        return self.bars(max(0, count-2000), 2000, series=series, symbol=symbol)

    def locate(self, time_ns, *, series, symbol=None):
        stamp = int(time_ns)
        with closing(self.connect()) as db:
            table, where, params = self._selection(db, series, symbol)
            condition = where + (' AND ' if where else 'WHERE ')
            count = db.execute(f'SELECT count(*) FROM {table} {condition}time_ns<=?',
                               (*params, stamp)).fetchone()[0]
        index = max(0, count-1)
        return (self.bars(max(0, index-1000), 2000, series=series, symbol=symbol)
                | {'global_id': index})

    def window(self, offset, limit, *, series='signal', symbol=None):
        page = self.bars(offset, limit, series=series, symbol=symbol)
        warmup = 0
        with closing(self.connect()) as db:
            state = {k: json.loads(v) for k, v in db.execute('SELECT * FROM state')}
            config = validate_research_config(state['config'])
            warmup = config.slow_period
        prefix = self.bars(max(0, offset-warmup), min(10000, limit+min(warmup, offset)),
                           series=series, symbol=symbol)['bars']
        lines = []
        for period in (config.fast_period, config.slow_period):
            values = ma(pd.Series([float(b['close']) for b in prefix], dtype=float), period)
            lines.append(dict(period=period, points=[dict(id=b['global_id'],
                time_ns=b['time_ns'], value=float(value))
                for b, value in zip(prefix, values, strict=True)
                if b['global_id'] >= offset and pd.notna(value)]))
        bars = page['bars']
        if bars:
            with closing(self.connect()) as db:
                evidence = _evidence(db, int(bars[0]['time_ns']), int(bars[-1]['end_ns']),
                                     series=series, symbol=symbol)
        else:
            evidence = dict(fills=[], risk_events=[], main_changes=[])
        return page | evidence | dict(ma_series=lines, first_bar_id=offset)


def _spec(raw):
    data = dict(raw)
    for key in ('price_tick', 'volume_multiple', 'margin_per_lot', 'commission_per_lot'):
        data[key] = dec(data[key])
    return ContractSpec(**data)


def _evidence(db, first, now, *, series='signal', symbol=None):
    mappings = [(r[0], json.loads(r[1])) for r in db.execute(
        'SELECT time_ns,data FROM main_changes ORDER BY time_ns')]
    def offset_at(stamp, actual_symbol):
        value = Decimal(0)
        for time_ns, mapping in mappings:
            if time_ns > stamp:
                break
            if mapping['new_symbol'] == actual_symbol:
                value = dec(mapping['offset'])
        return value if series == 'signal' else Decimal(0)
    fills = []
    for row in db.execute('SELECT f.*,l.trade_id,l.role,l.fee FROM fills f JOIN logical_fills l '
                         'ON l.fill_key=f.key WHERE f.time_ns BETWEEN ? AND ? '
                         'ORDER BY f.time_ns DESC,f.rowid DESC LIMIT 5000', (first, now)):
        if series == 'actual' and row[2] != symbol:
            continue
        fill = dict(zip(('key', 'order_id', 'symbol', 'direction', 'offset', 'volume',
                         'price', 'time_ns', 'trade_id', 'role', 'fee'), row, strict=True))
        fill['time_ns'] = str(fill['time_ns'])
        fill['display_price'] = dec(fill['price'])-offset_at(row[7], fill['symbol'])
        fills.append(fill)
    specs = {s: _spec(json.loads(raw)) for s, raw in db.execute('SELECT * FROM contract_specs')}
    events = []
    for stamp, kind, payload, raw in db.execute(
            'SELECT time_ns,kind,payload,risk FROM risk_events WHERE time_ns BETWEEN ? AND ? '
            'ORDER BY time_ns DESC,rowid DESC LIMIT 5000', (first, now)):
        risk = logical_from_dict(json.loads(raw))
        content = json.loads(payload)
        actual = content.get('symbol') or content.get('source_symbol')
        if actual is None:
            actual = next((m['new_symbol'] for time_ns, m in reversed(mappings)
                           if time_ns <= stamp), None)
        risk_data = json.loads(raw)
        if actual in specs and risk.quantity:
            stop = logical_stop(risk, spec=specs[actual])
            risk_data.update(actual_stop_price=stop, stop_price=stop-offset_at(stamp, actual))
        if series == 'signal' or actual == symbol:
            events.append(dict(time_ns=str(stamp), kind=kind, payload=content, risk=risk_data))
    return public_values(dict(fills=list(reversed(fills)), risk_events=list(reversed(events)),
        main_changes=[dict(m, time_ns=str(t)) for t, m in mappings if first <= t <= now]))


def read_continuous_run(root, run_id, *, details=False):
    from qf.research_results import run_path
    path = run_path(root, run_id)
    try:
        with closing(ContinuousReader(path).connect()) as db:
            db.execute('BEGIN')
            state = {k: json.loads(v) for k, v in db.execute('SELECT * FROM state')}
            config = validate_research_config(state['config'])
            if config.schema_version != 3 or state.get('research_schema') != 2:
                raise ValueError('连续实验版本不一致')
            logical_from_dict(state['logical_risk'])
            if state.get('research_integrity') != integrity_manifest(db):
                raise ValueError('连续实验完整性校验失败')
            missing = db.execute('SELECT 1 FROM fills f LEFT JOIN logical_fills l '
                'ON f.key=l.fill_key LEFT JOIN contract_specs c ON c.symbol=f.symbol '
                'WHERE l.fill_key IS NULL OR l.symbol!=f.symbol '
                'OR c.symbol IS NULL LIMIT 1').fetchone()
            if missing:
                raise ValueError('连续成交关联不完整')
            linked = []
            for kind, raw, risk in db.execute('SELECT kind,payload,risk FROM risk_events'):
                logical_from_dict(json.loads(risk))
                if kind == 'fill':
                    linked.extend(json.loads(raw).get('fill_keys', []))
            if sorted(linked) != sorted(r[0] for r in db.execute('SELECT key FROM fills')):
                raise ValueError('成交事件关联不完整')
            span = db.execute('SELECT min(time_ns),max(time_ns),count(*) '
                              'FROM signal_bars').fetchone()
            symbols = [r[0] for r in db.execute(
                'SELECT symbol FROM contract_specs ORDER BY symbol')]
            result = dict(run_id=run_id, config=config.public(),
                status=state.get('status', 'created'),
                reason=state.get('reason'), fee_multiplier=state.get('fee_multiplier', 1),
                risk=state['logical_risk'], experiment_ref=state.get('experiment_ref'),
                cost_source='SDK模拟模型（逐合约记录，非历史真实成本）', precision=config.precision,
                coverage_check=state.get('coverage_check'), actual_symbols=symbols,
                coverage=dict(first_ns=str(span[0]) if span[0] else None,
                              last_ns=str(span[1]) if span[1] else None, bars=span[2]))
    except (OSError, KeyError, TypeError, sqlite3.Error, ValueError):
        raise ValueError('连续实验文件缺失、版本不支持或记录不完整') from None
    if details:
        page = ContinuousReader(path).initial()
        result.update(ContinuousReader(path).window(page['offset'], 2000))
    return result


def summarize_continuous_run(root, run_id):
    from qf.research_results import run_path
    result = read_continuous_run(root, run_id)
    with closing(ContinuousReader(run_path(root, run_id)).connect()) as db:
        state = {k: json.loads(v) for k, v in db.execute('SELECT * FROM state')}
        initial = dec(state.get('initial_equity', result['config']['initial_balance']))
        equity = [dec(r[0]) for r in db.execute('SELECT balance FROM equity ORDER BY time_ns')]
        final = state.get('sdk_statistics', {}).get('end_balance', equity[-1] if equity else None)
        fee = state.get('total_commission', state.get('sdk_statistics', {}).get('commission'))
        fees = [dec(r[0]) for r in db.execute(
            "SELECT fee FROM logical_fills WHERE role IN ('roll_in','roll_out')")]
        # 平旧换新期间数量暂时为零，不是逻辑交易结束；只统计最终策略退出。
        closed = db.execute("SELECT count(*) FROM (SELECT l.trade_id FROM logical_fills l "
            "JOIN fills f ON f.key=l.fill_key GROUP BY l.trade_id HAVING "
            "sum(CASE WHEN f.offset='OPEN' THEN f.volume ELSE -f.volume END)=0 "
            "AND sum(CASE WHEN l.role='strategy_close' THEN 1 ELSE 0 END)>0)").fetchone()[0]
        count = db.execute('SELECT count(*) FROM fills').fetchone()[0]
        actual = state.get('final_positions')
        peak, drawdown, pct = initial, Decimal(0), Decimal(0)
        for value in [*equity, *([dec(final)] if final is not None else [])]:
            peak = max(peak, value)
            drawdown = max(drawdown, peak-value)
            if peak > 0:
                pct = max(pct, (peak-value)/peak*100)
        net = dec(final)-initial if final is not None else None
    return public_values(result | dict(final_equity=final, net_pnl=net, commission=fee,
        gross_pnl=net+dec(fee) if net is not None and fee is not None else None,
        roll_commission=sum(fees, Decimal(0)), roll_count=state.get('roll_count', 0),
        closed_trade_count=closed, fill_count=count,
        max_drawdown_amount=drawdown if equity else None,
        max_drawdown_pct=pct if equity else None, account_positions=actual,
        open_position=(sum(pair[0]-pair[1] for pair in actual.values())
                       if actual is not None else None),
        position_source='account' if actual is not None else 'local_fills_unconfirmed'))


def continuous_snapshot(journal, config, quote, *, now, revision, progress, terminal=False):
    prefix = [json.loads(r[1]) | {'global_id': r[0]} for r in reversed(journal.db.execute(
        'SELECT seq,data FROM signal_bars WHERE time_ns<=? ORDER BY time_ns DESC LIMIT ?',
        (now, 500+config.slow_period)).fetchall())]
    bars = prefix[-500:]
    first_id = bars[0]['global_id'] if bars else 0
    lines = []
    for period in (config.fast_period, config.slow_period):
        values = ma(pd.Series([float(b['close']) for b in prefix], dtype=float), period)
        lines.append(dict(period=period, points=[dict(id=b['global_id'], time_ns=b['time_ns'],
            value=float(v)) for b, v in zip(prefix, values, strict=True)
            if b['global_id'] >= first_id and pd.notna(v)]))
    evidence = _evidence(journal.db, int(bars[0]['time_ns']) if bars else now, now)
    spec_raw = journal.db.execute('SELECT data FROM contract_specs WHERE symbol=?',
                                 (journal.get('current_symbol'),)).fetchone()
    safe_quote = {key: getattr(quote, key) for key in ('datetime', 'price_tick', 'price_decs',
                 'volume_multiple', 'instrument_name') if hasattr(quote, key)}
    if bars:
        safe_quote['last_price'] = bars[-1]['close']
    return public_values(evidence | dict(run_id=journal.path.name, revision=revision,
        as_of_ns=str(now), symbol=config.continuous, bar_seconds=config.bar_seconds,
        config=config.public(), bars=bars, ma_series=lines, quote=safe_quote,
        entry_plan=journal.get('entry_plan'),
        contract_spec=json.loads(spec_raw[0]) if spec_raw else {}, first_bar_id=first_id,
        progress=progress, terminal=terminal, display_limit=dict(bars=500, events=5000)))
