"""单任务完整只读观察窗；不暴露业务桥接或写操作。"""

import asyncio
import copy
import re
import threading
from pathlib import Path

from aiohttp import web

from qf.desktop import allowed_chart_url
from qf.research_config import public_values
from qf.runtime import chart_address
from qf.trade_analytics import (
    filter_trades,
    normalize_trade_filters,
    trade_ledger_csv,
    trade_statistics,
)

JOB_ID = re.compile(r'^[0-9a-f]{32}$')
ASSETS = {'research-window.js', 'research-window.css', 'account-view.js', 'labels.js'}
STATE_FIELDS = {'job_id', 'status', 'running', 'reason', 'run_id', 'config',
                'progress', 'account', 'risk', 'mode', 'engine_kind',
                'compute_backend', 'dataset_id'}


class ResearchWindowView:
    def __init__(self, job_id, state_provider, ledger_provider, chart_provider):
        if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
            raise ValueError('观察任务编号无效')
        self.job_id = job_id
        self.state_provider = state_provider
        self.ledger_provider = ledger_provider
        self.chart_provider = chart_provider
        self.url = None
        self.thread = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._error = False

    def _state(self):
        raw = self.state_provider()
        if not isinstance(raw, dict) or raw.get('job_id') != self.job_id:
            raise ValueError('观察任务身份不匹配')
        state = {key: copy.deepcopy(raw[key]) for key in STATE_FIELDS if key in raw}
        state = public_values(state)
        chart_url = self.chart_provider()
        if not allowed_chart_url(chart_url):
            raise ValueError('观察图地址无效')
        state['chart_url'] = chart_url
        return state

    def _ledger(self, raw_filters):
        filters = normalize_trade_filters(raw_filters)
        ledger = self.ledger_provider()
        if not isinstance(ledger, dict):
            raise ValueError('交易账本无效')
        trades = filter_trades(ledger, filters)
        ids = {trade.get('trade_id') for trade in trades}
        fills = [fill for fill in ledger.get('fills', [])
                 if isinstance(fill, dict) and fill.get('trade_id') in ids]
        return {
            'available': ledger.get('available') is True,
            'reason': ledger.get('reason', ''),
            'reconciled': ledger.get('reconciled') is True,
            'truncated': ledger.get('truncated') is True,
            'fee_total': ledger.get('fee_total'),
            'fee_reconciled_difference': ledger.get('fee_reconciled_difference'),
            'trades': trades,
            'fills': fills,
            'statistics': trade_statistics(trades),
        }

    def app(self):
        async def index(_request):
            page = Path(__file__).with_name('web')/'research-window.html'
            if page.is_file():
                return web.FileResponse(page)
            return web.Response(
                text='<!doctype html><meta charset="utf-8"><title>研究观察窗</title>'
                     '<p>研究观察窗正在准备。</p>',
                content_type='text/html')

        async def state(_request):
            try:
                return web.json_response(self._state())
            except (KeyError, TypeError, ValueError, OSError):
                return web.json_response(
                    {'ok': False, 'reason': '观察状态暂不可用。'}, status=503)

        def query_filters(request):
            allowed = ('direction', 'status', 'symbol', 'reason', 'start', 'end',
                       'min_net', 'max_net')
            return {key: request.query.get(key) for key in allowed}

        async def ledger(request):
            try:
                packet = self._ledger(query_filters(request))
                return web.json_response(public_values(packet))
            except (TypeError, ValueError, OSError):
                return web.json_response(
                    {'ok': False, 'reason': '交易筛选或账本暂不可用。'}, status=400)

        async def ledger_csv(request):
            try:
                packet = self._ledger(query_filters(request))
                text = trade_ledger_csv(packet['trades'])
                return web.Response(
                    text=text, content_type='text/csv',
                    headers={'Content-Disposition':
                             f"attachment; filename=trade-ledger-{self.job_id[:8]}.csv"})
            except (TypeError, ValueError, OSError):
                return web.Response(text='交易筛选或账本暂不可用。', status=400)

        async def asset(request):
            name = request.match_info['name']
            if name not in ASSETS:
                raise web.HTTPNotFound()
            path = Path(__file__).with_name('web')/name
            if not path.is_file():
                raise web.HTTPNotFound()
            return web.FileResponse(path)

        application = web.Application()
        application.router.add_get('/', index)
        application.router.add_get('/state', state)
        application.router.add_get('/ledger', ledger)
        application.router.add_get('/ledger.csv', ledger_csv)
        application.router.add_get('/assets/{name}', asset)
        return application

    def open(self):
        if self.thread and self.thread.is_alive():
            return self.url
        self.url = chart_address()+'/'
        self._ready.clear()
        self._stop.clear()
        self._error = False
        self.thread = threading.Thread(target=self._thread_main, daemon=True)
        self.thread.start()
        if not self._ready.wait(10) or self._error:
            self.close()
            raise ValueError('研究观察窗服务未能打开')
        return self.url

    def _thread_main(self):
        try:
            asyncio.run(self._serve())
        except Exception:
            self._error = True
            self._ready.set()

    async def _serve(self):
        runner = web.AppRunner(self.app(), shutdown_timeout=1)
        await runner.setup()
        port = int(self.url.split(':')[-1].strip('/'))
        site = web.TCPSite(runner, '127.0.0.1', port)
        await site.start()
        self._ready.set()
        try:
            while not self._stop.is_set():
                await asyncio.sleep(.05)
        finally:
            await runner.cleanup()

    def close(self):
        self._stop.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(3)
            if self.thread.is_alive():
                raise ValueError('研究观察窗服务尚未关闭')
