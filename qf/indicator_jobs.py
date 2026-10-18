"""单计算线程；各格仅保留最新待处理请求，结果有界。"""

import copy
import re
import threading
import uuid
from collections import OrderedDict

from qf.indicator_calculation import calculate_indicators, validate_rows
from qf.indicator_catalog import CATALOG, number, validate_item

IDENTITY = ('pane_id', 'generation', 'chart_revision', 'settings_revision',
            'symbol', 'period', 'data_revision', 'request_id')
FIELDS = set(IDENTITY) | {'rows', 'items', 'price_tick', 'visible', 'coverage_end_ns'}


def validate_request(raw):
    if not isinstance(raw, dict) or set(raw) != FIELDS:
        raise ValueError('计算请求字段无效')
    if (raw['pane_id'] not in [f'pane-{i}' for i in range(1, 5)]
            or raw['period'] not in ('close', '1m', '5m', '15m', '30m', '1h', '1d')
            or not isinstance(raw['symbol'], str)
            or not re.fullmatch(r'(?:KQ\.m@)?(?:SHFE|DCE|CZCE|CFFEX|INE|GFEX)'
                                r'\.[A-Za-z]+\d{0,4}', raw['symbol'])
            or not isinstance(raw['data_revision'], str) or len(raw['data_revision']) > 128
            or not isinstance(raw['coverage_end_ns'], str)
            or not re.fullmatch(r'\d{16,20}', raw['coverage_end_ns'])):
        raise ValueError('计算标识无效')
    for key in ('generation', 'chart_revision', 'settings_revision', 'request_id'):
        number(raw[key], 1, 2**53-1, integer=True)
    number(raw['price_tick'], 1e-10, 1e10)
    rows = validate_rows(raw['rows'])
    if (not isinstance(raw['visible'], list) or len(raw['visible']) != 2
            or any(type(v) is not int for v in raw['visible'])
            or not rows[0]['id'] <= raw['visible'][0] <= raw['visible'][1] <= rows[-1]['id']
            or not isinstance(raw['items'], list) or len(raw['items']) > len(CATALOG)+1):
        raise ValueError('指标计算范围无效')
    seen = set()
    for item in raw['items']:
        item = validate_item(item)
        if item['id'] in seen:
            raise ValueError('指标重复')
        seen.add(item['id'])
    return copy.deepcopy(raw)


class IndicatorJobs:
    def __init__(self, *, compute=calculate_indicators):
        self._compute = compute
        self._condition = threading.Condition()
        self._pending = OrderedDict()
        self._results = OrderedDict()
        self._thread = None
        self._closed = False

    def submit(self, request: dict) -> dict:
        try:
            payload = validate_request(request)
        except (ValueError, TypeError, KeyError, OverflowError):
            return {'ok': False, 'reason': '指标请求无效、范围过大或历史数据需核实。'}
        with self._condition:
            if self._closed:
                return {'ok': False, 'reason': '指标计算已停止。'}
            pane, ident = payload['pane_id'], uuid.uuid4().hex
            old = self._pending.pop(pane, None)
            if old:
                self._results[old[0]]['status'] = 'superseded'
            self._pending[pane] = (ident, payload)
            self._results[ident] = {'status': 'queued',
                'identity': {k: payload[k] for k in IDENTITY}}
            while len(self._results) > 32:
                stale = next((k for k, v in self._results.items()
                              if v['status'] not in ('queued', 'running')), None)
                if stale is None:
                    break
                del self._results[stale]
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, daemon=True,
                                                name='indicator-calculation')
                self._thread.start()
            self._condition.notify()
            return {'ok': True, 'job_id': ident, 'reason': ''}

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._pending)
                if self._closed:
                    return
                _, (ident, payload) = self._pending.popitem(last=False)
                self._results[ident]['status'] = 'running'
            try:
                result = {'status': 'ready', 'result': self._compute(payload)}
            except Exception:
                result = {'status': 'error', 'reason': '指标计算失败，请检查参数或已加载数据。'}
            with self._condition:
                if not self._closed and ident in self._results:
                    self._results[ident].update(result)

    def poll(self, job_ids: list[str]) -> dict:
        if (not isinstance(job_ids, list) or len(job_ids) > 8
                or any(not isinstance(x, str) or len(x) > 64 for x in job_ids)):
            return {}
        with self._condition:
            return {ident: copy.deepcopy(self._results.get(ident, {'status': 'superseded'}))
                    for ident in job_ids}

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._pending.clear()
            self._results.clear()
            self._condition.notify_all()
