"""只读实验结果；不创建SDK会话、不用当前行情修补历史。"""

import json
import re
import sqlite3
from pathlib import Path

from qf.research_config import decimal_value, public_values, validate_research_config
from qf.research_journal import risk_from_dict

RUN_ID = re.compile(r"\d{8}T\d{6}-[0-9a-f]{12}\Z")


def run_path(root, run_id):
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise ValueError("实验运行编号无效")
    path = Path(root).resolve() / run_id
    if not path.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError("实验位置无效")
    if not (path / "journal.sqlite3").is_file():
        raise ValueError("实验结果不存在")
    return path


def _read(root, run_id):
    path = run_path(root, run_id)
    try:
        with sqlite3.connect((path / "journal.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
            state = {k: json.loads(v) for k, v in db.execute("SELECT * FROM state")}
            if state.get("research_schema") != 1:
                raise ValueError("不支持的实验版本")
            config = validate_research_config(state["config"])
            if "risk_state" in state:
                risk_from_dict(state["risk_state"])
            fills = list(db.execute("SELECT * FROM fills ORDER BY time_ns,rowid"))
            equity = list(db.execute("SELECT * FROM equity ORDER BY time_ns"))
            span = db.execute(
                "SELECT min(time_ns),max(time_ns),count(*) FROM research_bars"
            ).fetchone()
    except (OSError, KeyError, TypeError, sqlite3.Error, ValueError):
        raise ValueError("实验文件缺失、版本不支持或记录不完整") from None
    return config, state, fills, equity, span


def read_run(root, run_id):
    config, state, _, _, span = _read(root, run_id)
    return dict(
        run_id=run_id,
        config=config.public(),
        status=state.get("status", "created"),
        reason=state.get("reason"),
        fee_multiplier=state.get("fee_multiplier", 1),
        risk=state.get("risk_state", {}),
        experiment_ref=state.get("experiment_ref"),
        cost_source=state.get("cost_source"),
        precision=config.precision,
        coverage=dict(
            first_ns=str(span[0]) if span[0] else None,
            last_ns=str(span[1]) if span[1] else None,
            bars=span[2],
        ),
    )


def summarize_run(root, run_id):
    config, state, fills, equity, _ = _read(root, run_id)
    initial = decimal_value(state.get("initial_equity", config.initial_balance))
    balances = [initial, *[decimal_value(r[1]) for r in equity]]
    final = decimal_value(state.get("sdk_statistics", {}).get("end_balance", balances[-1]))
    balances.append(final)
    fee_raw = state.get(
        "total_commission",
        state.get("sdk_statistics", {}).get("commission", equity[-1][2] if equity else None),
    )
    fee = decimal_value(fee_raw) if fee_raw is not None else None
    peak, max_amount, max_pct = initial, decimal_value(0), decimal_value(0)
    for value in balances:
        peak = max(peak, value)
        max_amount = max(max_amount, peak - value)
        if peak > 0:
            max_pct = max(max_pct, (peak - value) / peak * 100)
    net, position, closed = final - initial, 0, 0
    for fill in fills:
        previous = position
        position += fill[5] if fill[3] == "BUY" else -fill[5]
        if previous and not position:
            closed += 1
    measured = bool(equity) or bool(state.get("sdk_statistics"))
    return public_values(
        dict(
            **read_run(root, run_id),
            gross_pnl=net + fee if fee is not None and measured else None,
            net_pnl=net if measured else None,
            commission=fee,
            max_drawdown_amount=max_amount.normalize() if equity else None,
            max_drawdown_pct=max_pct.normalize() if equity else None,
            fill_count=len(fills),
            closed_trade_count=closed,
            open_position=position,
            final_equity=final if measured else None,
        )
    )


def compare_runs(root, run_ids):
    if not isinstance(run_ids, list) or len(run_ids) != 2 or run_ids[0] == run_ids[1]:
        raise ValueError("请选择两个不同的实验运行")
    items = [summarize_run(root, identity) for identity in run_ids]
    left, right = [i["config"] for i in items]
    differences = {k: [left[k], right[k]] for k in left if left[k] != right[k]}
    comparable = ("symbol", "bar_seconds", "start", "end", "initial_balance", "precision")
    warnings = [key for key in comparable if key in differences]
    if items[0]["fee_multiplier"] != items[1]["fee_multiplier"]:
        warnings.append("fee_multiplier（独立成本压力回放）")
    if items[0]["status"] != "backtest_finished" or items[1]["status"] != "backtest_finished":
        warnings.append("包含未完成或非历史回测结果")
    return dict(items=items, config_differences=differences, comparability_warnings=warnings)


def run_details(root, run_id):
    read_run(root, run_id)
    path = run_path(root, run_id)
    with sqlite3.connect((path / "journal.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
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
                    row,
                    strict=True,
                )
            )
            for row in db.execute("SELECT * FROM fills ORDER BY time_ns,rowid")
        ]
        events = [
            dict(time_ns=str(r[0]), kind=r[1], payload=json.loads(r[2]), risk=json.loads(r[3]))
            for r in db.execute("SELECT time_ns,kind,payload,risk FROM risk_events ORDER BY rowid")
        ]
    for fill in fills:
        fill["time_ns"] = str(fill["time_ns"])
    return dict(fills=fills, risk_events=events)
