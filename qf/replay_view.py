"""本机只读复盘服务：使用SDK原生资源与已存数据，不创建TqApi。"""

import asyncio
import json
import sqlite3
import threading
from contextlib import closing
from importlib import metadata
from pathlib import Path

import pandas as pd
from aiohttp import web
from tqsdk.tafunc import ma

from qf.research_chart_assets import chart_html
from qf.research_config import decimal_value
from qf.research_results import read_run, run_path
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
        summary = read_run(self.root, run_id)
        if summary["status"] not in ("backtest_finished", "stopped", "frozen", "failed"):
            raise ValueError("请先结束运行再查看静态复盘")
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

    def _read(self, offset=0, limit=10000):
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

    def _payload(self):
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
        )

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
        data = {
            str(i): dict(
                datetime=int(row["time_ns"]), **{k: v for k, v in row.items() if k != "time_ns"}
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
            klines={symbol: {duration: dict(last_id=len(data) - 1, data=data)}},
        )
        html = chart_html(assets)
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
                    int(request.query.get("offset", "0")),
                    int(request.query.get("limit", "10000")),
                )
                if offset < 0 or not 1 <= limit <= 10000:
                    raise ValueError()
                return web.json_response(self._read(offset, limit))
            except (ValueError, sqlite3.Error):
                raise web.HTTPBadRequest(text="复盘分页无效") from None

        async def script(request):
            return web.FileResponse(Path(__file__).with_name("web") / "native-replay.js")

        app = web.Application()
        app.router.add_get("/", index)
        app.router.add_get("/index.html", index)
        app.router.add_get("/url", urls)
        app.router.add_get("/ws", websocket)
        app.router.add_get("/replay", replay)
        app.router.add_get("/bars", bars)
        app.router.add_get("/replay.js", script)
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
