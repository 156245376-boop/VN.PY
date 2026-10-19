"""只读运行图：消费执行线程发布的副本，不创建账户或读取活动SQLite。"""

import asyncio
import json
import threading
from importlib import metadata
from pathlib import Path

from aiohttp import web

from qf.research_chart_assets import chart_html
from qf.runtime import chart_address


class LiveResearchView:
    def __init__(self, snapshot_provider, *, state_provider=None):
        self.provider = snapshot_provider
        self.state_provider = state_provider
        self.generation = 0
        self.run_id = None
        self.thread = None
        self._stop, self._ready = threading.Event(), threading.Event()
        self._error = False

    def open(self):
        current = self.provider()
        run_id = current['run_id'] if current else None
        if (self.thread and self.thread.is_alive()
                and (not run_id or self.run_id in (None, run_id))):
            if run_id:
                self.run_id = run_id
            return self.url
        self.close()
        if metadata.version('tqsdk') != '3.10.2':
            raise ValueError('运行图资源版本不匹配')
        self.generation += 1
        self.run_id, self.url = run_id, chart_address()+'/'
        self._stop.clear()
        self._ready.clear()
        self._error = False
        self.thread = threading.Thread(target=self._thread_main, daemon=True)
        self.thread.start()
        if not self._ready.wait(10) or self._error:
            self.close()
            raise ValueError('本机运行图服务未能打开')
        return self.url

    def _thread_main(self):
        try:
            asyncio.run(self._serve())
        except Exception:
            self._error = True
            self._ready.set()

    async def _serve(self):
        import tqsdk
        assets = Path(tqsdk.__file__).parent/'web'
        html = chart_html(assets, live=dict(run_id=self.run_id, generation=self.generation))
        sockets = set()

        async def index(request):
            return web.Response(text=html, content_type='text/html')

        async def snapshot(request):
            try:
                after = int(request.query.get('after_revision', '0'))
                if after < 0:
                    raise ValueError()
            except ValueError:
                raise web.HTTPBadRequest(text='快照序号无效') from None
            value = self.provider()
            if value is None:
                state = self.state_provider() if self.state_provider else {}
                if (not state.get('running') and state.get('status') in
                        ('failed', 'frozen', 'stopped', 'backtest_finished')):
                    return web.json_response(dict(changed=False, waiting=False, terminal=True,
                        generation=self.generation, run_id=self.run_id or state.get('run_id'),
                        revision=0, status=state['status'], reason=state.get('reason')))
                return web.json_response(dict(changed=False, waiting=True,
                    generation=self.generation, run_id=self.run_id, revision=0))
            if self.run_id is None:
                self.run_id = value['run_id']
            if value['run_id'] != self.run_id:
                raise web.HTTPConflict(text='实验已切换，请重新打开运行图')
            result = dict(changed=value['revision'] > after, run_id=self.run_id,
                          revision=value['revision'], generation=self.generation)
            if result['changed']:
                result['snapshot'] = value
            return web.json_response(result, dumps=lambda x: json.dumps(x, allow_nan=False))

        async def urls(request):
            return web.json_response(dict(ins_url='', md_url='', access_token='local-read-only'))

        async def websocket(request):
            if request.headers.get('Origin') != self.url.rstrip('/'):
                raise web.HTTPForbidden(text='运行图来源无效')
            ws = web.WebSocketResponse(timeout=.5)
            await ws.prepare(request)
            sockets.add(ws)
            try:
                await ws.send_json(dict(aid='rtn_data', data=[dict(action=dict(mode='run',
                    accounts={}, user_name='回测过程 · 只读', file_name='双均线实验',
                    md_url_status=False), subscribed=[], trade={}, snapshots={},
                    draw_chart_datas={}, quotes={}, klines={})]))
                async for _ in ws:
                    pass
            finally:
                sockets.discard(ws)
            return ws

        async def script(request):
            name = 'native-live-research.js' if request.path == '/live.js' else 'native-replay.js'
            return web.FileResponse(Path(__file__).with_name('web')/name)

        app = web.Application()
        app.router.add_get('/', index)
        app.router.add_get('/index.html', index)
        app.router.add_get('/snapshot', snapshot)
        app.router.add_get('/url', urls)
        app.router.add_get('/ws', websocket)
        app.router.add_get('/live.js', script)
        app.router.add_get('/replay.js', script)
        app.router.add_static('/web', assets, show_index=False)
        runner = web.AppRunner(app, shutdown_timeout=1)
        await runner.setup()
        try:
            await web.TCPSite(runner, '127.0.0.1', int(self.url.split(':')[-1].strip('/'))).start()
            self._ready.set()
            while not self._stop.is_set():
                await asyncio.sleep(.05)
        finally:
            for ws in tuple(sockets):
                await ws.close()
            await runner.cleanup()

    def close(self):
        self._stop.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(3)
            if self.thread.is_alive():
                raise ValueError('运行图服务尚未关闭')
