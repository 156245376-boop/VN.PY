"""TqSdk 3.10.2 专用薄适配；仅本地回测与快期模拟。"""

import hashlib
import importlib.metadata
import json
import math
import secrets
import socket
import subprocess
import time
from numbers import Real
from pathlib import Path

from qf.journal import Journal, PaperLock
from qf.safety import Frozen, Guard, settle_stop
from qf.strategy import completed_signal

DISCONNECTED = {2019112910, 2019112911}


def emit_progress(progress, stage, **fields):
    if progress is not None:
        try:
            progress(stage, **fields)
        except Exception:
            # 终端关闭或输出失败不能妨碍运行状态核对和撤单收尾。
            pass


def provenance(*, source_root=None):
    repository = Path(__file__).resolve().parent.parent
    root = Path(source_root) if source_root else repository
    digest = hashlib.sha256()
    manifest = {}
    for folder in (root / "qf", root / "tools", root / "experiments"):
        for path in sorted(folder.rglob("*")):
            if '__pycache__' in path.parts:
                continue
            if path.is_file():
                digest.update(str(path.relative_to(root)).encode())
                digest.update(path.read_bytes())
                manifest[str(path.relative_to(root))] = (
                    hashlib.sha256(path.read_bytes()).hexdigest())
    for name in ("pyproject.toml", "uv.lock"):
        digest.update((root / name).read_bytes())
    process_options = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repository, capture_output=True,
                            text=True, check=True, **process_options).stdout.strip()
    changed = subprocess.run(["git", "status", "--porcelain"], cwd=repository, capture_output=True,
                             check=True, **process_options).stdout
    summary = subprocess.run(["git", "diff", "HEAD", "--stat"], cwd=repository,
                             capture_output=True, check=True,
                             **process_options).stdout.decode("utf-8", "replace")
    return {"commit": commit, "dirty": bool(changed), "source_sha256": digest.hexdigest(),
            "source_manifest": manifest, "change_summary": summary,
            "sdk": importlib.metadata.version("tqsdk"), "timezone": "Asia/Shanghai"}


def positions_snapshot(positions):
    return {key: (int(p.pos_long), int(p.pos_short)) for key, p in positions.items()
            if not key.startswith("_")}


def trades_snapshot(trades):
    return [{"key": str(t.trade_id), "order_id": str(t.order_id),
             "symbol": f"{t.exchange_id}.{t.instrument_id}", "direction": str(t.direction),
             "offset": str(t.offset), "volume": int(t.volume), "price": float(t.price),
             "time_ns": int(t.trade_date_time)}
            for key, t in trades.items() if not key.startswith("_")]


def check_connections(api, seen):
    # SDK 3.10.2 没有公开 connected；只在此处读取已核实的私有通知结构。
    for key, notify in api._data.get("notify", {}).items():
        if key.startswith("_") or key in seen:
            continue
        seen.add(key)
        if notify.get("code") in DISCONNECTED:
            raise Frozen("connection_lost")


def rows_of(serial):
    return serial[["datetime", "close"]].to_dict("records")


def wait_ready(api, predicate, timeout, seen):
    end = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= end:
            raise Frozen("data_timeout_or_permission_unavailable")
        api.wait_update(deadline=time.time() + min(1, end - time.monotonic()))
        check_connections(api, seen)
    check_connections(api, seen)


def chart_address():
    # 高位端口避免系统分配到 Chromium 禁用的 6000/6667/10080 等服务端口。
    for _ in range(64):
        with socket.socket() as candidate:
            try:
                candidate.bind(("127.0.0.1", 20000 + secrets.randbelow(45000)))
                port = candidate.getsockname()[1]
                if port >= 20000:
                    return f"http://127.0.0.1:{port}"
            except OSError:
                continue
    raise OSError("没有可用的本机图表端口")


