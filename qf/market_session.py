"""一个线程拥有只读 TqApi；业务对象仅以白名单快照离开线程。"""

import asyncio
import contextlib
import copy
import logging
import os
import threading
import time

from qf.market import CONTINUOUS, catalog_rows, quote_row
from qf.runtime import chart_address


def _close_api(api):
    """先释放本会话图表请求，避免 SDK 3.10.2 等待未返回的 peek_message。"""
    loop = getattr(api, "_loop", None)
    if loop is not None and not loop.is_closed():
        from aiohttp.web_protocol import RequestHandler

        async def release_chart_requests():
            codes = {RequestHandler.start.__code__, RequestHandler._handle_request.__code__}
            tasks = [task for task in asyncio.all_tasks(loop)
                     if getattr(task.get_coro(), "cr_code", None) in codes]
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        create_task = getattr(api, "create_task", loop.create_task)
        task = create_task(release_chart_requests())
        if hasattr(api, "_run_until_task_done"):
            # SDK 会主动 stop 自有事件循环，必须使用它的驱动器推进清理任务。
            api._run_until_task_done(task)
            task.result()
        else:
            loop.run_until_complete(task)
    api.close()


class MarketSession:
    def __init__(self, *, sdk=None):
        self._sdk = sdk
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self.thread = None
        self._view = (0, (), None)
        self._started = time.monotonic()
        self._state = {"status": "idle", "catalog": [], "rows": [], "selected": None,
                       "chart_url": None, "reason": "", "heartbeat_seconds": 0,
                       "connected": False, "chart_status": "idle"}

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, user: str, password: str) -> None:
        with self._lock:
            if self.running:
                raise ValueError("行情会话已在运行")
            if (not isinstance(user, str) or not isinstance(password, str)
                    or not user or not password):
                raise ValueError("请填写快期账号与密码")
            self._stop.clear()
            self._started = time.monotonic()
            self._view = (0, (), None)
            self._state.update(status="connecting", reason="", rows=[], chart_url=None,
                               selected=None, connected=None, chart_status="loading")
            self.thread = threading.Thread(target=self._run, args=(user, password), daemon=False)
            self.thread.start()

    def set_view(self, continuous: list[str], selected: str | None) -> None:
        if (not isinstance(continuous, list) or len(continuous) > 98
                or not all(isinstance(s, str) and CONTINUOUS.fullmatch(s) for s in continuous)
                or selected is not None and
                (not isinstance(selected, str) or not CONTINUOUS.fullmatch(selected))):
            raise ValueError("品种选择无效或超过订阅上限")
        with self._lock:
            symbols = tuple(dict.fromkeys([*continuous, *([selected] if selected else [])]))
            if len(symbols) > 98:
                raise ValueError("当前列表超过订阅上限")
            self._view = (self._view[0] + 1, symbols, selected)
            if self._state["selected"] != selected:
                self._state.update(selected=selected, chart_url=None, chart_status="loading")

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._state)

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            self._state.update(chart_url=None)
            if self.running:
                self._state["status"] = "stopping"

    def _publish(self, *, version=None, **values):
        with self._lock:
            if version is None or version == self._view[0]:
                self._state.update(values)

    def _run(self, user, password):
        previous = logging.root.manager.disable
        try:
            logging.disable(logging.CRITICAL)
            with open(os.devnull, "w", encoding="utf-8") as sink:
                with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                    sdk = self._sdk
                    if sdk is None:
                        import tqsdk as sdk
                    self._stream(sdk, user, password)
        except Exception:
            self._publish(status="failed", reason="connection_auth_or_data_failed", chart_url=None,
                          connected=False, chart_status="unavailable")
        finally:
            user = password = None
            logging.disable(previous)
            if self._stop.is_set() and self.snapshot()["status"] != "failed":
                self._publish(status="stopped", chart_url=None, reason="", connected=False,
                              chart_status="idle")

    def _stream(self, sdk, user, password):
        catalog = []
        while not self._stop.is_set():
            address = chart_address()
            chart_ready = threading.Event()

            class ReadOnlyApi(sdk.TqApi):
                _ready_signal = chart_ready
                _chart_address = address

                def _print(self, message, *args, **kwargs):
                    if isinstance(message, str) and message.startswith(
                            f"您可以访问 {self._chart_address} "):
                        self._ready_signal.set()

                def insert_order(self, *args, **kwargs):
                    raise RuntimeError("行情会话为只读，禁止下单")

            self._publish(status="connecting", chart_url=None, connected=None,
                          chart_status="loading")
            api = ReadOnlyApi(sdk.TqSim(), auth=sdk.TqAuth(user, password), debug=False,
                              disable_print=True, web_gui=address)
            try:
                if self._stop.is_set():
                    break
                self._publish(status="waiting_data", connected=True, reason="catalog_loading")
                if not catalog:
                    symbols = list(api.query_quotes(ins_class="CONT"))
                    symbols = [s for s in symbols if CONTINUOUS.fullmatch(s)]
                    if not symbols:
                        raise ValueError("没有可读取的国内期货目录")
                    raw = []
                    for offset in range(0, len(symbols), 50):
                        if self._stop.is_set():
                            break
                        raw.extend(api.query_symbol_info(symbols[offset:offset + 50])
                                   .to_dict("records"))
                    if self._stop.is_set():
                        break
                    catalog = catalog_rows(raw)
                    if not catalog:
                        raise ValueError("目录元数据未就绪")
                    self._publish(catalog=catalog, reason="")
                    with self._lock:
                        if self._view[2] is None:
                            default = next((r["continuous"] for r in catalog
                                            if r["product"] == "rb"), catalog[0]["continuous"])
                            requested = list(self._view[1])[:97] or [
                                r["continuous"] for r in catalog[:40]]
                            self.set_view(requested, default)
                self._serve_view(api, catalog, address, chart_ready)
            finally:
                _close_api(api)

    def _serve_view(self, api, catalog, address, chart_ready):
        known = {r["continuous"]: r for r in catalog}
        quotes, seen, subscribed = {}, set(), set()
        connections = {}
        active_selected, chart_symbol = None, None
        chart_failed = False
        initialized, connected = False, True
        while not self._stop.is_set():
            with self._lock:
                version, requested, selected = self._view
            if selected and selected not in known or any(s not in known for s in requested):
                self._publish(version=version, reason="unknown_selection", chart_url=None)
                if self._stop.wait(0.1):
                    break
                continue
            if initialized and selected != active_selected:
                return
            desired = set(requested)
            if len(subscribed | desired) > 99:
                return
            for symbol in desired:
                if symbol not in quotes:
                    quotes[symbol] = api.get_quote(symbol)
                    subscribed.add(symbol)
            active_selected, initialized = selected, True
            if selected:
                underlying = quotes[selected].get("underlying_symbol", "")
                if underlying:
                    if chart_symbol and underlying != chart_symbol:
                        self._publish(chart_url=None, reason="main_contract_changed")
                        return
                    if not chart_symbol and not chart_failed:
                        if len(subscribed | {underlying}) > 100:
                            return
                        try:
                            api.get_kline_serial(underlying, 60, data_length=200)
                            subscribed.add(underlying)
                            chart_symbol = underlying
                        except Exception:
                            chart_failed = True
            api.wait_update(deadline=time.time() + 0.2)
            # 映射可能在本次更新中改变；发布前再次核对，避免新合约配旧图。
            if selected and chart_symbol and (
                    quotes[selected].get("underlying_symbol", "") != chart_symbol):
                self._publish(version=version, chart_url=None, reason="main_contract_changed")
                return
            # SDK 3.10.2 无公开 connected；仅读取已核实的通知码，丢弃通知原文。
            for key, notify in list(getattr(api, "_data", {}).get("notify", {}).items()):
                if key.startswith("_") or key in seen:
                    continue
                seen.add(key)
                connection = notify.get("conn_id", "feed")
                if notify.get("code") in (2019112910, 2019112911):
                    connections[connection] = False
                elif notify.get("code") in (2019112901, 2019112902):
                    connections[connection] = True
            connected = all(connections.values())
            rows = [quote_row(known[s], quotes[s], connected=connected) for s in requested]
            ready = any(r["data_state"] == "ready" for r in rows)
            status = "disconnected" if not connected else "ready" if ready else "waiting_data"
            chart_url = address if connected and chart_symbol and chart_ready.is_set() else None
            self._publish(version=version, status=status, rows=rows, selected=selected,
                          connected=connected, chart_url=chart_url,
                          chart_status="ready" if chart_url else "unavailable" if chart_failed
                          else "loading" if selected else "idle",
                          reason="connection_lost" if not connected else
                          "chart_data_unavailable" if chart_failed else "",
                          heartbeat_seconds=int(time.monotonic() - self._started))
