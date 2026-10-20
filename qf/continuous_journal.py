"""连续回测账本：信号、真实合约与逻辑交易分别存证。"""

import csv
import json
import re
from dataclasses import asdict
from pathlib import Path

from qf.continuous_risk import LogicalRisk
from qf.research_account import account_schema, insert_fill_fees, normalize_fill_fees
from qf.research_config import decimal_value as dec
from qf.research_config import public_values, validate_research_config
from qf.research_journal import ResearchJournal, completed_at, dumps, research_trade_key
from qf.trade_risk import ContractSpec

CONTINUOUS_TABLES = ('signal_bars', 'main_changes', 'roll_events', 'contract_specs',
                     'logical_fills', 'logical_trades', 'continuous_order_roles')
PAYLOAD = {'signal', 'entry_plan', 'reason', 'phase', 'price', 'quote_ns', 'target_symbol',
           'role', 'symbol', 'source_symbol', 'offset', 'progress', 'fill_keys', 'failure_context'}
KINDS = {'signal', 'fill', 'protection', 'intent', 'sealed', 'reconciled', 'skipped', 'stopped',
         'roll', 'mapping', 'boundary', 'warmup', 'closed'}
ROLES = {'strategy_open', 'strategy_close', 'roll_out', 'roll_in'}
ROLL_FIELDS = {'phase', 'old_symbol', 'new_symbol', 'side', 'requested_lots',
               'started_ns', 'reason'}
PHASES = {'idle', 'old_cancel', 'old_exit', 'new_enter', 'aborting', 'frozen'}
DECIMALS = {'entry_price', 'initial_r', 'floor_gross', 'peak_gross', 'realized_gross',
            'first_offset_amount'}


def logical_from_dict(raw):
    if not isinstance(raw, dict) or set(raw) != set(LogicalRisk.__annotations__):
        raise ValueError('逻辑交易记录字段不完整')
    data = dict(raw)
    for key in DECIMALS:
        data[key] = dec(data[key])
    for key in ('side', 'quantity', 'stage', 'last_fill_ns', 'last_quote_ns'):
        if type(data[key]) is not int:
            raise ValueError('逻辑交易整数格式无效')
    if (data['side'] not in (-1, 0, 1) or data['quantity'] < 0 or data['stage'] not in (0, 1, 2)
            or min(data['last_fill_ns'], data['last_quote_ns']) < 0
            or type(data['sealed']) is not bool or not isinstance(data['trade_id'], str)
            or len(data['trade_id']) > 80 or data['initial_r'] < 0 or data['peak_gross'] < 0
            or (data['quantity'] and (not data['trade_id'] or data['side'] == 0
                                      or data['entry_price'] <= 0))
            or data['exit_reason'] is not None and not re.fullmatch(
                '[a-z][a-z0-9_]{0,79}', data['exit_reason'])):
        raise ValueError('逻辑交易状态无效')
    return LogicalRisk(**data)


