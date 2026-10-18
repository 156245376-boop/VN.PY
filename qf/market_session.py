"""一个线程拥有只读 TqApi；业务对象仅以白名单快照离开线程。"""

import asyncio
import contextlib
import copy
import logging
import os
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from qf.chart_workspace import PERIODS, period_for, validate_panes
from qf.history import summarize_history
from qf.market import CONTINUOUS, catalog_rows, quote_row
from qf.market_account import account_snapshot
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
        self._view = (0, (), None, "actual")
        self._next_chart_revision = 0
        self._generation = 0
        self._pane_requests = []
        self._subscribed = set()
        self._mappings = {}
        self._configured = False
        self._started = time.monotonic()
        self._loading_started = self._started
        self._state = {"status": "idle", "catalog": [], "rows": [], "selected": None,
                       "chart_url": None, "reason": "", "heartbeat_seconds": 0,
                       "generation": 0, "panes": [], "account": None,
                       "connected": False, "chart_status": "idle", "chart_mode": "actual",
                       "chart_symbol": None, "chart_revision": None, "history": None,
                       "loading": {"phase": "idle", "done": 0, "total": None,
                                   "elapsed_seconds": 0}}

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
            self._view = (0, (), None, "actual")
            self._pane_requests = []
            self._subscribed = set()
            self._mappings = {}
            self._configured = False
            self._generation += 1
            self._state.update(generation=self._generation, panes=[], status="connecting",
                               reason="", rows=[], chart_url=None, account=None,
                               selected=None, connected=None, chart_status="loading",
                               chart_symbol=None, chart_mode="actual", chart_revision=None,
                               history=None)
            self._set_loading("connecting")
            self.thread = threading.Thread(target=self._run, args=(user, password), daemon=False)
            self.thread.start()

    def set_view(self, continuous: list[str], selected: str | None,
                 chart_mode: str = "actual") -> None:
        with self._lock:
            old = next((p for p in self._pane_requests if p["id"] == "pane-1"), None)
            same = old and (old["continuous"], old["mode"]) == (selected, chart_mode)
            if not same:
                self._next_chart_revision += 1
            revision = old["revision"] if same else self._next_chart_revision
            self.set_workspace(continuous, [{"id": "pane-1", "continuous": selected,
                                "mode": chart_mode, "period": None, "revision": revision}])

    def set_workspace(self, symbols: list[str], panes: list[dict]) -> None:
        requests = validate_panes(panes, requests=True)
        if (not isinstance(symbols, list) or len(symbols) > 100
                or any(not isinstance(s, str) or not CONTINUOUS.fullmatch(s) for s in symbols)):
            raise ValueError("品种选择无效或超过订阅上限")
        with self._lock:
            desired = set(symbols) | {p["continuous"] for p in requests if p["continuous"]}
            known = {r["continuous"] for r in self._state["catalog"]}
            if known and not desired <= known:
                raise ValueError("所选品种不在目录中")
            actual = {self._mappings.get(p["continuous"]) for p in requests
                      if p["mode"] == "actual" and p["continuous"]}
            if len(self._subscribed | desired | (actual - {None, ""})) > 100:
                raise ValueError("当前行情订阅已达到上限，请减少需求或重新连接")
            requested = tuple(dict.fromkeys([*symbols, *[p["continuous"] for p in requests
                                                        if p["continuous"]]]))
            if requested == self._view[1] and requests == self._pane_requests:
                return
            first = next((p for p in requests if p["id"] == "pane-1"), None)
            selected, mode = (first["continuous"], first["mode"]) if first else (None, "actual")
            changed = self._pane_requests != requests
            self._pane_requests = requests
            self._configured = True
            self._view = (self._view[0] + 1, requested, selected, mode)
            if changed:
                previous = {p['id']: p for p in self._state['panes']}
                next_states = []
                for p in requests:
                    old_state = previous.get(p['id'], {})
                    next_states.append(old_state if all(old_state.get(k) == v
                                       for k, v in p.items()) else
                                       {**p, 'symbol': None, 'duration': PERIODS[period_for(p)]
                                        * 1_000_000_000, 'history': None, 'status': 'loading',
                                        'reason': ''})
                first_state = next((p for p in next_states if p['id'] == 'pane-1'), {})
                self._state.update(selected=selected, chart_mode=mode, panes=next_states,
                                   chart_status=first_state.get('status', 'idle'),
                                   chart_symbol=first_state.get('symbol'),
                                   chart_revision=first_state.get('revision') if
                                   first_state.get('status') == 'ready' else None,
                                   history=first_state.get('history'))
                if not any(p['status'] == 'ready' for p in next_states):
                    self._state['chart_url'] = None
                self._set_loading("bars")

    def snapshot(self) -> dict:
        with self._lock:
            if self._state["loading"]["phase"] in ("connecting", "catalog", "bars", "chart"):
                self._state["loading"]["elapsed_seconds"] = int(
                    time.monotonic() - self._loading_started)
            snapshot = copy.deepcopy(self._state)
            if snapshot.get('account') and snapshot.get('connected') is not True:
                snapshot['account']['connected'] = False
            return snapshot

    def _set_loading(self, phase, done=0, total=None, *, version=None):
        with self._lock:
            if version is not None and (version != self._view[0] or self._stop.is_set()):
                return
            if phase != self._state["loading"]["phase"]:
                self._loading_started = time.monotonic()
            self._state["loading"] = {"phase": phase, "done": done, "total": total,
                                      "elapsed_seconds": int(
                                          time.monotonic() - self._loading_started)}

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            self._state.update(chart_url=None, chart_status="idle", chart_revision=None,
                               history=None)
            if self.running:
                self._state["status"] = "stopping"

    def _publish(self, *, version=None, **values):
        with self._lock:
            if version is not None and self._stop.is_set():
                return
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
            self._set_loading("failed")
            self._publish(status="failed", reason="connection_auth_or_data_failed", chart_url=None,
                          connected=False, chart_status="unavailable")
        finally:
            user = password = None
            logging.disable(previous)
            if self._stop.is_set() and self.snapshot()["status"] != "failed":
                self._set_loading("stopped")
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
                          chart_status="loading", chart_revision=None, history=None)
            self._set_loading("connecting")
            api = ReadOnlyApi(sdk.TqSim(), auth=sdk.TqAuth(user, password), debug=False,
                              disable_print=True, web_gui=address)
            try:
                if self._stop.is_set():
                    break
                self._publish(status="waiting_data", connected=True, reason="catalog_loading")
                if not catalog:
                    self._set_loading("catalog")
                    symbols = list(api.query_quotes(ins_class="CONT"))
                    symbols = [s for s in symbols if CONTINUOUS.fullmatch(s)]
                    if not symbols:
                        raise ValueError("没有可读取的国内期货目录")
                    raw = []
                    self._set_loading("catalog", total=len(symbols))
                    for offset in range(0, len(symbols), 50):
                        if self._stop.is_set():
                            break
                        raw.extend(api.query_symbol_info(symbols[offset:offset + 50])
                                   .to_dict("records"))
                        self._set_loading("catalog", min(offset + 50, len(symbols)), len(symbols))
                    if self._stop.is_set():
                        break
                    catalog = catalog_rows(raw)
                    if not catalog:
                        raise ValueError("目录元数据未就绪")
                    self._publish(catalog=catalog, reason="")
                    with self._lock:
                        if not self._configured or (self._pane_requests and
                                all(p["continuous"] is None for p in self._pane_requests)):
                            default = next((r["continuous"] for r in catalog
                                            if r["product"] == "rb"), catalog[0]["continuous"])
                            requested = list(self._view[1])[:97] or [
                                r["continuous"] for r in catalog[:40]]
                            self.set_view(requested, default, self._view[3])
                self._set_loading("bars")
                self._serve_view(api, catalog, address, chart_ready)
            finally:
                _close_api(api)

    def _serve_view(self, api, catalog, address, chart_ready):
        known = {r["continuous"]: r for r in catalog}
        quotes, seen, serials, failures = {}, set(), {}, set()
        connections = {}
        account = None
        while not self._stop.is_set():
            with self._lock:
                version, requested, _, _ = self._view
                panes = copy.deepcopy(self._pane_requests)
            for symbol in requested:
                if symbol in known and symbol not in quotes:
                    quotes[symbol] = api.get_quote(symbol)
                    with self._lock:
                        self._subscribed.add(symbol)
            prepared = []
            for pane in panes:
                symbol = pane["continuous"]
                duration = PERIODS[period_for(pane)]
                target = (symbol if pane["mode"] == "continuous" else
                          quotes.get(symbol, {}).get("underlying_symbol")) if symbol else None
                state = {**pane, "symbol": target, "duration": duration * 1_000_000_000,
                         "history": None, "status": "loading" if symbol else "idle", "reason": ""}
                key = (target, duration)
                if target:
                    with self._lock:
                        capacity = len(self._subscribed | {target}) <= 100
                    if not capacity:
                        state.update(status="unavailable", reason="subscription_limit")
                    else:
                        attempt = (key, pane["revision"])
                        if key not in serials and attempt not in failures:
                            try:
                                serials[key] = api.get_kline_serial(target, duration,
                                                    data_length=3000 if duration == 86400 else 200)
                                with self._lock:
                                    self._subscribed.add(target)
                            except Exception:
                                failures.add(attempt)
                        if attempt in failures:
                            state.update(status="unavailable", reason="chart_data_unavailable")
                prepared.append((state, key))
            api.wait_update(deadline=time.time() + .2)
            with self._lock:
                if self._stop.is_set():
                    return
                if version != self._view[0]:
                    continue
                self._mappings = {s: q.get("underlying_symbol", "") for s, q in quotes.items()}
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
            if connected and hasattr(api, 'get_account'):
                try:
                    account = account_snapshot(api, connected=True, observed_at=datetime.now(
                        ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S'))
                except Exception:
                    if account:
                        account = {**account, 'connected': False}
            elif account:
                account = {**account, 'connected': False}
            rows = [quote_row(known[s], quotes[s], connected=connected)
                    for s in requested if s in known and s in quotes]
            published = []
            for state, key in prepared:
                current = (state["continuous"] if state["mode"] == "continuous" else
                           self._mappings.get(state["continuous"]))
                if current != state["symbol"]:
                    state.update(symbol=None, history=None, status="loading",
                                 reason="main_contract_changed")
                elif key in serials and api.is_serial_ready(serials[key]):
                    history = summarize_history(serials[key], key[1])
                    state.update(history=history, status="unavailable" if history["issues"] else
                                 "ready" if chart_ready.is_set() else "loading",
                                 reason="chart_data_unavailable" if history["issues"] else "")
                published.append(state)
            first = next((p for p in published if p["id"] == "pane-1"), {})
            ready = any(p["status"] == "ready" for p in published)
            address_now = address if connected and ready else None
            failed = any(p["status"] == "unavailable" for p in published)
            phase = "ready" if ready else "failed" if failed else "chart"
            self._set_loading(phase, version=version)
            self._publish(version=version,
                          status="disconnected" if not connected else "ready" if any(
                              r["data_state"] == "ready" for r in rows) else "waiting_data",
                          rows=rows, panes=published, account=account,
                          connected=connected, chart_url=address_now,
                          selected=first.get("continuous"), chart_mode=first.get("mode", "actual"),
                          chart_symbol=first.get("symbol"), chart_revision=first.get("revision"),
                          history=first.get("history"), chart_status=first.get("status", "idle"),
                          reason="connection_lost" if not connected else first.get("reason", ""),
                          heartbeat_seconds=int(time.monotonic() - self._started))
