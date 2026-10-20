"""本机只读复盘服务：使用SDK原生资源与已存数据，不创建TqApi。"""

import asyncio
import json
import sqlite3
import threading
from bisect import bisect_right
from contextlib import closing
from dataclasses import asdict
from importlib import metadata
from pathlib import Path

import pandas as pd
from aiohttp import web
from tqsdk.tafunc import ma

from qf.history_store import HistoryStore
from qf.local_data import load_continuous_frame
from qf.local_results import local_run_details
from qf.research_account import account_window, read_account
from qf.research_chart_assets import chart_html
from qf.research_config import decimal_value, public_values
from qf.research_protection import protection_window
from qf.research_results import run_path, summarize_run
from qf.runtime import chart_address


class ReplayView:
    def __init__(self, root):
        self.root = Path(root)
        self._stop = threading.Event()
        self._ready = threading.Event()
        self.thread = None
        self.revision = 0
        self._error = None

    def open(self, run_id):
        summary = summarize_run(self.root, run_id)
        if summary["status"] not in ("backtest_finished", "stopped", "frozen", "failed"):
            raise ValueError("请先结束运行再查看静态复盘")
        self.local_frame = None
        self.local_details = None
        if summary.get('engine_kind') == 'local_research':
            dataset_id = summary.get('dataset_id')
            if not isinstance(dataset_id, str) or not dataset_id:
                raise ValueError("快速研究缺少本机数据身份")
            self.local_frame = load_continuous_frame(
                HistoryStore(self.root/'history'), dataset_id
            )
            self.local_details = local_run_details(self.root, run_id)
        if not summary["coverage"]["bars"]:
            raise ValueError("本实验没有保存可复盘的K线")
        if metadata.version("tqsdk") != "3.10.2":
            raise ValueError("复盘资源版本不匹配")
        self.close()
        self.revision += 1
        self.path = run_path(self.root, run_id)
        self.summary, self.run_id = summary, run_id
        self.url = chart_address() + "/"
        self._stop.clear()
        self._ready.clear()
        self._error = None
        self.thread = threading.Thread(target=self._thread_main, daemon=True)
        self.thread.start()
        if not self._ready.wait(10) or self._error:
            self.close()
            raise ValueError("本机复盘服务未能打开")
        return self.url

    def _read(self, offset=None, limit=10000, *, series='signal', symbol=None):
        if self.summary.get('engine_kind') == 'local_research':
            return self._read_local(
                offset, limit, series=series, symbol=symbol
            )
        if self.summary['config']['schema_version'] == 3:
            from qf.continuous_results import ContinuousReader
            reader = ContinuousReader(self.path)
            if offset is None:
                initial = reader.initial(series=series, symbol=symbol)
                offset, limit = initial['offset'], 2000
            return reader.window(offset, limit, series=series, symbol=symbol)
        offset = 0 if offset is None else offset
        with closing(
            sqlite3.connect((self.path / "journal.sqlite3").as_uri() + "?mode=ro", uri=True)
        ) as db:
            rows = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT data FROM research_bars ORDER BY time_ns LIMIT ? OFFSET ?",
                    (limit, offset),
                )
            ]
            count = db.execute("SELECT count(*) FROM research_bars").fetchone()[0]
        return dict(bars=rows, total_bars=count, offset=offset, next_offset=offset + len(rows))

    def _read_local(self, offset, limit, *, series, symbol=None):
        if series not in ('signal', 'actual'):
            raise ValueError('复盘序列无效')
        frame = self.local_frame.frame
        if series == 'actual':
            if symbol not in self.local_frame.symbols:
                raise ValueError('实际合约不存在')
            frame = frame[frame['symbol'] == symbol]
        offset = max(0, len(frame)-2000) if offset is None else offset
        page = frame.iloc[offset:offset+limit]
        price_prefix = '' if series == 'signal' else 'actual_'
        bars = [
            {
                'time_ns': str(int(row.time_ns)),
                'open': float(getattr(row, price_prefix+'open')),
                'high': float(getattr(row, price_prefix+'high')),
                'low': float(getattr(row, price_prefix+'low')),
                'close': float(getattr(row, price_prefix+'close')),
                'volume': float(row.volume),
                'close_oi': float(row.close_oi),
                'completed': True,
                'symbol': row.symbol,
            }
            for row in page.itertuples(index=False)
        ]
        return {
            'bars': bars,
            'total_bars': len(frame),
            'offset': offset,
            'next_offset': offset+len(bars),
            'series': series,
            'actual_symbol': symbol if series == 'actual' else None,
        }

    def _payload(self):
        if self.summary.get('engine_kind') == 'local_research':
            return self._local_payload()
        if self.summary['config']['schema_version'] == 3:
            from qf.continuous_results import ContinuousReader
            with closing(ContinuousReader(self.path).connect()) as db:
                raw = db.execute('SELECT data FROM contract_specs '
                                 'ORDER BY symbol LIMIT 1').fetchone()
                specs = {s: json.loads(data) for s, data in db.execute(
                    'SELECT * FROM contract_specs')}
                span = db.execute('SELECT min(time_ns),max(time_ns) FROM signal_bars').fetchone()
                first, last = span
                observation = dict(
                    protection=protection_window(
                        db, first_ns=first or 0, as_of_ns=last or (first or 0),
                        series='signal', symbol=None),
                    account=read_account(db, at_ns=last),
                    account_history=account_window(
                        db, first_ns=first or 0, as_of_ns=last or (first or 0)))
            return dict(**self.summary, revision=self.revision,
                symbol=self.summary['config']['continuous'],
                bar_seconds=self.summary['config']['bar_seconds'],
                contract_spec=json.loads(raw[0]) if raw else {},
                contract_specs=specs,
                fills=[], risk_events=[], ma_series=[], **observation)
        with closing(
            sqlite3.connect((self.path / "journal.sqlite3").as_uri() + "?mode=ro", uri=True)
        ) as db:
            events = [
                dict(time_ns=str(r[0]), kind=r[1], payload=json.loads(r[2]), risk=json.loads(r[3]))
                for r in db.execute(
                    "SELECT time_ns,kind,payload,risk FROM risk_events ORDER BY rowid"
                )
            ]
            fills = [
                dict(
                    zip(
                        (
                            "key",
                            "order_id",
                            "symbol",
                            "direction",
                            "offset",
                            "volume",
                            "price",
                            "time_ns",
                        ),
                        r,
                        strict=True,
                    )
                )
                for r in db.execute("SELECT * FROM fills ORDER BY time_ns,rowid")
            ]
            closes = [
                (r[0], json.loads(r[1])["close"])
                for r in db.execute("SELECT time_ns,data FROM research_bars ORDER BY time_ns")
            ]
            spec_raw = db.execute("SELECT value FROM state WHERE key='contract_spec'").fetchone()
            span = db.execute('SELECT min(time_ns),max(time_ns) FROM research_bars').fetchone()
            observation = dict(
                protection=protection_window(
                    db, first_ns=span[0] or 0, as_of_ns=span[1] or (span[0] or 0),
                    series='actual', symbol=self.summary['config']['symbol']),
                account=read_account(db, at_ns=span[1]),
                account_history=account_window(
                    db, first_ns=span[0] or 0, as_of_ns=span[1] or (span[0] or 0)))
        for fill in fills:
            fill["time_ns"] = str(fill["time_ns"])
        lines = []
        for period in (
            self.summary["config"]["fast_period"],
            self.summary["config"]["slow_period"],
        ):
            values = ma(pd.Series([r[1] for r in closes]), period)
            lines.append(
                dict(
                    period=period,
                    points=[
                        dict(id=i, value=float(v), time_ns=str(closes[i][0]))
                        for i, v in enumerate(values)
                        if pd.notna(v)
                    ],
                )
            )
        return dict(
            **self.summary,
            revision=self.revision,
            symbol=self.summary["config"]["symbol"],
            bar_seconds=self.summary["config"]["bar_seconds"],
            fills=fills,
            risk_events=events,
            ma_series=lines,
            contract_spec=json.loads(spec_raw[0]) if spec_raw else {},
            **observation,
        )

    def _local_payload(self):
        details = self.local_details
        fills = []
        events = []
        reason_by_trade = {
            trade['trade_id']: trade.get('exit_reason')
            for trade in details.get('trades', [])
        }
        for item in details.get('fills', []):
            fill = dict(item)
            fill['time_ns'] = str(int(fill['time_ns']))
            fills.append(fill)
            events.append({
                'time_ns': fill['time_ns'],
                'kind': 'fill',
                'payload': {'fill_keys': [fill['key']], 'fill': fill},
                'risk': {
                    'side': 1 if fill['direction'] == 'BUY' else -1,
                    'exit_reason': reason_by_trade.get(fill['trade_id']),
                },
            })
        closes = self.local_frame.frame['close'].astype(float).tolist()
        times = self.local_frame.frame['time_ns'].astype('int64').tolist()
        lines = []
        for period in (
            self.summary['config']['fast_period'],
            self.summary['config']['slow_period'],
        ):
            values = ma(pd.Series(closes), period)
            lines.append({
                'period': period,
                'points': [
                    dict(
                        id=index,
                        value=float(value),
                        time_ns=str(times[index]),
                    )
                    for index, value in enumerate(values)
                    if pd.notna(value)
                ],
            })
        specs = public_values({
            symbol: asdict(spec)
            for symbol, spec in self.local_frame.specs.items()
        })
        equity = details.get('equity', [])
        account = None
        account_history = []
        if equity:
            last = equity[-1]
            account = {
                'time_ns': last['time_ns'],
                'balance': last['balance'],
                'float_profit': last['unrealized_gross'],
                'margin': last['margin'],
                'commission': self.summary['commission'],
                'equity': last['equity'],
            }
            account_history = [
                dict(
                    time_ns=point['time_ns'],
                    balance=point['equity'],
                    equity=point['equity'],
                )
                for point in equity[-2000:]
            ]
        mappings = [
            dict(item, time_ns=str(item['time_ns']))
            for item in self.local_frame.mapping
        ]
        payload = dict(
            **self.summary,
            revision=self.revision,
            symbol=self.summary['config']['continuous'],
            bar_seconds=self.summary['config']['bar_seconds'],
            fills=fills,
            risk_events=events,
            ma_series=lines,
            contract_spec=specs.get(self.local_frame.symbols[0], {}),
            contract_specs=specs,
            main_changes=mappings,
            account=account,
            account_history=account_history,
            protection=[],
        )
        payload['actual_symbols'] = list(self.local_frame.symbols)
        return payload

    def _thread_main(self):
        try:
            asyncio.run(self._serve())
        except Exception:
            self._error = True
            self._ready.set()

    async def _serve(self):
        import tqsdk

        assets = Path(tqsdk.__file__).parent / "web"
        payload = self._payload()
        initial = self._read()
        duration = str(payload["bar_seconds"] * 1_000_000_000)
        symbol = payload["symbol"]
        first_id = initial.get('first_bar_id', 0)
        data = {
            str(first_id+i): dict(
                datetime=int(row['time_ns']),
                **{k: v for k, v in row.items() if k not in ('time_ns', 'datetime')}
            )
            for i, row in enumerate(initial["bars"])
        }
        last = initial["bars"][-1]
        quote = dict(
            payload["contract_spec"],
            instrument_name="离线复盘",
            last_price=last["close"],
            datetime=str(pd.Timestamp(int(last["time_ns"]), tz="UTC").tz_convert("Asia/Shanghai")),
            ins_class="FUTURE",
        )
        for key in ("price_tick", "volume_multiple"):
            if key in quote:
                quote[key] = float(decimal_value(quote[key]))
        if quote.get("price_tick"):
            quote["price_decs"] = max(
                0, -decimal_value(quote["price_tick"]).normalize().as_tuple().exponent
            )
        packet = dict(
            action=dict(
                mode="run",
                accounts={},
                user_name="离线复盘 · 非实时行情",
                file_name="双均线成交复盘",
                md_url_status=False,
            ),
            trade={},
            subscribed=[dict(symbol=symbol, dur_nano=int(duration))],
            draw_chart_datas={},
            snapshots={},
            quotes={symbol: quote},
            klines={symbol: {duration: dict(last_id=first_id+len(data)-1, data=data)}},
        )
        html = chart_html(assets, continuous=payload['config']['schema_version'] == 3)
        sockets = set()

        async def index(request):
            return web.Response(text=html, content_type="text/html")

        async def urls(request):
            return web.json_response(dict(ins_url="", md_url="", access_token="offline-replay"))

        async def websocket(request):
            if request.headers.get("Origin") != self.url.rstrip("/"):
                raise web.HTTPForbidden(text="复盘来源无效")
            ws = web.WebSocketResponse(timeout=0.5)
            await ws.prepare(request)
            sockets.add(ws)
            try:
                await ws.send_json(dict(aid="rtn_data", data=[packet]))
                async for _ in ws:
                    pass  # 静态结果无后续报价，不用空响应制造轮询风暴。
            finally:
                sockets.discard(ws)
            return ws

        async def replay(request):
            return web.json_response(payload)

        async def bars(request):
            try:
                offset, limit = (
                    int(request.query['offset']) if 'offset' in request.query else None,
                    int(request.query.get("limit", "10000")),
                )
                if (offset is not None and offset < 0) or not 1 <= limit <= 10000:
                    raise ValueError()
                page = self._read(offset, limit, series=request.query.get('series', 'signal'),
                                  symbol=request.query.get('symbol'))
                return web.json_response(page | dict(run_id=self.run_id,
                    request_id=request.query.get('request_id', ''), revision=self.revision))
            except (ValueError, sqlite3.Error):
                raise web.HTTPBadRequest(text="复盘分页无效") from None

        async def account(request):
            try:
                stamp = request.query.get('time_ns')
                stamp = int(stamp) if stamp is not None else None
                if self.summary.get('engine_kind') == 'local_research':
                    points = [
                        point for point in self.local_details.get('equity', [])
                        if stamp is None or int(point['time_ns']) <= stamp
                    ]
                    value = (
                        {
                            'time_ns': points[-1]['time_ns'],
                            'balance': points[-1]['balance'],
                            'float_profit': points[-1]['unrealized_gross'],
                            'margin': points[-1]['margin'],
                            'commission': self.summary['commission'],
                            'equity': points[-1]['equity'],
                        }
                        if points else None
                    )
                    return web.json_response(dict(
                        run_id=self.run_id,
                        revision=self.revision,
                        requested_time_ns=(
                            str(stamp) if stamp is not None else None
                        ),
                        account=value,
                    ))
                with closing(sqlite3.connect(
                        (self.path/'journal.sqlite3').as_uri()+'?mode=ro', uri=True)) as db:
                    value = read_account(db, at_ns=stamp)
                return web.json_response(dict(run_id=self.run_id, revision=self.revision,
                    requested_time_ns=str(stamp) if stamp is not None else None,
                    account=value))
            except (ValueError, sqlite3.Error):
                raise web.HTTPBadRequest(text="账户历史时点无效") from None

        async def protection(request):
            try:
                first_ns = int(request.query['first_ns'])
                as_of_ns = int(request.query.get('as_of_ns', first_ns))
                series = request.query.get('series', 'signal')
                symbol = request.query.get('symbol')
                if self.summary.get('engine_kind') == 'local_research':
                    return web.json_response({
                        'run_id': self.run_id,
                        'revision': self.revision,
                        'first_ns': str(first_ns),
                        'as_of_ns': str(as_of_ns),
                        'series': series,
                        'actual_symbol': symbol if series == 'actual' else None,
                        'trades': [],
                        'events': [],
                    })
                with closing(sqlite3.connect(
                        (self.path/'journal.sqlite3').as_uri()+'?mode=ro', uri=True)) as db:
                    value = protection_window(
                        db, first_ns=first_ns, as_of_ns=as_of_ns,
                        series=series, symbol=symbol)
                return web.json_response(value | dict(
                    run_id=self.run_id, revision=self.revision))
            except (ValueError, KeyError, sqlite3.Error):
                raise web.HTTPBadRequest(text="保护轨迹窗口无效") from None

        async def script(request):
            if request.path == '/native-toolbar.js':
                name = 'native-toolbar.js'
            else:
                name = ('continuous-replay.js' if request.path == '/continuous.js'
                        else 'native-replay.js')
            return web.FileResponse(Path(__file__).with_name("web") / name)

        async def locate(request):
            from qf.continuous_results import ContinuousReader
            try:
                if payload['config']['schema_version'] != 3:
                    raise ValueError()
                if self.summary.get('engine_kind') == 'local_research':
                    frame = self.local_frame.frame
                    series = request.query.get('series', 'signal')
                    symbol = request.query.get('symbol')
                    if series == 'actual':
                        frame = frame[frame['symbol'] == symbol]
                    times = frame['time_ns'].astype('int64').tolist()
                    count = bisect_right(times, int(request.query['time_ns']))
                    index = max(0, count-1)
                    return web.json_response({
                        'offset': max(0, index-1000),
                        'global_id': index,
                    })
                page = ContinuousReader(self.path).locate(request.query['time_ns'],
                    series=request.query.get('series', 'signal'),
                    symbol=request.query.get('symbol'))
                return web.json_response(dict(offset=page['offset'], global_id=page['global_id']))
            except (KeyError, ValueError):
                raise web.HTTPBadRequest(text='复盘定位无效') from None

        app = web.Application()
        app.router.add_get("/", index)
        app.router.add_get("/index.html", index)
        app.router.add_get("/url", urls)
        app.router.add_get("/ws", websocket)
        app.router.add_get("/replay", replay)
        app.router.add_get("/bars", bars)
        app.router.add_get("/account", account)
        app.router.add_get("/protection", protection)
        app.router.add_get('/native-toolbar.js', script)
        app.router.add_get("/replay.js", script)
        app.router.add_get('/continuous.js', script)
        app.router.add_get('/locate', locate)
        app.router.add_static("/web", assets, show_index=False)
        runner = web.AppRunner(app, shutdown_timeout=1)
        await runner.setup()
        try:
            await web.TCPSite(runner, "127.0.0.1", int(self.url.split(":")[-1].strip("/"))).start()
            self._ready.set()
            while not self._stop.is_set():
                await asyncio.sleep(0.05)
        finally:
            for ws in tuple(sockets):
                await ws.close()
            await runner.cleanup()

    def close(self):
        self._stop.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(3)
            if self.thread.is_alive():
                raise ValueError("复盘服务尚未关闭")
