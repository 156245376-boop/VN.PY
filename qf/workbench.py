"""可信桌面页面的最小业务桥接；不向网页暴露文件或命令执行接口。"""

import re
import subprocess
import threading
import webbrowser
from pathlib import Path

from qf.chart_workspace import PERIODS, ChartWorkspaceStore, period_for, validate_panes
from qf.credentials import SavedLogin
from qf.desktop import allowed_chart_url
from qf.history import HISTORY_ISSUES
from qf.market import catalog_rows
from qf.market_account import public_account
from qf.market_session import MarketSession
from qf.market_units import price_unit
from qf.window_host import run_window
from qf.workbench_store import WorkbenchStore

REASONS = {
    "connection_auth_or_data_failed": "连接、认证或目录数据未完成，请核对账号与权限后重新连接。",
    "connection_lost": "行情连接中断，当前显示最后收到的数据。",
    "main_contract_changed": "主力合约发生变化，正在重新核实图表。",
    "unknown_selection": "所选品种不在当前市场目录中。",
    "catalog_loading": "行情服务已连接，正在读取品种目录。",
    "chart_data_unavailable": "当前合约K线未返回或读取失败，其他行情仍可查看。",
}
STATUSES = {"idle", "connecting", "ready", "waiting_data", "disconnected", "stopping",
            "stopped", "failed"}
LOAD_PHASES = {"idle", "connecting", "catalog", "bars", "chart", "ready", "failed", "stopped"}
ROW_FIELDS = ("continuous", "name", "exchange", "product", "underlying", "last_price",
              "change_percent", "volume", "open_interest", "quote_time", "data_state",
              "price_unit", "data_note")


def _history_summary(raw):
    if not isinstance(raw, dict):
        return None
    count = raw.get("valid_count")
    dates = {key: value if isinstance(value := raw.get(key), str)
             and re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", value) else None
             for key in ("first", "last")}
    years, issues = raw.get("years"), raw.get("issues")
    return {"valid_count": count if type(count) is int and count >= 0 else 0, **dates,
            "years": {key: value for key, value in years.items()
                      if isinstance(key, str) and re.fullmatch(r"\d{4}", key)
                      and type(value) is int and value > 0} if isinstance(years, dict) else {},
            "issues": [value for value in issues if isinstance(value, str)
                       and value in HISTORY_ISSUES] if isinstance(issues, list) else []}