def tracked_api(sdk, journal, *, web_gui=False, progress=None, **kwargs):
    class ResearchApi(sdk.TqApi):
        execution_guard = None

        def _print(self, message, *args, **print_kwargs):
            # 只拦截 SDK 在 HTTP 服务就绪后发出的地址通知，不转发任何通知原文。
            if web_gui and isinstance(message, str) and message.startswith(
                    f"您可以访问 {web_gui} "):
                emit_progress(progress, "chart_ready", url=web_gui)
            return super()._print(message, *args, **print_kwargs)

        def insert_order(self, symbol, direction, offset="", volume=0, limit_price=None,
                         advanced=None, order_id=None, account=None, offset_leg2=""):
            if self.execution_guard is None:
                raise Frozen("read_only_order_blocked")
            check_connections(self, set())
            for fill in trades_snapshot(self.get_trade()):
                self.execution_guard.accept_fill(fill)
            self.execution_guard.check(positions_snapshot(self.get_position()), self.get_order())
            self.execution_guard.before_order(symbol, direction, offset, volume)
            order = super().insert_order(symbol=symbol, direction=direction, offset=offset,
                                         volume=volume, limit_price=limit_price, advanced=advanced,
                                         order_id=order_id, account=account,
                                         offset_leg2=offset_leg2)
            # insert_order 先入本地队列；下次 wait_update 发出前持久记录所有权。
            journal.order(order.order_id, symbol, direction, offset, volume)
            return order

    return ResearchApi(debug=False, disable_print=True, web_gui=web_gui, **kwargs)


