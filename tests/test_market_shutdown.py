"""真实天勤图表 WebSocket 的关闭回归；不建立账户会话。"""

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
import tqsdk
from aiohttp import ClientSession
from aiohttp.web_protocol import RequestHandler
from tqsdk.baseApi import TqBaseApi
from tqsdk.tqwebhelper import TqWebHelper

from qf.runtime import chart_address


@pytest.mark.filterwarnings("ignore:Bare functions are deprecated:DeprecationWarning")
def test_close_releases_sdk_chart_waiter_without_server_shutdown_timeout():
    import qf.market_session as market

    api = TqBaseApi()
    loop = api._loop
    ready = asyncio.Event()
    api._logger = logging.getLogger("offline-shutdown")
    api.create_task = api._create_task
    api._auth = SimpleNamespace(_access_token="offline-fixture")
    api._ins_url = api._md_url = ""
    api._print = lambda *args: ready.set()
    helper = object.__new__(TqWebHelper)
    helper._api = api
    helper._data = {"action": {"mode": "run"}, "subscribed": []}
    helper._conn_diff_chans = set()
    helper._http_server_host = "127.0.0.1"
    address = chart_address()
    helper._http_server_port = int(address.rsplit(":", 1)[1])
    helper._web_dir = str(Path(tqsdk.__file__).parent / "web")
    server = api._create_task(helper.link_httpserver())

    async def connect():
        await asyncio.wait_for(ready.wait(), 3)
        client = ClientSession()
        ws = await client.ws_connect(address + "/ws")
        await ws.receive_json()
        await ws.send_json({"aid": "peek_message"})
        await asyncio.sleep(0.05)
        return client, ws

    client, ws = loop.run_until_complete(connect())
    rescued = []

    def rescue():
        rescued.append(True)
        for task in asyncio.all_tasks(loop):
            if getattr(task.get_coro(), "cr_code", None) in (
                    RequestHandler.start.__code__, RequestHandler._handle_request.__code__):
                task.cancel()

    def close():
        guard = loop.call_later(0.7, rescue)
        try:
            api._close_tasks()
        finally:
            guard.cancel()

    api.close = close
    try:
        assert len(helper._conn_diff_chans) == 1
        market._close_api(api)
        assert not rescued, "关闭仍在等待 HTTP 超时，而没有释放图表请求"
        assert server.done()
    finally:
        if not server.done():
            rescue()
            close()
        loop.run_until_complete(ws.close())
        loop.run_until_complete(client.close())
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
