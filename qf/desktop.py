"""本机窗口的后台会话；凭证只经内存传递，输出只经白名单队列。"""

import contextlib
import logging
import math
import os
import queue
import re
import threading
from pathlib import Path

from qf.config import load_config
from qf.runtime import execute

STAGES = {"sdk_loading", "sdk_ready", "record_creating", "connecting", "waiting_data",
          "data_ready", "backtesting", "observing", "paper_active", "heartbeat", "stopping",
          "done", "chart_ready", "report_ready", "baseline_complete"}
STATUSES = {"data_ready", "backtest_finished", "stopped", "failed", "frozen"}
RUN_ID = re.compile(r"\d{8}T\d{6}-[0-9a-f]{12}\Z")


def allowed_chart_url(url):
    if not isinstance(url, str):
        return False
    match = re.fullmatch(r"http://127\.0\.0\.1:([1-9][0-9]{0,4})/?", url)
    return bool(match and int(match[1]) <= 65535)


def public_result(result):
    status = result.get("status")
    safe = {"status": status if status in STATUSES else "failed"}
    reasons = {"requested_stop", "historical_replay_completed", "double_fee_replay_failed",
               "current_quote_and_minute_subscription_verified", "startup_or_local_record_error",
               "sdk_or_auth_or_permission_error", "cancellation_unconfirmed",
               "data_timeout_or_permission_unavailable", "new_run_requires_flat_account",
               "new_run_requires_no_orders", "connection_lost", "contract_near_expiry",
               "underlying_changed", "sdk_cost_missing", "comparison_cancelled"}
    safe["reason"] = (result.get("reason") if result.get("reason") in reasons
                      else "operation_not_completed")
    for field in ("run_id", "double_fee_run_id"):
        value = result.get(field)
        if isinstance(value, str) and RUN_ID.fullmatch(value):
            safe[field] = value
    for field in ("final_equity", "commission", "day_commission"):
        value = result.get(field)
        if type(value) in (int, float) and math.isfinite(value):
            safe[field] = value
    return safe


class DesktopSession:
    def __init__(self, results_root, *, execute_fn=None):
        self.results_root = Path(results_root)
        self.execute_fn = execute_fn or execute
        self.messages = queue.Queue()
        self.thread = None
        self.stop_event = threading.Event()

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, mode, user, password, *, activate=False):
        if self.running:
            raise ValueError("已有运行中的实验")
        if mode not in {"paper", "backtest"} or not user or not password:
            raise ValueError("请填写快期账号和密码")
        if activate and mode != "paper":
            raise ValueError("仅快期模拟可以启用委托")
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run,
                                       args=(mode, user, password, activate), daemon=False)
        self.thread.start()

    def _progress(self, stage, **fields):
        if stage not in STAGES:
            return
        message = {"type": "progress", "stage": stage}
        if stage == "chart_ready":
            if not allowed_chart_url(fields.get("url")):
                return
            message["url"] = fields["url"]
        for key in ("elapsed", "duration"):
            value = fields.get(key)
            if type(value) is int and value >= 0:
                message[key] = value
        self.messages.put(message)

    def _run(self, mode, user, password, activate):
        previous = logging.root.manager.disable
        try:
            logging.disable(logging.CRITICAL)
            with open(os.devnull, "w", encoding="utf-8") as sink:
                with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                    project = Path(__file__).resolve().parent.parent
                    config_path = project / "experiments/rb-demo.toml"
                    config = load_config(config_path)
                    result = self.execute_fn(
                        mode, config, self.results_root, (user, password), activate=activate,
                        chart=True, hold_chart=mode == "backtest", progress=self._progress,
                        stop_requested=self.stop_event.is_set)
            result = public_result(result)
        except Exception:
            result = {"status": "failed", "reason": "startup_or_local_record_error"}
        finally:
            user = password = None
            logging.disable(previous)
        self.messages.put({"type": "result", "result": result})

    def stop(self):
        self.stop_event.set()

    def drain(self):
        while True:
            try:
                yield self.messages.get_nowait()
            except queue.Empty:
                return