def _one(mode, config, root, credentials, sdk, *, activate=False, resume=None,
         duration=0, stop_requested=lambda: False, fee_multiplier=1, progress=None,
         chart=False, hold_chart=False):
    emit_progress(progress, "record_creating")
    if resume:
        journal = Journal.resume(root / resume, config.public())
    else:
        journal = Journal.create(root, mode, config.public(), provenance())
    api, task, guard = None, None, None
    orders = {}
    seen = set()
    status, reason = "failed", "sdk_or_auth_or_permission_error"
    result = {"run_id": journal.path.name}
    is_paper = mode == "paper"
    try:
        if resume:
            original = json.loads((journal.path / "metadata.json").read_text(encoding="utf-8"))
            if original.get("source_sha256") != provenance()["source_sha256"]:
                raise Frozen("resume_code_changed")
        if is_paper:
            salt = journal.get("identity_salt", secrets.token_hex(32))
            binding = hashlib.sha256((salt + credentials[0]).encode()).hexdigest()
            if resume and journal.get("account_binding") != binding:
                raise Frozen("resume_account_mismatch")
            journal.set("identity_salt", salt)
            journal.set("account_binding", binding)
        emit_progress(progress, "connecting")
        account = sdk.TqKq() if is_paper else sdk.TqSim(init_balance=config.initial_balance)
        kwargs = {"account": account, "auth": sdk.TqAuth(*credentials)}
        if mode == "backtest":
            kwargs["backtest"] = sdk.TqBacktest(start_dt=config.start, end_dt=config.end)
            # 3.10.2 的 date 参数按交易日扩展，包含前一日（周一为上周五）夜盘。
            start_ns, end_ns = kwargs["backtest"]._start_dt, kwargs["backtest"]._end_dt
            journal.set("replay_bounds_ns", [start_ns, end_ns])
        api = tracked_api(sdk, journal, web_gui=chart_address() if chart else False,
                          progress=progress, **kwargs)
        emit_progress(progress, "waiting_data")
        if mode == "backtest":
            symbol = config.symbol
            continuous = None
        else:
            continuous = api.get_quote(config.continuous)
            wait_ready(api, lambda: bool(continuous.underlying_symbol),
                       config.timeout_seconds, seen)
            symbol = continuous.underlying_symbol
            if not symbol.startswith("SHFE.rb") or not symbol[7:].isdigit():
                raise Frozen("unexpected_underlying")
        if resume and journal.get("symbol") != symbol:
            raise Frozen("underlying_changed")
        journal.set("symbol", symbol)
        result["symbol"] = symbol
        quote = api.get_quote(symbol)
        serial = api.get_kline_serial(symbol, 60, data_length=config.period + 1)
        acct = api.get_account()
        positions, orders, trades = api.get_position(), api.get_order(), api.get_trade()
        wait_ready(api, lambda: (math.isfinite(quote.last_price)
                                and completed_signal(rows_of(serial), config.period) is not None
                                and math.isfinite(acct.balance)), config.timeout_seconds, seen)
        journal.set("initial_equity", float(acct.balance))
        journal.set("data_time", str(quote.datetime))
        emit_progress(progress, "data_ready")
        if mode == "data-check":
            journal.set("data_check", {"continuous": config.continuous, "symbol": symbol,
                                       "quote_time": str(quote.datetime),
                                       "completed_bar_ns": int(serial.iloc[-2].datetime)})
            status, reason = "data_ready", "current_quote_and_minute_subscription_verified"
            result["quote_time"] = str(quote.datetime)
            result.update(status=status, reason=reason)
            return result
        if mode == "backtest":
            fee, margin = account.get_commission(symbol), account.get_margin(symbol)
            if not (math.isfinite(fee) and fee >= 0 and math.isfinite(margin) and margin > 0):
                raise Frozen("sdk_cost_missing")
            account.set_commission(symbol, fee * fee_multiplier)
            journal.set("cost", {"source": "SDK_per_lot_model", "commission": fee * fee_multiplier,
                                 "margin": margin, "fee_multiplier": fee_multiplier})
            result["commission_per_lot"] = fee * fee_multiplier
        else:
            journal.set("cost", {"source": "TqKq_server_account", "editable": False})
        guard = Guard(journal, symbol)
        if not resume:
            guard.baseline = {t["key"] for t in trades_snapshot(trades)}
            journal.set("baseline_trades", sorted(guard.baseline))
        else:
            for fill in trades_snapshot(trades):
                guard.accept_fill(fill)
        guard.start(positions_snapshot(positions), orders,
                    activate=activate or mode == "backtest", resume=bool(resume))
        api.execution_guard = guard
        if guard.enabled:
            task = sdk.TargetPosTask(api, symbol)
        start_time = time.monotonic()
        emit_progress(progress, ("paper_active" if activate else "observing")
                      if is_paper else "backtesting", elapsed=0, duration=duration)
        next_heartbeat = 15
        pending_since = None
        submitted_target = None
        # paper 启动时跳过已有历史柱；只从下一根新完成柱开始。
        initial_bar = int(serial.iloc[-2].datetime) if is_paper else 0
        while True:
            elapsed = int(time.monotonic() - start_time) if is_paper else 0
            if is_paper and elapsed >= next_heartbeat:
                emit_progress(progress, "heartbeat", elapsed=elapsed, duration=duration)
                next_heartbeat = (elapsed // 15 + 1) * 15
            check_connections(api, seen)
            for fill in trades_snapshot(trades):
                guard.accept_fill(fill)
            guard.check(positions_snapshot(positions), orders)
            if continuous and continuous.underlying_symbol != symbol:
                guard.freeze("underlying_changed")
            if is_paper and (quote.expired or not math.isfinite(quote.expire_datetime)
                             or quote.expire_datetime <= time.time() + 86400):
                guard.freeze("contract_near_expiry")
            signal = completed_signal(rows_of(serial), config.period)
            if signal:
                minute, target = signal
                in_range = is_paper or start_ns <= minute <= end_ns
                inputs = rows_of(serial)[-config.period - 1:-1]
                if minute > initial_bar and in_range and journal.signal(minute, target, inputs):
                    if task:
                        task.set_target_volume(target)
                        submitted_target = target
                    journal.applied(minute)
                    journal.equity(minute, float(acct.balance), float(acct.commission))
                    journal.set("last_target", target)
            if task and submitted_target is not None:
                actual = positions_snapshot(positions).get(symbol, (0, 0))[0]
                waiting = (actual != submitted_target
                           or any(o.status != "FINISHED" for o in orders.values()))
                pending_since = (pending_since or time.monotonic()) if waiting else None
                if (pending_since
                        and time.monotonic() - pending_since > config.execution_timeout_seconds):
                    guard.freeze("execution_timeout")
            if stop_requested() or (duration and time.monotonic() - start_time >= duration):
                status, reason = "stopped", "requested_stop"
                break
            api.wait_update(deadline=time.time() + 1)
    except sdk.BacktestFinished:
        if mode == "backtest" and journal.db.execute("SELECT count(*) FROM signals").fetchone()[0]:
            stats = getattr(account, "tqsdk_stat", {})
            if (stats and all(isinstance(stats.get(k), Real) and math.isfinite(stats[k])
                              for k in ("end_balance", "commission"))):
                status, reason = "backtest_finished", "historical_replay_completed"
                journal.set("sdk_statistics", {k: float(v) for k, v in stats.items()
                                               if isinstance(v, Real) and math.isfinite(v)})
            else:
                reason = "backtest_statistics_missing"
        else:
            reason = "historical_data_missing_or_incomplete"
    except Frozen as exc:
        status, reason = "frozen", str(exc)
    except KeyboardInterrupt:
        status, reason = "stopped", "keyboard_interrupt"
    except Exception:
        # 认证/权限/任务异常原文可能含凭证；只记录统一业务类别。
        status, reason = "failed", "sdk_or_auth_or_permission_error"
    finally:
        if guard:
            guard.enabled = False
        if hold_chart and api and status == "backtest_finished":
            if task:
                task.cancel()
            emit_progress(progress, "report_ready")
            while not stop_requested():
                try:
                    api.wait_update(deadline=time.time() + 0.5)
                except sdk.BacktestFinished:
                    continue
                except Exception:
                    journal.event("chart_view_ended")
                    break
        emit_progress(progress, "stopping")
        confirmed = task is None
        if api:
            if mode == "backtest":
                # 历史结束后不能再推进回放；取消任务，最终仅复制已提供的账户截面。
                if task:
                    task.cancel()
                confirmed = False if any(o.status != "FINISHED" for o in orders.values()) else True
            else:
                try:
                    confirmed = settle_stop(api, task, orders, journal.owned(),
                                            config.timeout_seconds)
                except Exception:
                    confirmed = False
            try:
                if guard:
                    for fill in trades_snapshot(trades):
                        guard.accept_fill(fill)
                    guard.check(positions_snapshot(positions), orders)
                acct = api.get_account()
                if math.isfinite(acct.balance) and math.isfinite(acct.commission):
                    snapshot_ns = int(serial.iloc[-1].datetime)
                    journal.equity(snapshot_ns, float(acct.balance), float(acct.commission))
                    result["final_equity"] = float(acct.balance)
                    result["day_commission"] = float(acct.commission)
                if status == "backtest_finished":
                    summary = journal.get("sdk_statistics")
                    result["final_equity"] = summary["end_balance"]
                    result["commission"] = summary["commission"]
                journal.set("final_positions", positions_snapshot(api.get_position()))
            except Exception:
                status, reason = "frozen", "final_reconciliation_incomplete"
            try:
                api.close()
            except Exception:
                status, reason = "frozen", "session_close_unconfirmed"
        if not confirmed and is_paper:
            status, reason = "frozen", "cancellation_unconfirmed"
        journal.set("cancellation_confirmed", confirmed)
        journal.set("status", status)
        journal.set("reason", reason)
        journal.event(reason)
        journal.export()
        journal.close()
        result.update(status=status, reason=reason)
        emit_progress(progress, "done")
    return dict(result, status=status, reason=reason)


def execute(mode, config, root, credentials, *, sdk=None, activate=False, resume=None,
            duration=0, stop_requested=lambda: False, progress=None, chart=False,
            hold_chart=False):
    if mode not in {"data-check", "backtest", "paper"}:
        raise ValueError("不支持的运行模式")
    if (activate or resume) and mode != "paper":
        raise ValueError("activate/resume 只用于快期模拟")
    if resume and (Path(resume).name != resume or resume in {".", ".."}):
        raise ValueError("恢复参数必须是本地 run_id")
    if sdk is None:
        emit_progress(progress, "sdk_loading")
        import tqsdk as sdk
        emit_progress(progress, "sdk_ready")
    root.mkdir(parents=True, exist_ok=True)
    arguments = dict(activate=activate, resume=resume, duration=duration,
                     stop_requested=stop_requested, progress=progress)
    if mode == "paper":
        with PaperLock(root):
            return _one(mode, config, root, credentials, sdk, chart=chart, **arguments)
    first = _one(mode, config, root, credentials, sdk, **arguments)
    if mode == "backtest" and first["status"] == "backtest_finished":
        if stop_requested():
            return dict(first, status="stopped", reason="comparison_cancelled")
        emit_progress(progress, "baseline_complete")
        second = _one(mode, config, root, credentials, sdk, fee_multiplier=2,
                      chart=chart, hold_chart=hold_chart, **arguments)
        comparison = {"baseline": first, "double_fee": second,
                      "method": "two_independent_TqSim_replays"}
        (root / first["run_id"] / "comparison.json").write_text(
            json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
        first["double_fee_run_id"] = second["run_id"]
        comparison_text = ("# 基准费用与双倍费用\n\n两次独立 SDK 历史回放。\n\n"
                           + f"基准：{first.get('final_equity')}；"
                           + f"总费用：{first.get('commission')}\n\n"
                           + f"双倍：{second.get('final_equity')}；"
                           + f"总费用：{second.get('commission')}\n\n"
                           + f"第二次状态：{second['status']}。浮动持仓按市值计入，未自动平仓。\n")
        (root / first["run_id"] / "comparison.md").write_text(comparison_text, encoding="utf-8")
        if second["status"] != "backtest_finished":
            first["status"] = "failed"
            first["reason"] = "double_fee_replay_failed"
    return first
