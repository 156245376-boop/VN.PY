"""只读实验结果；不创建SDK会话、不用当前行情修补历史。"""

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from qf.research_account import account_schema, costs_reconciled, fill_fee_total
from qf.research_config import decimal_value, public_values, validate_research_config
from qf.research_journal import integrity_manifest, risk_from_dict

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
        with closing(
            sqlite3.connect((path / "journal.sqlite3").as_uri() + "?mode=ro", uri=True)
        ) as db:
            db.execute('BEGIN')
            state = {k: json.loads(v) for k, v in db.execute("SELECT * FROM state")}
            if state.get("research_schema") != 1:
                raise ValueError("不支持的实验版本")
            config = validate_research_config(state["config"])
            risk_from_dict(state['risk_state'])
            if state.get('research_integrity') != integrity_manifest(db):
                raise ValueError('实验完整性校验失败')
            fills = list(db.execute("SELECT * FROM fills ORDER BY time_ns,rowid"))
            linked = []
            for kind, payload, risk in db.execute('SELECT kind,payload,risk FROM risk_events'):
                risk_from_dict(json.loads(risk))
                keys = json.loads(payload).get('fill_keys', [])
                if kind == 'fill':
                    linked.extend(keys)
            if sorted(linked) != sorted(row[0] for row in fills):
                raise ValueError('成交风险关联不完整')
            equity = list(db.execute("SELECT * FROM equity ORDER BY time_ns"))
            actual = state.get("final_positions")
            if actual is not None and (
                not isinstance(actual, dict)
                or any(
                    not isinstance(pair, list)
                    or len(pair) != 2
                    or any(type(value) is not int or value < 0 for value in pair)
                    for pair in actual.values()
                )
            ):
                raise ValueError("持仓记录无效")
            for fill in fills:
                if (
                    fill[2] != config.symbol
                    or fill[3] not in ("BUY", "SELL")
                    or fill[4] not in ("OPEN", "CLOSE", "CLOSETODAY")
                    or type(fill[5]) is not int
                    or fill[5] <= 0
                    or decimal_value(fill[6]) <= 0
                    or fill[7] <= 0
                ):
                    raise ValueError("成交记录无效")
            for row in equity:
                decimal_value(row[1])
                if decimal_value(row[2]) < 0:
                    raise ValueError("费用记录无效")
            span = db.execute(
                "SELECT min(time_ns),max(time_ns),count(*) FROM research_bars"
            ).fetchone()
            if db.execute('SELECT 1 FROM research_bars WHERE symbol!=? OR bar_seconds!=?',
                          (config.symbol, config.bar_seconds)).fetchone():
                raise ValueError('柱品种或周期不匹配')
    except (OSError, KeyError, TypeError, sqlite3.Error, ValueError):
        raise ValueError("实验文件缺失、版本不支持或记录不完整") from None
    return config, state, fills, equity, span


def read_run(root, run_id):
    from qf.continuous_results import read_continuous_run, schema_at
    schema = schema_at(run_path(root, run_id))
    if schema == 3:
        from qf.local_results import read_local_run
        return read_local_run(root, run_id)
    if schema == 2:
        return read_continuous_run(root, run_id)
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
        coverage_check=state.get('coverage_check'),
        precision=config.precision,
        coverage=dict(
            first_ns=str(span[0]) if span[0] else None,
            last_ns=str(span[1]) if span[1] else None,
            bars=span[2],
        ),
    )