class ContinuousJournal(ResearchJournal):
    def __init__(self, path):
        super().__init__(path)
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS signal_bars(seq INTEGER PRIMARY KEY,
            time_ns INTEGER UNIQUE, end_ns INTEGER, source_symbol TEXT, data TEXT);
          CREATE TABLE IF NOT EXISTS main_changes(id INTEGER PRIMARY KEY, time_ns INTEGER,
            old_symbol TEXT, new_symbol TEXT, data TEXT, UNIQUE(time_ns,new_symbol));
          CREATE TABLE IF NOT EXISTS roll_events(event_id TEXT PRIMARY KEY,
            time_ns INTEGER, phase TEXT, data TEXT);
          CREATE TABLE IF NOT EXISTS contract_specs(symbol TEXT PRIMARY KEY, data TEXT);
          CREATE TABLE IF NOT EXISTS logical_fills(fill_key TEXT PRIMARY KEY,
            trade_id TEXT, symbol TEXT, role TEXT, fee TEXT);
          CREATE TABLE IF NOT EXISTS logical_trades(trade_id TEXT PRIMARY KEY,
            time_ns INTEGER, reason TEXT);
          CREATE TABLE IF NOT EXISTS continuous_order_roles(order_id TEXT PRIMARY KEY,
            symbol TEXT, role TEXT);
          CREATE INDEX IF NOT EXISTS continuous_fill_time ON fills(time_ns);
          CREATE INDEX IF NOT EXISTS continuous_risk_time ON risk_events(time_ns);
          CREATE INDEX IF NOT EXISTS continuous_actual_time ON research_bars(symbol,time_ns);
          CREATE INDEX IF NOT EXISTS continuous_roll_time ON roll_events(time_ns);
        ''')

    @classmethod
    def create(cls, root, mode, config, metadata=None):
        cfg = validate_research_config(config.public() if hasattr(config, 'public') else config)
        allowed = {'commit', 'dirty', 'source_sha256', 'source_manifest', 'change_summary',
                   'sdk', 'timezone', 'experiment_ref'}
        if mode != 'backtest' or cfg.schema_version != 3 or set(metadata or {})-allowed:
            raise ValueError('连续账本仅支持已核对的历史回测元数据')
        j = super().create(Path(root), mode, cfg.public(), metadata)
        j.set('research_schema', 2)
        j.set('logical_risk', public_values(asdict(LogicalRisk())))
        for key in ('signal_count', 'fill_count', 'roll_count'):
            j.set(key, 0)
        return j

    def _put(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, dumps(value)))

    def _symbol(self, symbol):
        prefix = self.get('config')['continuous'][5:]
        if not isinstance(symbol, str) or not re.fullmatch(re.escape(prefix)+r'\d{3,4}', symbol):
            raise ValueError('实际合约不属于所选品种')

    def record_spec(self, symbol, spec):
        self._symbol(symbol)
        value = public_values(asdict(ContractSpec(**asdict(spec))))
        if symbol != value['symbol']:
            raise ValueError('规格与合约不一致')
        data = dumps(value)
        old = self.db.execute('SELECT data FROM contract_specs WHERE symbol=?',
                              (symbol,)).fetchone()
        if old and old[0] != data:
            raise ValueError('同一合约的已记录规格发生变化')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO contract_specs VALUES (?,?)', (symbol, data))

    def record_mapping(self, evidence):
        keys = {'changed', 'old_symbol', 'new_symbol', 'detected_ns', 'reference_ns',
                'previous_offset', 'offset'}
        if set(evidence) != keys or evidence['changed'] is not True:
            raise ValueError('历史主力映射证据无效')
        self._symbol(evidence['new_symbol'])
        if evidence['old_symbol'] is not None:
            self._symbol(evidence['old_symbol'])
        stamp = evidence['detected_ns']
        if type(stamp) is not int or stamp <= 0:
            raise ValueError('主力映射时间无效')
        dec(evidence['offset'])
        dec(evidence['previous_offset'])
        existing = self.db.execute('SELECT data FROM main_changes WHERE time_ns=? AND new_symbol=?',
            (stamp, evidence['new_symbol'])).fetchone()
        if existing:
            if existing[0] != dumps(evidence):
                raise ValueError('已经记录的主力映射内容发生变化')
            return False
        if evidence['old_symbol'] != self.get('current_symbol'):
            raise ValueError('历史主力切换顺序不一致')
        if dec(evidence['previous_offset']) != dec(self.get('signal_offset', 0)):
            raise ValueError('历史累计偏移不连续')
        if evidence['old_symbol'] is not None:
            reference = evidence['reference_ns']
            if type(reference) is not int or not 0 < reference < stamp:
                raise ValueError('换月参考时间无效')
            quotes = []
            for symbol in (evidence['old_symbol'], evidence['new_symbol']):
                saved = self.db.execute('SELECT data FROM research_bars '
                    'WHERE symbol=? AND bar_seconds=? AND time_ns=?',
                    (symbol, self.get('config')['bar_seconds'], reference)).fetchone()
                if saved is None:
                    raise ValueError('换月参考原始数据没有保存')
                raw = json.loads(saved[0])
                if (not raw['completed']
                        or completed_at(raw, self.get('config')['bar_seconds']) > stamp):
                    raise ValueError('换月参考柱在当时未完成')
                quotes.append(dec(raw['close']))
            if dec(evidence['offset']) != dec(evidence['previous_offset'])+quotes[1]-quotes[0]:
                raise ValueError('换月偏移与原始合约价格不一致')
        elif evidence['reference_ns'] is not None or dec(evidence['offset']) != 0:
            raise ValueError('首次主力映射不能带有未来调整')
        with self.db:
            cursor = self.db.execute('INSERT OR IGNORE INTO main_changes '
                '(time_ns,old_symbol,new_symbol,data) VALUES (?,?,?,?)',
                (stamp, evidence['old_symbol'], evidence['new_symbol'], dumps(evidence)))
            if cursor.rowcount:
                self._put('current_symbol', evidence['new_symbol'])
                self._put('signal_offset', evidence['offset'])
        return bool(cursor.rowcount)

    def capture_actual(self, symbol, period, rows):
        self._symbol(symbol)
        if period != self.get('config')['bar_seconds']:
            raise ValueError('实际合约周期不匹配')
        normal = [row for row in rows if 'completion_source' not in row]
        self.capture_bars(symbol, period, normal)
        for row in rows:
            if 'completion_source' in row:
                done = completed_at(row, period)
                self.capture_bars(symbol, period, [row], sdk_closed_ns=done,
                                  completion_source='SDK_3.10.2_CLOSE')

    def capture_signal(self, row):
        keys = {'open', 'high', 'low', 'close', 'datetime', 'end_ns', 'completed',
                'completed_at_ns', 'raw', 'source_symbol', 'offset', 'volume',
                'close_oi', 'trading_day'}
        if set(row)-{'completion_source'} != keys or row['completed'] is not True:
            raise ValueError('信号记录必须是明确完成的白名单柱')
        if 'completion_source' in row and row['completion_source'] != 'SDK_3.10.2_CLOSE':
            raise ValueError('信号完成证据来源无效')
        self._symbol(row['source_symbol'])
        stamp, end = row['datetime'], row['end_ns']
        if (type(stamp) is not int or type(end) is not int or stamp <= 0 or end <= stamp
                or type(row['completed_at_ns']) is not int):
            raise ValueError('信号完成时间无效')
        completed_at(row, self.get('config')['bar_seconds'])
        for key in ('open', 'high', 'low', 'close', 'offset', 'volume', 'close_oi'):
            dec(row[key])
        raw_fields = {'open', 'high', 'low', 'close', 'volume', 'close_oi', 'datetime', 'end_ns'}
        if not isinstance(row['raw'], dict) or set(row['raw']) != raw_fields:
            raise ValueError('信号原始数据包含非白名单字段')
        if (row['raw']['datetime'] != stamp or row['raw']['end_ns'] != end
                or any(dec(row['raw'][key]) <= 0
                       or dec(row[key]) != dec(row['raw'][key])-dec(row['offset'])
                       for key in ('open', 'high', 'low', 'close'))):
            raise ValueError('信号与真实价格或时间无法对应')
        data = dumps(row | {'time_ns': str(stamp)})
        existing = self.db.execute('SELECT data FROM signal_bars WHERE time_ns=?',
                                   (stamp,)).fetchone()
        if existing:
            if existing[0] != data:
                raise ValueError('已记录信号柱被改写')
            return False
        with self.db:
            seq = self.get('signal_count', 0)
            self.db.execute('INSERT INTO signal_bars VALUES (?,?,?,?,?)',
                (seq, stamp, end, row['source_symbol'], data))
            self._put('signal_count', seq+1)
        return True

    def expected_positions(self):
        return {symbol: quantity for symbol, quantity in self.db.execute(
            "SELECT symbol,sum(CASE WHEN direction='BUY' THEN volume ELSE -volume END) "
            'FROM fills GROUP BY symbol') if quantity}

    def bind_order_role(self, order_id, symbol, role):
        self._symbol(symbol)
        if role not in ROLES or order_id not in self.owned():
            raise ValueError('委托用途缺少执行所有权')
        old = self.db.execute('SELECT symbol,role FROM continuous_order_roles WHERE order_id=?',
                              (order_id,)).fetchone()
        if old is not None and old != (symbol, role):
            raise ValueError('既有委托用途不可改写')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO continuous_order_roles VALUES (?,?,?)',
                            (order_id, symbol, role))

    def commit_continuous(self, event_id, *, time_ns, kind, payload, logical_risk,
                          roll_state, fills, target=None, fill_fees=None):
        if (kind not in KINDS or not isinstance(event_id, str) or not event_id
                or type(time_ns) is not int or time_ns < 0 or set(payload)-PAYLOAD
                or (target is not None and type(target) is not int)
                or set(roll_state) != ROLL_FIELDS or roll_state['phase'] not in PHASES):
            raise ValueError('连续实验事件不在白名单内')
        risk_json = dumps(asdict(logical_risk))
        logical_from_dict(json.loads(risk_json))
        if (any(type(roll_state[key]) is not int
                for key in ('side', 'requested_lots', 'started_ns'))
                or roll_state['side'] not in (-1, 0, 1)
                or min(roll_state['requested_lots'], roll_state['started_ns']) < 0):
            raise ValueError('移仓控制状态格式无效')
        for key in ('old_symbol', 'new_symbol'):
            if roll_state[key] is not None:
                self._symbol(roll_state[key])
        pairs = []
        for fill in fills:
            self._symbol(fill['symbol'])
            key = research_trade_key(fill)
            values = (key, fill['order_id'], fill['symbol'], fill['direction'], fill['offset'],
                      fill['volume'], float(dec(fill['price'])), int(fill['time_ns']))
            if (kind != 'fill' or payload.get('role') not in ROLES
                    or fill['direction'] not in ('BUY', 'SELL')
                    or fill['offset'] not in ('OPEN', 'CLOSE', 'CLOSETODAY')
                    or type(fill['volume']) is not int or fill['volume'] <= 0
                    or dec(fill['price']) <= 0 or type(fill['time_ns']) is not int
                    or fill['time_ns'] <= 0):
                raise ValueError('连续成交格式无效')
            old = self.db.execute('SELECT * FROM fills WHERE key=?', (key,)).fetchone()
            if old and old != values:
                raise ValueError('重复成交内容发生变化')
            pairs.append((old, values))
        if any(old for old, _ in pairs):
            if not all(old for old, _ in pairs):
                raise ValueError('混合重复成交必须先去重')
            return False
        if self.db.execute('SELECT 1 FROM risk_events WHERE event_id=?', (event_id,)).fetchone():
            return False
        keys = [values[0] for _, values in pairs]
        evidence = account_schema(self.db)
        fees = normalize_fill_fees(fill_fees, keys) if evidence and fills else []
        if evidence and fills:
            expected = {}
            for _, values in pairs:
                raw = self.db.execute('SELECT data FROM contract_specs WHERE symbol=?',
                                      (values[2],)).fetchone()
                if raw is None:
                    raise ValueError('成交缺少已核实规格和费用模型')
                expected[values[0]] = (dec(json.loads(raw[0])['commission_per_lot'])
                                       * values[5])
            for entry in fees:
                if dec(entry['amount']) != dec(expected[entry['fill_key']]):
                    raise ValueError('成交费用证据与合约规格不一致')
        content = payload | ({'fill_keys': keys} if fills else {})
        with self.db:
            if (kind == 'closed' or (fills and payload.get('role') == 'strategy_close'
                                     and not logical_risk.quantity)):
                if not logical_risk.trade_id or logical_risk.quantity:
                    raise ValueError('逻辑交易终结时必须确认实际空仓')
                self.db.execute('INSERT OR IGNORE INTO logical_trades VALUES (?,?,?)',
                    (logical_risk.trade_id, time_ns,
                     logical_risk.exit_reason or payload.get('reason', 'strategy_close')))
            for _, values in pairs:
                raw = self.db.execute('SELECT data FROM contract_specs WHERE symbol=?',
                                      (values[2],)).fetchone()
                if raw is None:
                    raise ValueError('成交缺少已核实规格和费用模型')
                fee = dec(json.loads(raw[0])['commission_per_lot'])*values[5]
                self.db.execute('INSERT INTO fills VALUES (?,?,?,?,?,?,?,?)', values)
                self.db.execute('INSERT INTO logical_fills VALUES (?,?,?,?,?)',
                    (values[0], logical_risk.trade_id, values[2], payload['role'], str(fee)))
            if fees:
                insert_fill_fees(self.db, fees)
            self.db.execute('INSERT INTO risk_events VALUES (?,?,?,?,?,?)',
                (event_id, time_ns, kind, dumps(content), risk_json, target))
            roll_data = dumps(dict(roll=roll_state, payload=content))
            self.db.execute('INSERT INTO roll_events VALUES (?,?,?,?)',
                (event_id, time_ns, roll_state['phase'], roll_data))
            self._put('logical_risk', json.loads(risk_json))
            self._put('roll_state', roll_state)
            if fills:
                self._put('fill_count', self.get('fill_count', 0)+len(fills))
            if target is not None:
                self._put('last_target', target)
        return True

    def export(self):
        super().export()
        tables = CONTINUOUS_TABLES
        for table in tables:
            cursor = self.db.execute(f'SELECT * FROM {table}')
            with (self.path/f'{table}.csv').open('w', newline='', encoding='utf-8-sig') as out:
                writer = csv.writer(out)
                writer.writerow([item[0] for item in cursor.description])
                writer.writerows(cursor)
