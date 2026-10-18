"""实验记录：成交、风险状态与执行意图在同一SQLite事务落盘。"""

import csv
import hashlib
import json
from dataclasses import asdict

from tqsdk.datetime import _get_trading_day_end_time, _get_trading_day_from_timestamp

from qf.journal import Journal
from qf.research_config import decimal_value, public_values
from qf.trade_risk import RiskState

PAYLOAD_FIELDS = {'signal', 'sizing', 'reason', 'phase', 'price', 'quote_ns', 'cost_source',
                  'price_tick', 'volume_multiple', 'commission_per_lot', 'margin_per_lot'}
KINDS = {'signal', 'fill', 'protection', 'intent', 'sealed', 'reconciled', 'skipped', 'stopped'}
DECIMALS = {'entry_price', 'initial_r', 'stop_price', 'peak_gross'}


def risk_from_dict(raw):
    if not isinstance(raw, dict) or set(raw) != set(RiskState.__annotations__):
        raise ValueError('风险状态不完整')
    data = dict(raw)
    for key in DECIMALS:
        data[key] = decimal_value(data[key])
    for key in ('quantity', 'side', 'stage', 'last_quote_ns', 'last_fill_ns'):
        if type(data[key]) is not int:
            raise ValueError('风险状态格式无效')
    if (data['quantity'] < 0 or data['side'] not in (-1, 0, 1)
            or type(data['sealed']) is not bool or data['stage'] not in (0, 1, 2)):
        raise ValueError('风险状态格式无效')
    return RiskState(**data)


def research_trade_key(fill):
    identity = [fill['symbol'], fill['order_id'], fill['key'], str(fill['time_ns'])]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def dumps(value):
    return json.dumps(public_values(value), ensure_ascii=False, allow_nan=False)


class ResearchJournal(Journal):
    def __init__(self, path):
        super().__init__(path)
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS risk_events(event_id TEXT PRIMARY KEY, time_ns INTEGER,
            kind TEXT, payload TEXT, risk TEXT, target INTEGER);
          CREATE TABLE IF NOT EXISTS research_bars(symbol TEXT, bar_seconds INTEGER,
            time_ns INTEGER, data TEXT, PRIMARY KEY(symbol,bar_seconds,time_ns));
        ''')
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO state VALUES ('research_schema','1')")

    def load_risk(self):
        raw = self.get('risk_state')
        return risk_from_dict(raw) if raw is not None else RiskState()

    def has_fill(self, fill):
        return self.db.execute('SELECT 1 FROM fills WHERE key=?',
                               (research_trade_key(fill),)).fetchone() is not None

    def commit_update(self, event_id, *, time_ns, kind, payload, risk_state, fills, target=None):
        if (kind not in KINDS or not isinstance(event_id, str) or not event_id
                or type(time_ns) is not int or time_ns < 0 or set(payload)-PAYLOAD_FIELDS
                or (target is not None and type(target) is not int)):
            raise ValueError('研究事件格式无效')
        if self.db.execute('SELECT 1 FROM risk_events WHERE event_id=?', (event_id,)).fetchone():
            return False
        if fills and any(self.has_fill(fill) for fill in fills):
            if not all(self.has_fill(fill) for fill in fills):
                raise ValueError('混合重复成交须先核实')
            return False
        risk_json = dumps(asdict(risk_state))
        risk_from_dict(json.loads(risk_json))
        with self.db:
            for fill in fills:
                self.db.execute('INSERT INTO fills VALUES (?,?,?,?,?,?,?,?)', (
                    research_trade_key(fill), fill['order_id'], fill['symbol'], fill['direction'],
                    fill['offset'], fill['volume'], float(fill['price']), int(fill['time_ns'])))
            self.db.execute('INSERT INTO risk_events VALUES (?,?,?,?,?,?)',
                            (event_id, time_ns, kind, dumps(payload), risk_json, target))
            self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', ('risk_state', risk_json))
            if target is not None:
                self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',
                                ('last_target', json.dumps(target)))
        return True

    def capture_bars(self, symbol, bar_seconds, rows, *, completed=True):
        values = []
        for row in rows:
            stamp = int(row['datetime'])
            fields = ('open', 'high', 'low', 'close', 'volume', 'close_oi')
            data = {k: float(row[k]) for k in fields}
            data.update(time_ns=str(stamp), completed=completed)
            end = (_get_trading_day_end_time(_get_trading_day_from_timestamp(stamp))
                   if bar_seconds == 86400 else stamp+bar_seconds*1_000_000_000)
            data['end_ns'] = str(end)
            if stamp <= 0 or min(data[k] for k in ('open', 'high', 'low', 'close')) <= 0:
                raise ValueError('K线无效')
            values.append((symbol, bar_seconds, stamp, dumps(data)))
        with self.db:
            self.db.executemany('''INSERT INTO research_bars VALUES (?,?,?,?)
                ON CONFLICT(symbol,bar_seconds,time_ns) DO UPDATE SET data=excluded.data
                WHERE COALESCE(json_extract(research_bars.data,'$.completed'),1)=0''', values)

    def load_replay(self, *, offset, limit):
        if (type(offset) is not int or offset < 0
                or type(limit) is not int or not 1 <= limit <= 10000):
            raise ValueError('复盘分页无效')
        bars = [json.loads(r[0]) for r in self.db.execute(
            'SELECT data FROM research_bars ORDER BY time_ns LIMIT ? OFFSET ?', (limit, offset))]
        events = [dict(event_id=r[0], time_ns=str(r[1]), kind=r[2], payload=json.loads(r[3]),
                       risk=json.loads(r[4]), target=r[5]) for r in self.db.execute(
                           'SELECT * FROM risk_events ORDER BY time_ns,rowid')]
        fills = [dict(zip(('key', 'order_id', 'symbol', 'direction', 'offset', 'volume',
                          'price', 'time_ns'), row, strict=True))
                 for row in self.db.execute('SELECT * FROM fills ORDER BY time_ns,rowid')]
        for fill in fills:
            fill['time_ns'] = str(fill['time_ns'])
        count = self.db.execute('SELECT count(*) FROM research_bars').fetchone()[0]
        return dict(bars=bars, risk_events=events, fills=fills, total_bars=count,
                    offset=offset, next_offset=offset+len(bars))

    def export(self):
        tables = ('signals', 'fills', 'orders', 'equity', 'events', 'risk_events', 'research_bars')
        for table in tables:
            cursor = self.db.execute(f'SELECT * FROM {table}')
            with (self.path / f'{table}.csv').open('w', newline='', encoding='utf-8-sig') as out:
                writer = csv.writer(out)
                writer.writerow([d[0] for d in cursor.description])
                writer.writerows(cursor)
        text = ('# 双均线实验记录\n\n精度：'+self.get('config')['precision']
                +'；费用与保证金为SDK模型，非历史真实成本。\n\n'
                +'阶段保护按已观察报价触发，不保证保护价成交；期末持仓未自动平仓。\n\n'
                +f"状态：{self.get('status')}；原因：{self.get('reason')}。\n")
        (self.path / 'report.md').write_text(text, encoding='utf-8')
