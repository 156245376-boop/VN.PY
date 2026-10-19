"""唯一执行线程读取已提交记录，生成有界的独立展示副本。"""

import json

import pandas as pd
from tqsdk.tafunc import ma

from qf.research_config import public_values


def view_snapshot(journal, config, quote, *, now, revision, progress, terminal=False):
    bars = [json.loads(row[0]) for row in reversed(journal.db.execute(
        'SELECT data FROM research_bars WHERE time_ns<=? ORDER BY time_ns DESC LIMIT 500',
        (now,)).fetchall())]
    first = int(bars[0]['time_ns']) if bars else now
    events = [dict(time_ns=str(r[0]), kind=r[1], payload=json.loads(r[2]), risk=json.loads(r[3]))
              for r in reversed(journal.db.execute(
                  'SELECT time_ns,kind,payload,risk FROM risk_events WHERE time_ns BETWEEN ? AND ? '
                  'ORDER BY time_ns DESC,rowid DESC LIMIT 5000', (first, now)).fetchall())]
    fills = [dict(zip(('key', 'order_id', 'symbol', 'direction', 'offset', 'volume',
                       'price', 'time_ns'), r, strict=True)) for r in reversed(journal.db.execute(
        'SELECT * FROM fills WHERE time_ns BETWEEN ? AND ? '
        'ORDER BY time_ns DESC,rowid DESC LIMIT 5000', (first, now)).fetchall())]
    for fill in fills:
        fill['time_ns'] = str(fill['time_ns'])
    lines = []
    for period in (config.fast_period, config.slow_period):
        values = ma(pd.Series([b['close'] for b in bars], dtype=float), period)
        lines.append(dict(period=period, points=[dict(id=i, time_ns=bars[i]['time_ns'], value=v)
            for i, v in enumerate(values) if pd.notna(v)]))
    safe_quote = {key: getattr(quote, key) for key in ('datetime', 'last_price', 'price_tick',
        'price_decs', 'volume_multiple', 'instrument_name') if hasattr(quote, key)}
    return public_values(dict(run_id=journal.path.name, revision=revision, as_of_ns=str(now),
        symbol=config.symbol, bar_seconds=config.bar_seconds, config=config.public(),
        contract_spec=journal.get('contract_spec', {}), quote=safe_quote, bars=bars,
        ma_series=lines, fills=fills, risk_events=events, entry_plan=journal.get('entry_plan'),
        progress=progress, terminal=terminal, display_limit=dict(bars=500, events=5000)))
