"""跨执行线程的观看开关；只控制展示快照，不参与交易决策。"""

import threading


class ViewDemand:
    def __init__(self):
        self._lock = threading.Lock()
        self._enabled = False
        self._generation = 0

    def set(self, enabled, generation):
        if type(enabled) is not bool or type(generation) is not int or generation < 0:
            raise ValueError('观看请求无效')
        with self._lock:
            self._enabled, self._generation = enabled, generation

    def snapshot(self):
        with self._lock:
            return self._enabled, self._generation

    def wants_frame(self):
        with self._lock:
            return self._enabled