def summarize_run(root, run_id):
    from qf.continuous_results import schema_at, summarize_continuous_run
    schema = schema_at(run_path(root, run_id))
    if schema == 3:
        from qf.local_results import summarize_local_run
        return summarize_local_run(root, run_id)
    if schema == 2:
        return summarize_continuous_run(root, run_id)
    config, state, fills, equity, _ = _read(root, run_id)
    initial = decimal_value(state.get("initial_equity", config.initial_balance))
    balances = [initial, *[decimal_value(r[1]) for r in equity]]
    final = decimal_value(state.get("sdk_statistics", {}).get("end_balance", balances[-1]))
    balances.append(final)
    sdk_raw = state.get("sdk_statistics", {}).get("commission")
    legacy_raw = state.get(
        "total_commission",
        sdk_raw if sdk_raw is not None else equity[-1][2] if equity else None,
    )
    with closing(sqlite3.connect((run_path(root, run_id)/'journal.sqlite3').as_uri()
                                 + '?mode=ro', uri=True)) as db:
        if account_schema(db):
            fee = fill_fee_total(db)
            fee_raw = str(fee)
        else:
            fee_raw = legacy_raw
            fee = decimal_value(fee_raw) if fee_raw is not None else None
    cost_ok = (costs_reconciled(sdk_raw, fee_raw)
               if sdk_raw is not None and fee_raw is not None else None)
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
    actual = state.get("final_positions")
    actual_net = (
        actual.get(config.symbol, [0, 0])[0] - actual.get(config.symbol, [0, 0])[1]
        if isinstance(actual, dict)
        else None
    )
    return public_values(
        dict(
            **read_run(root, run_id),
            gross_pnl=net + fee if fee is not None and measured else None,
            net_pnl=net if measured else None,
            commission=fee,
            cost_reconciled=cost_ok,
            cost_difference=(abs(decimal_value(sdk_raw)-decimal_value(fee_raw))
                             if sdk_raw is not None and fee_raw is not None else None),
            max_drawdown_amount=max_amount.normalize() if equity else None,
            max_drawdown_pct=max_pct.normalize() if equity else None,
            fill_count=len(fills),
            closed_trade_count=closed,
            open_position=actual_net
            if actual_net is not None
            else (position if fills and state.get("mode") == "backtest" else None),
            account_positions=actual,
            position_source="account" if actual_net is not None else "local_fills_unconfirmed",
            final_equity=final if measured else None,
        )
    )


def compare_runs(root, run_ids):
    if not isinstance(run_ids, list) or len(run_ids) != 2 or run_ids[0] == run_ids[1]:
        raise ValueError("请选择两个不同的实验运行")
    items = [summarize_run(root, identity) for identity in run_ids]
    left, right = [i["config"] for i in items]
    differences = {k: [left.get(k), right.get(k)] for k in left.keys() | right.keys()
                   if left.get(k) != right.get(k)}
    comparable = ("symbol", "bar_seconds", "start", "end", "initial_balance", "precision")
    warnings = [key for key in comparable if key in differences]
    warnings.extend(key for key in ('contract_mode', 'signal_adjustment', 'roll_policy')
                    if key in differences)
    if (left['strategy_version'] != right['strategy_version']
            or left['risk'].get('stop_method') != right['risk'].get('stop_method')):
        warnings.append('策略版本或止损规则不同')
    if items[0]["fee_multiplier"] != items[1]["fee_multiplier"]:
        warnings.append("fee_multiplier（独立成本压力回放）")
    if items[0]["status"] != "backtest_finished" or items[1]["status"] != "backtest_finished":
        warnings.append("包含未完成或非历史回测结果")
    return dict(items=items, config_differences=differences, comparability_warnings=warnings)


def run_details(root, run_id):
    from qf.continuous_results import read_continuous_run, schema_at
    schema = schema_at(run_path(root, run_id))
    if schema == 3:
        from qf.local_results import local_run_details
        run_path(root, run_id)
        return local_run_details(root, run_id)
    if schema == 2:
        return read_continuous_run(root, run_id, details=True)
    read_run(root, run_id)
    path = run_path(root, run_id)
    with closing(sqlite3.connect((path / "journal.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
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
        from qf.research_account import read_account
        from qf.research_protection import protection_window
        span = db.execute('SELECT min(time_ns),max(time_ns) FROM research_bars').fetchone()
        account = read_account(db, at_ns=span[1])
        protection = protection_window(
            db, first_ns=span[0] or 0, as_of_ns=span[1] or 0,
            series='actual', symbol=read_run(root, run_id)['config']['symbol'])
    for fill in fills:
        fill["time_ns"] = str(fill["time_ns"])
    return dict(fills=fills, risk_events=events, account=account, protection=protection)
