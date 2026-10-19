"""仅按实际处理时间推进；保存成功前不发布100%。"""

import time


class BacktestProgress:
    def __init__(self, start_ns, end_ns, *, clock=time.monotonic):
        self.start_ns, self.end_ns, self.clock = start_ns, end_ns, clock
        self.started = self.advanced = clock()
        self.current = None
        self.stage, self.bars, self.fills, self.finished = 'validating', 0, 0, False

    def update(self, stage, *, current_ns=None, bars=0, fills=0, success=False):
        self.stage = stage
        if (type(current_ns) is int and self.start_ns <= current_ns <= self.end_ns
                and (self.current is None or current_ns > self.current)):
            self.current, self.advanced = current_ns, self.clock()
        self.bars, self.fills = max(self.bars, bars), max(self.fills, fills)
        self.finished = stage == 'completed' and success is True
        return self.snapshot()

    def snapshot(self):
        percent = None
        if self.finished:
            percent = 100
        elif self.current is not None and self.end_ns > self.start_ns:
            percent = min(99, max(0, int(100*(self.current-self.start_ns)
                                         /(self.end_ns-self.start_ns))))
        return dict(stage=self.stage, current_ns=self.current, percent=percent,
                    completed_bars=self.bars, fill_count=self.fills, finished=self.finished,
                    elapsed_seconds=round(self.clock()-self.started, 1),
                    last_advance_age_seconds=round(self.clock()-self.advanced, 1))
