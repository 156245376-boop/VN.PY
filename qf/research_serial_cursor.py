"""有界完成柱游标；只把新完成柱交给信号序列，并验证旧柱不被改写。"""

from collections import OrderedDict

from qf.safety import Frozen


class SerialCursor:
    def __init__(self, *, history=200):
        self.history = history
        self.last_datetime = 0
        self.seen = OrderedDict()

    def read(self, complete):
        rows = complete()
        fresh = []
        for row in rows:
            stamp = int(row['datetime'])
            raw = tuple(row[key] for key in
                        ('datetime', 'open', 'high', 'low', 'close', 'volume', 'close_oi'))
            if stamp <= self.last_datetime:
                if stamp in self.seen and self.seen[stamp] != raw:
                    raise Frozen('historical_data_invalid')
                continue
            fresh.append(row)
            self.seen[stamp] = raw
            self.last_datetime = max(self.last_datetime, stamp)
        while len(self.seen) > self.history:
            self.seen.popitem(last=False)
        return fresh
