"""可信桌面页面的最小业务桥接；不向网页暴露文件或命令执行接口。"""

import subprocess
import threading
import webbrowser
from pathlib import Path

from qf.credentials import SavedLogin
from qf.desktop import allowed_chart_url
from qf.market import catalog_rows
from qf.market_session import MarketSession
from qf.window_host import run_window
from qf.workbench_store import WorkbenchStore

REASONS = {
    "connection_auth_or_data_failed": "连接、认证或目录数据未完成，请核对账号与权限后重新连接。",
    "connection_lost": "行情连接中断，当前显示最后收到的数据。",
    "main_contract_changed": "主力合约发生变化，正在重新核实图表。",
    "unknown_selection": "所选品种不在当前市场目录中。",
}
STATUSES = {"idle", "connecting", "ready", "waiting_data", "disconnected", "stopping",
            "stopped", "failed"}
ROW_FIELDS = ("continuous", "name", "exchange", "product", "underlying", "last_price",
              "change_percent", "volume", "open_interest", "quote_time", "data_state")


class WorkbenchBridge:
    def __init__(self, root: Path, session: MarketSession, *, credential_store=None):
        self._root, self._session = root, session
        self._lock = threading.RLock()
        self._store = WorkbenchStore(root / "data/workbench")
        cached = self._store.load()
        self._catalog, self._favorites = cached["catalog"], cached["favorites"]
        self._issue = cached["issue"]
        self._selected = None
        self._login = SavedLogin(root, store=credential_store)

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
            matching = raw.get("selected") == self._selected
            address = address if matching and allowed_chart_url(address) else None
            rows = [{k: row.get(k) for k in ROW_FIELDS} for row in raw.get("rows", [])]
            heartbeat = raw.get("heartbeat_seconds", 0)
            return {"status": status, "catalog": self._catalog, "rows": rows,
                    "selected": self._selected, "chart_url": address,
                    "reason": REASONS.get(raw.get("reason"), ""),
                    "heartbeat_seconds": heartbeat if type(heartbeat) is int else 0,
                    "favorites": list(self._favorites),
                    "issue": self._issue or self._login.info()["issue"],
                    "cache_state": "live" if catalog and status in ("ready", "waiting_data")
                    else "cached" if self._catalog else "empty"}

    def set_view(self, symbols, selected):
        with self._lock:
            known = {r["continuous"] for r in self._catalog}
            if (not isinstance(symbols, list) or len(symbols) > 98
                    or not all(isinstance(s, str) and s in known for s in symbols)
                    or selected is not None and
                    (not isinstance(selected, str) or selected not in known)):
                return {"ok": False, "reason": "所选品种不可用或超过订阅上限。"}
            try:
                favorites = [s for s in self._favorites if s in known]
                self._session.set_view(list(dict.fromkeys([*symbols, *favorites])), selected)
                self._selected = selected
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