class WorkbenchBridge:
    def __init__(self, root: Path, session: MarketSession, *, credential_store=None):
        self._root, self._session = root, session
        self._lock = threading.RLock()
        self._store = WorkbenchStore(root / "data/workbench")
        cached = self._store.load()
        self._catalog, self._favorites = cached["catalog"], cached["favorites"]
        self._issue = cached["issue"]
        self._selected = None
        self._chart_mode = "actual"
        self._login = SavedLogin(root, store=credential_store)
        self._workspace_store = ChartWorkspaceStore(root / 'data/workbench')
        self._workspace_requests = None

    def get_workspace(self):
        with self._lock:
            return self._workspace_store.load()

    def save_workspace(self, workspace):
        with self._lock:
            try:
                self._workspace_store.save(workspace)
                return {'ok': True, 'reason': '布局已保存。'}
            except (OSError, ValueError, TypeError):
                return {'ok': False, 'reason': '布局未保存；原文件已保留，请检查本机布局文件。'}

    def set_workspace(self, symbols, panes):
        with self._lock:
            try:
                requests = validate_panes(panes, requests=True)
                known = {r['continuous'] for r in self._catalog}
                if (not isinstance(symbols, list) or len(symbols) > 100
                        or any(not isinstance(s, str) or s not in known for s in symbols)
                        or any(p['continuous'] is not None and p['continuous'] not in known
                               for p in requests)):
                    raise ValueError('unknown selection')
                favorites = [s for s in self._favorites if s in known]
                self._session.set_workspace(list(dict.fromkeys([*symbols, *favorites])), requests)
                self._workspace_requests = {p['id']: p for p in requests}
                first = next((p for p in requests if p['id'] == 'pane-1'), {})
                self._selected = first.get('continuous')
                self._chart_mode = first.get('mode', 'actual')
                return {'ok': True, 'reason': ''}
            except (ValueError, TypeError):
                return {'ok': False,
                        'reason': '图表设置未应用：品种无效或订阅已达上限，请减少需求或重新连接。'}

    def _public_panes(self, raw, rows):
        output = []
        mappings = {r.get('continuous'): r.get('underlying') for r in rows}
        for value in raw if isinstance(raw, list) else []:
            if not isinstance(value, dict):
                continue
            try:
                request = validate_panes([{k: value.get(k) for k in
                    ('id', 'continuous', 'mode', 'period', 'revision')}], requests=True)[0]
            except (ValueError, TypeError):
                continue
            if (self._workspace_requests is not None
                    and self._workspace_requests.get(request['id']) != request):
                continue
            expected = (request['continuous'] if request['mode'] == 'continuous' else
                        mappings.get(request['continuous']))
            symbol = value.get('symbol')
            if symbol is not None and symbol != expected:
                continue
            duration = PERIODS[period_for(request)] * 1_000_000_000
            if value.get('duration') != duration:
                continue
            output.append({**request, 'symbol': symbol, 'duration': duration,
                           'history': _history_summary(value.get('history')),
                           'status': value.get('status') if value.get('status') in
                           ('idle', 'loading', 'ready', 'unavailable') else 'unavailable',
                           'reason': REASONS.get(value.get('reason'),
                               '订阅容量已达上限，请减少需求或重新连接。' if
                               value.get('reason') == 'subscription_limit' else '')})
        return output

    def get_login_state(self):
        with self._lock:
            return self._login.info()

    def forget_login(self):
        with self._lock:
            try:
                self._login.forget()
                return {"ok": True, "reason": "已忘记账号密码；当前连接不受影响。"}
            except ValueError:
                return {"ok": False, "reason": "忘记账号密码未完成，请稍后重试。"}

    def login(self, user, password, remember=True):
        with self._lock:
            try:
                if self._session.running:
                    raise ValueError("already running")
                credentials = self._login.resolve(user, password)
                self._login.prepare(*credentials, remember)
                self._session.start(*credentials)
                self._selected = None
                self._chart_mode = "actual"
                self._workspace_requests = None
                return {"ok": True, "reason": "正在连接行情，请稍候。"}
            except Exception:
                self._login.discard()
                return {"ok": False,
                        "reason": "未开始连接，请填写或使用已保存的凭证，并确认行情已停止。"}

    def get_state(self):
        with self._lock:
            raw = self._session.snapshot()
            catalog = catalog_rows(raw.get("catalog", []))
            if catalog and catalog != self._catalog:
                self._catalog = catalog
                self._save()
            status = raw.get("status") if raw.get("status") in STATUSES else "failed"
            if status in ("ready", "waiting_data"):
                self._login.confirm()
            elif status in ("failed", "stopped"):
                self._login.discard()
            if self._selected is None:
                self._selected = raw.get("selected")
            address = raw.get("chart_url")
            matching = (raw.get("selected") == self._selected
                        and raw.get("chart_mode", "actual") == self._chart_mode)
            address = address if (matching or self._workspace_requests is not None) and \
                allowed_chart_url(address) else None
            rows = [{k: row.get(k) for k in ROW_FIELDS} for row in raw.get("rows", [])]
            heartbeat = raw.get("heartbeat_seconds", 0)
            display_catalog = [{**row, "price_unit": price_unit(row["exchange"], row["product"])}
                               for row in self._catalog]
            connected = raw.get("connected")
            connected = (connected if type(connected) is bool else
                         None if status in ("connecting", "stopping") else
                         status in ("ready", "waiting_data"))
            chart_status = raw.get("chart_status")
            loading = raw.get("loading", {})
            loading = loading if isinstance(loading, dict) else {}
            phase = loading.get("phase")
            progress = {"phase": phase if isinstance(phase, str) and phase in LOAD_PHASES
                        else "idle"}
            for field in ("done", "total", "elapsed_seconds"):
                value = loading.get(field)
                progress[field] = value if type(value) is int and value >= 0 else None
            chart_symbol = raw.get("chart_symbol")
            if not isinstance(chart_symbol, str) or (chart_symbol != self._selected
                    and chart_symbol not in {row.get("underlying") for row in rows}):
                chart_symbol = None
            revision = raw.get("chart_revision")
            generation = raw.get('generation', 0)
            return {"status": status, "catalog": display_catalog, "rows": rows,
                    'generation': generation if type(generation) is int and generation >= 0 else 0,
                    'panes': self._public_panes(raw.get('panes'), rows),
                    'account': public_account(raw.get('account')),
                    "loading": progress, "chart_mode": self._chart_mode,
                    "chart_symbol": chart_symbol,
                    "chart_revision": revision if matching and type(revision) is int
                    and revision > 0 else 0,
                    "history": _history_summary(raw.get("history")) if matching else None,
                    "connected": connected,
                    "chart_status": chart_status if chart_status in
                    {"idle", "loading", "ready", "unavailable"} else "idle",
                    "selected": self._selected, "chart_url": address,
                    "reason": REASONS.get(raw.get("reason"), ""),
                    "heartbeat_seconds": heartbeat if type(heartbeat) is int else 0,
                    "favorites": list(self._favorites),
                    "issue": self._issue or self._login.info()["issue"],
                    "cache_state": "live" if catalog and status in ("ready", "waiting_data")
                    else "cached" if self._catalog else "empty"}

    def set_view(self, symbols, selected, chart_mode="actual"):
        with self._lock:
            known = {r["continuous"] for r in self._catalog}
            if (not isinstance(symbols, list) or len(symbols) > 98
                    or chart_mode not in ("actual", "continuous")
                    or not all(isinstance(s, str) and s in known for s in symbols)
                    or selected is not None and
                    (not isinstance(selected, str) or selected not in known)):
                return {"ok": False, "reason": "所选品种不可用或超过订阅上限。"}
            try:
                favorites = [s for s in self._favorites if s in known]
                self._session.set_view(list(dict.fromkeys([*symbols, *favorites])), selected,
                                       chart_mode)
                self._selected = selected
                self._chart_mode = chart_mode
                return {"ok": True, "reason": ""}
            except ValueError:
                return {"ok": False, "reason": "当前行情订阅已达到上限，请减少自选。"}

    def set_favorites(self, symbols):
        with self._lock:
            known = {r["continuous"] for r in self._catalog}
            if (not isinstance(symbols, list) or len(symbols) > 50
                    or not all(isinstance(s, str) and s in known for s in symbols)):
                return {"ok": False, "reason": "自选需来自市场目录，最多 50 项。"}
            before = self._favorites
            self._favorites = list(dict.fromkeys(symbols))
            if not self._save():
                self._favorites = before
                return {"ok": False, "reason": self._issue}
            return {"ok": True, "reason": "自选已保存。"}

    def _save(self):
        try:
            self._store.save(self._catalog, self._favorites)
            return True
        except (OSError, ValueError):
            self._issue = "本机目录或自选无法保存，原文件已保留；请检查 data/workbench。"
            return False

    def open_resource(self, key):
        urls = {"docs": "https://doc.shinnytech.com/tqsdk/latest/usage/web_gui.html",
                "jin10": "https://open.jin10.com/",
                "calendar": "https://rili.jin10.com/"}
        try:
            if key == "legacy":
                subprocess.Popen(
                    [str(self._root / ".venv-tqsdk/Scripts/pythonw.exe"), "-I", "-X", "utf8",
                     "-B", str(self._root / "tools/gui_entry.py")], cwd=self._root,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            elif isinstance(key, str) and key in urls:
                webbrowser.open(urls[key])
            else:
                return {"ok": False, "reason": "该入口不可用。"}
            return {"ok": True, "reason": "已打开。"}
        except (OSError, ValueError, TypeError):
            return {"ok": False, "reason": "无法打开入口，请核对本机环境。"}

    def disconnect(self):
        with self._lock:
            self._login.discard()
        self._session.stop()
        return {"ok": True, "reason": "正在断开行情连接。"}

    def _request_close(self):
        self._session.stop()
        return not self._session.running


def main():
    root = Path(__file__).resolve().parent.parent
    bridge = WorkbenchBridge(root, MarketSession())
    run_window(root / "qf/web/index.html", bridge, bridge._request_close)
