"""规范化历史数据SQLite存储；网络获取和策略执行不在此模块。"""

import hashlib
import json
import math
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

import pandas as pd

from qf.data_catalog import SYMBOL, CoverageReport, DataRequest
from qf.research_config import decimal_value as dec


class HistoryStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root/'history.sqlite3'
        with closing(self.connect()) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS data_sets(
                    dataset_id TEXT PRIMARY KEY, request_json TEXT NOT NULL,
                    source TEXT NOT NULL, capability_json TEXT NOT NULL,
                    status TEXT NOT NULL, sha256 TEXT);
                CREATE TABLE IF NOT EXISTS instruments(
                    dataset_id TEXT NOT NULL, symbol TEXT NOT NULL, data TEXT NOT NULL,
                    PRIMARY KEY(dataset_id,symbol));
                CREATE TABLE IF NOT EXISTS bars(
                    dataset_id TEXT NOT NULL, symbol TEXT NOT NULL, duration INTEGER NOT NULL,
                    time_ns INTEGER NOT NULL, open REAL NOT NULL, high REAL NOT NULL,
                    low REAL NOT NULL, close REAL NOT NULL, volume REAL NOT NULL,
                    close_oi REAL NOT NULL, completed INTEGER NOT NULL,
                    PRIMARY KEY(dataset_id,symbol,duration,time_ns));
                CREATE TABLE IF NOT EXISTS main_changes(
                    dataset_id TEXT NOT NULL, time_ns INTEGER NOT NULL,
                    old_symbol TEXT, new_symbol TEXT NOT NULL, offset TEXT NOT NULL,
                    reference_ns INTEGER, PRIMARY KEY(dataset_id,time_ns,new_symbol));
                CREATE TABLE IF NOT EXISTS coverage(
                    dataset_id TEXT PRIMARY KEY, data TEXT NOT NULL);
            ''')

    def connect(self):
        db = sqlite3.connect(self.path)
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=NORMAL')
        db.execute('PRAGMA foreign_keys=ON')
        return db

    @staticmethod
    def _dataset_id(request):
        return hashlib.sha256(request.key().encode('utf-8')).hexdigest()[:32]

    def create_dataset(self, request, source, capability):
        request.validate()
        capability.validate()
        if not isinstance(source, str) or not source or len(source) > 100:
            raise ValueError('数据来源无效')
        dataset_id = self._dataset_id(request)
        request_json = json.dumps(request.public(), ensure_ascii=False, sort_keys=True)
        capability_json = json.dumps(capability.public(), ensure_ascii=False,
                                     sort_keys=True)
        with closing(self.connect()) as db, db:
            old = db.execute(
                'SELECT request_json,source,capability_json FROM data_sets WHERE dataset_id=?',
                (dataset_id,)).fetchone()
            if old is not None and old != (request_json, source, capability_json):
                raise ValueError('相同数据请求的已存来源或权限证据不一致')
            db.execute(
                'INSERT OR IGNORE INTO data_sets VALUES (?,?,?,?,?,NULL)',
                (dataset_id, request_json, source, capability_json, 'created'))
        return dataset_id

    def _dataset(self, db, dataset_id):
        row = db.execute(
            'SELECT request_json FROM data_sets WHERE dataset_id=?',
            (dataset_id,)).fetchone()
        if row is None:
            raise ValueError('数据集不存在')
        return DataRequest.from_public(json.loads(row[0]))

    @staticmethod
    def _finite(value, name, *, positive=False):
        value = dec(value)
        result = float(value)
        if not math.isfinite(result) or result < 0 or positive and result <= 0:
            raise ValueError(f'{name}无效')
        return result

    def _bar(self, request, row):
        if not isinstance(row, dict):
            raise ValueError('K线行无效')
        symbol = row.get('symbol', request.symbol)
        if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol):
            raise ValueError('K线合约无效')
        duration = row.get('duration', request.bar_seconds)
        stamp = row.get('time_ns')
        completed = row.get('completed', True)
        if type(duration) is not int or duration != request.bar_seconds:
            raise ValueError('K线周期与数据集不一致')
        if type(stamp) is not int or stamp <= 0 or type(completed) is not bool:
            raise ValueError('K线时间或完成标记无效')
        ohlc = {
            key: self._finite(row.get(key), key, positive=True)
            for key in ('open', 'high', 'low', 'close')
        }
        if (ohlc['high'] < max(ohlc['open'], ohlc['close'], ohlc['low'])
                or ohlc['low'] > min(ohlc['open'], ohlc['close'], ohlc['high'])):
            raise ValueError('K线OHLC无效')
        return (
            symbol, duration, stamp, ohlc['open'], ohlc['high'], ohlc['low'],
            ohlc['close'], self._finite(row.get('volume', 0), 'volume'),
            self._finite(row.get('close_oi', 0), 'close_oi'), int(completed))

    def write_bars(self, dataset_id, rows):
        if not isinstance(rows, list):
            raise ValueError('K线行必须为列表')
        with closing(self.connect()) as db, db:
            request = self._dataset(db, dataset_id)
            prepared, seen = [], set()
            inserted = 0
            for raw in rows:
                values = self._bar(request, raw)
                key = values[:3]
                if key in seen:
                    previous = next(item for item in prepared if item[:3] == key)
                    if previous != values:
                        raise ValueError('同一批K线重复内容不一致')
                    continue
                seen.add(key)
                old = db.execute(
                    'SELECT symbol,duration,time_ns,open,high,low,close,volume,'
                    'close_oi,completed FROM bars WHERE dataset_id=? AND '
                    'symbol=? AND duration=? AND time_ns=?',
                    (dataset_id, values[0], values[1], values[2])).fetchone()
                if old is not None and tuple(old) != values:
                    raise ValueError('既有K线内容发生变化')
                if old is None:
                    prepared.append(values)
            db.executemany(
                'INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                [(dataset_id, *values) for values in prepared])
            inserted = len(prepared)
            db.execute("UPDATE data_sets SET status='writing' WHERE dataset_id=?",
                       (dataset_id,))
        return inserted

    def write_instruments(self, dataset_id, rows):
        with closing(self.connect()) as db, db:
            self._dataset(db, dataset_id)
            for row in rows:
                if not isinstance(row, dict) or not SYMBOL.fullmatch(row.get('symbol', '')):
                    raise ValueError('合约规格无效')
                data = {key: row[key] for key in (
                    'symbol', 'price_tick', 'volume_multiple', 'margin_per_lot',
                    'commission_per_lot') if key in row}
                if set(data) != {'symbol', 'price_tick', 'volume_multiple',
                                 'margin_per_lot', 'commission_per_lot'}:
                    raise ValueError('合约规格字段不完整')
                data['price_tick'] = str(dec(data['price_tick']))
                data['volume_multiple'] = str(dec(data['volume_multiple']))
                data['margin_per_lot'] = str(dec(data['margin_per_lot']))
                data['commission_per_lot'] = str(dec(data['commission_per_lot']))
                raw = json.dumps(data, ensure_ascii=False, sort_keys=True)
                old = db.execute(
                    'SELECT data FROM instruments WHERE dataset_id=? AND symbol=?',
                    (dataset_id, data['symbol'])).fetchone()
                if old is not None and old[0] != raw:
                    raise ValueError('既有合约规格发生变化')
                db.execute('INSERT OR IGNORE INTO instruments VALUES (?,?,?)',
                           (dataset_id, data['symbol'], raw))
        return len(rows)

    def write_mapping(self, dataset_id, rows):
        with closing(self.connect()) as db, db:
            self._dataset(db, dataset_id)
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError('历史主力映射无效')
                old_symbol, new_symbol = row.get('old_symbol'), row.get('new_symbol')
                if (old_symbol is not None
                        and (not isinstance(old_symbol, str)
                             or not SYMBOL.fullmatch(old_symbol))) or (
                        not isinstance(new_symbol, str) or not SYMBOL.fullmatch(new_symbol)):
                    raise ValueError('历史主力合约无效')
                stamp, reference = row.get('time_ns'), row.get('reference_ns')
                if (type(stamp) is not int or stamp <= 0
                        or reference is not None
                        and (type(reference) is not int or not 0 < reference < stamp)):
                    raise ValueError('历史主力映射时间无效')
                offset = str(dec(row.get('offset')))
                values = (old_symbol, new_symbol, offset, reference)
                old = db.execute(
                    'SELECT old_symbol,new_symbol,offset,reference_ns FROM main_changes '
                    'WHERE dataset_id=? AND time_ns=? AND new_symbol=?',
                    (dataset_id, stamp, new_symbol)).fetchone()
                if old is not None and tuple(old) != values:
                    raise ValueError('既有历史主力映射发生变化')
                db.execute('INSERT OR IGNORE INTO main_changes VALUES (?,?,?,?,?,?)',
                           (dataset_id, stamp, *values))
        return len(rows)

    def write_coverage(self, dataset_id, report):
        report.validate()
        with closing(self.connect()) as db, db:
            self._dataset(db, dataset_id)
            db.execute('INSERT OR REPLACE INTO coverage VALUES (?,?)',
                       (dataset_id, json.dumps(report.public(), ensure_ascii=False,
                                               sort_keys=True)))
            db.execute("UPDATE data_sets SET status=? WHERE dataset_id=?",
                       ('ready' if report.complete() else 'incomplete', dataset_id))

    def set_status(self, dataset_id, status):
        if status not in {'created', 'writing', 'ready', 'incomplete', 'cancelled', 'failed'}:
            raise ValueError('数据集状态无效')
        with closing(self.connect()) as db, db:
            self._dataset(db, dataset_id)
            db.execute('UPDATE data_sets SET status=? WHERE dataset_id=?',
                       (status, dataset_id))

    def coverage(self, dataset_id):
        with closing(self.connect()) as db:
            self._dataset(db, dataset_id)
            row = db.execute('SELECT data FROM coverage WHERE dataset_id=?',
                             (dataset_id,)).fetchone()
            if row is None:
                raise ValueError('数据集尚未保存覆盖证据')
            raw = json.loads(row[0])
            return CoverageReport(
                expected_days=[date.fromisoformat(value) for value in raw['expected_days']],
                observed_days=[date.fromisoformat(value) for value in raw['observed_days']],
                issues=list(raw['issues']))

    def load_bars(self, dataset_id, *, symbol=None):
        with closing(self.connect()) as db:
            self._dataset(db, dataset_id)
            if symbol is None:
                return pd.read_sql_query(
                    'SELECT symbol,duration,time_ns,open,high,low,close,volume,'
                    'close_oi,completed FROM bars WHERE dataset_id=? '
                    'ORDER BY time_ns,symbol', db, params=(dataset_id,))
            return pd.read_sql_query(
                'SELECT symbol,duration,time_ns,open,high,low,close,volume,'
                'close_oi,completed FROM bars WHERE dataset_id=? AND symbol=? '
                'ORDER BY time_ns', db, params=(dataset_id, symbol))

    def load_instruments(self, dataset_id):
        with closing(self.connect()) as db:
            self._dataset(db, dataset_id)
            return [json.loads(row[0]) for row in db.execute(
                'SELECT data FROM instruments WHERE dataset_id=? ORDER BY symbol',
                (dataset_id,))]

    def load_mapping(self, dataset_id):
        with closing(self.connect()) as db:
            self._dataset(db, dataset_id)
            return [dict(zip(('time_ns', 'old_symbol', 'new_symbol', 'offset',
                              'reference_ns'), row, strict=True))
                    for row in db.execute(
                        'SELECT time_ns,old_symbol,new_symbol,offset,reference_ns '
                        'FROM main_changes WHERE dataset_id=? ORDER BY time_ns,new_symbol',
                        (dataset_id,))]
