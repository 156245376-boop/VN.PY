"""历史主力信号的因果向前价差调整；原始合约价格不改写。"""

import copy
from collections import deque
from decimal import Decimal

from tqsdk.datetime import _get_trading_day_from_timestamp, _timestamp_nano_to_str

from qf.research_config import decimal_value as dec
from qf.research_journal import bar_end_ns, completed_at

PRICE_FIELDS = ('open', 'high', 'low', 'close')


class SignalSeries:
    def __init__(self, period_seconds, *, max_window):
        if (type(period_seconds) is not int or period_seconds not in
                (60, 300, 900, 1800, 3600, 86400)
                or type(max_window) is not int or max_window < 2):
            raise ValueError('连续信号窗口无效')
        self.period, self.maximum = period_seconds, max_window
        self.symbol, self.offset, self.switch_ns = None, Decimal(0), 0
        self._rows, self._discards = deque(), []
        self._seen, self._last = {}, 0

    def _raw(self, row):
        stamp = row['datetime']
        if type(stamp) is not int or stamp <= 0:
            raise ValueError('原始K线时间无效')
        end = row.get('end_ns', bar_end_ns(stamp, self.period))
        if type(end) is not int or end <= stamp:
            raise ValueError('原始K线结束时间无效')
        raw = {key: dec(row[key]) for key in PRICE_FIELDS}
        if (min(raw.values()) <= 0 or raw['high'] < max(raw.values())
                or raw['low'] > min(raw.values())):
            raise ValueError('真实OHLC无效')
        for key in ('volume', 'close_oi'):
            raw[key] = dec(row.get(key, 0))
            if raw[key] < 0:
                raise ValueError('真实成交量或持仓量无效')
        return raw | dict(datetime=stamp, end_ns=end)

    def switch(self, *, old_symbol, new_symbol, detected_ns, old_rows, new_rows):
        if (old_symbol != self.symbol or not isinstance(new_symbol, str) or not new_symbol
                or type(detected_ns) is not int or detected_ns <= 0
                or detected_ns < self.switch_ns):
            raise ValueError('历史主力切换状态无效')
        if new_symbol == old_symbol:
            return dict(changed=False, offset=self.offset)
        previous, reference = self.offset, None
        if old_symbol is not None:
            def completed(rows):
                result = {}
                for row in rows:
                    if row.get('completed', True) is not True:
                        continue
                    stamp = int(row['datetime'])
                    end = row.get('end_ns', bar_end_ns(stamp, self.period))
                    done = completed_at(row | {'end_ns': end}, self.period)
                    if done <= detected_ns:
                        raw = self._raw(row)
                        result[stamp] = raw
                return result
            old, new = completed(old_rows), completed(new_rows)
            common = old.keys() & new.keys()
            if not common:
                raise ValueError('没有当时已经完成且时间一致的换月参考柱')
            reference = max(common)
            offset = previous+new[reference]['close']-old[reference]['close']
        else:
            offset = Decimal(0)
        self.symbol, self.offset, self.switch_ns = new_symbol, offset, detected_ns
        return dict(changed=True, old_symbol=old_symbol, new_symbol=new_symbol,
                    detected_ns=detected_ns, reference_ns=reference,
                    previous_offset=previous, offset=offset)

    def append(self, *, symbol, row, completed_at_ns):
        if symbol != self.symbol:
            raise ValueError('信号柱不是当前历史主力')
        raw = self._raw(row)
        stamp, end = raw['datetime'], raw['end_ns']
        available = completed_at(row | {'end_ns': end}, self.period)
        if (row.get('completed', True) is not True or type(completed_at_ns) is not int
                or completed_at_ns < available):
            raise ValueError('信号柱尚未完成')
        if stamp < self.switch_ns:
            if end > self.switch_ns:
                evidence = dict(reason='roll_boundary_incomplete', source_symbol=symbol,
                                datetime=stamp, end_ns=end, detected_ns=self.switch_ns)
                if evidence not in self._discards:
                    self._discards.append(evidence)
            return None
        if stamp in self._seen:
            if raw != self._seen[stamp]:
                raise ValueError('已经处理的完成柱内容发生变化')
            return None
        if stamp <= self._last:
            return None
        adjusted = {key: raw[key]-self.offset for key in PRICE_FIELDS}
        adjusted.update(datetime=stamp, end_ns=end, completed=True,
                        completed_at_ns=completed_at_ns, raw=raw, source_symbol=symbol,
                        offset=self.offset, volume=raw['volume'], close_oi=raw['close_oi'],
                        trading_day=_timestamp_nano_to_str(
                            _get_trading_day_from_timestamp(stamp), fmt='%Y-%m-%d'))
        if row.get('completion_source') == 'SDK_3.10.2_CLOSE':
            adjusted.update(completed_at_ns=available, completion_source=row['completion_source'])
        self._rows.append(adjusted)
        self._seen[stamp], self._last = raw, stamp
        if len(self._rows) > self.maximum:
            self._seen.pop(self._rows.popleft()['datetime'])
        return copy.deepcopy(adjusted)

    def window(self):
        return copy.deepcopy(list(self._rows))

    def take_discards(self):
        result, self._discards = self._discards, []
        return result
