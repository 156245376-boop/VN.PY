"""真实 SDK 网页服务的本机离线检查；认证对象是内存替身。"""

import asyncio
import contextlib
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import aiohttp
import pytest
import tqsdk
from tqsdk.tqwebhelper import TqWebHelper

from qf.journal import Journal
from qf.runtime import chart_address, tracked_api


def test_chart_address_avoids_restricted_low_browser_ports(monkeypatch):
    ports = iter([6000, 6667, 10080, 54321])

    class Candidate:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def bind(self, address):
            pass

        def getsockname(self):
            return ('127.0.0.1', next(ports))

    monkeypatch.setattr('qf.runtime.socket.socket', Candidate)
    assert chart_address() == 'http://127.0.0.1:54321'


@pytest.mark.filterwarnings(
    "ignore:Bare functions are deprecated, use async ones:DeprecationWarning:"
    "aiohttp.web_urldispatcher"
)
def test_real_sdk_http_server_serves_page_and_reports_ready_without_account(tmp_path):
    class BoundaryApi:
        def __init__(self, **kwargs):
            self._auth = SimpleNamespace(_access_token="offline-fixture")
            self._ins_url, self._md_url = "", ""

        def _print(self, message, *args, **kwargs):
            pass

    async def exercise():
        events = []
        address = chart_address()
        journal = Journal.create(tmp_path, "paper", {})
        api = tracked_api(SimpleNamespace(TqApi=BoundaryApi), journal, web_gui=address,
                          progress=lambda stage, **fields: events.append((stage, fields)))
        helper = object.__new__(TqWebHelper)
        helper._api = api
        helper._http_server_host = "127.0.0.1"
        helper._http_server_port = urlsplit(address).port
        helper._web_dir = str(Path(tqsdk.__file__).parent / "web")
        task = asyncio.create_task(helper.link_httpserver())
        try:
            end = asyncio.get_running_loop().time() + 3
            while not events and asyncio.get_running_loop().time() < end:
                await asyncio.sleep(0.01)
            assert events == [("chart_ready", {"url": address})]
            async with aiohttp.ClientSession(trust_env=False) as client:
                async with client.get(address, timeout=aiohttp.ClientTimeout(total=2)) as response:
                    assert response.status == 200
                    assert "<html" in (await response.text()).lower()
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            journal.close()

    asyncio.run(exercise())
