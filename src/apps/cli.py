"""qf —— 单一 CLI 入口(计划第 9 节)。

Phase 0 只建立命名空间,各子命令尚无实现。**先统一命名空间的理由**:不统一会
导致脚本、文档、ADR 里的命令彼此对不上,而这类不一致在文档里是静默的 ——
读者照抄一条不存在的命令,只会得到"命令不存在",不会得到"文档过期了"。

各子命令的落地 Phase 见 CLAUDE.md 的模块清单。
"""

from __future__ import annotations

import typer

from core import QfError

app = typer.Typer(
    name="qf",
    help="个人自用国内期货交易与回测系统",
    no_args_is_help=True,
    add_completion=False,
)

data_app = typer.Typer(name="data", help="数据采集、构建、质量与参考数据", no_args_is_help=True)
bt_app = typer.Typer(name="bt", help="回测、参数扫描与报告", no_args_is_help=True)
live_app = typer.Typer(name="live", help="实盘运行、对账与滑点分析", no_args_is_help=True)
rec_app = typer.Typer(name="rec", help="行情录制器", no_args_is_help=True)

app.add_typer(data_app)
app.add_typer(bt_app)
app.add_typer(live_app)
app.add_typer(rec_app)

#: 子命令 -> 落地 Phase。占位实现据此给出明确提示,而非含混的 NotImplementedError。
_PLANNED: dict[str, str] = {
    "data ingest": "Phase 3",
    "data build": "Phase 3",
    "data quality": "Phase 3",
    "data show": "Phase 3",
    "data gaps": "Phase 4",
    "data cont": "Phase 4",
    "data params": "Phase 4",
    "bt run": "Phase 5b",
    "bt sweep": "Phase 8",
    "bt report": "Phase 5b",
    "live run": "Phase 6",
    "live status": "Phase 6",
    "live flatten": "Phase 6",
    "live recon": "Phase 6",
    "live slippage": "Phase 7",
    "rec start": "Phase 2",
    "rec status": "Phase 2",
}


def _todo(command: str) -> None:
    """尚未实现的子命令的统一出口。"""
    phase = _PLANNED[command]
    typer.secho(f"qf {command} 尚未实现,计划于 {phase} 落地。", fg=typer.colors.YELLOW)
    typer.echo("实施计划见 docs/IMPLEMENTATION_PLAN.md,模块职责见 CLAUDE.md。")
    raise typer.Exit(code=2)


@data_app.command("ingest")
def data_ingest() -> None:
    """采集原始数据至 Raw_Layer。"""
    _todo("data ingest")


@data_app.command("build")
def data_build() -> None:
    """由 Raw_Layer 整分区重建 Curated_Layer。"""
    _todo("data build")


@data_app.command("quality")
def data_quality() -> None:
    """执行数据质量检查并写入质量台账。"""
    _todo("data quality")


@data_app.command("gaps")
def data_gaps() -> None:
    """输出真实缺失汇总表 —— 用于判定哪些回测结论站在窟窿上。"""
    _todo("data gaps")


@data_app.command("cont")
def data_cont() -> None:
    """构造主力连续序列与换月映射。"""
    _todo("data cont")


@data_app.command("show")
def data_show() -> None:
    """查看指定合约的 Bar 序列。"""
    _todo("data show")


@data_app.command("params")
def data_params() -> None:
    """查询指定合约在指定参考日期生效的费率与保证金。"""
    _todo("data params")


@bt_app.command("run")
def bt_run() -> None:
    """执行一次回测。"""
    _todo("bt run")


@bt_app.command("sweep")
def bt_sweep() -> None:
    """参数扫描(多进程,按物理核心数)。"""
    _todo("bt sweep")


@bt_app.command("report")
def bt_report() -> None:
    """输出回测绩效报告。"""
    _todo("bt report")


@live_app.command("run")
def live_run() -> None:
    """启动实盘或模拟盘策略运行。"""
    _todo("live run")


@live_app.command("status")
def live_status() -> None:
    """查询 Live_Process 运行状态。"""
    _todo("live status")


@live_app.command("flatten")
def live_flatten() -> None:
    """平掉全部持仓。"""
    _todo("live flatten")


@live_app.command("recon")
def live_recon() -> None:
    """执行持仓对账。"""
    _todo("live recon")


@live_app.command("slippage")
def live_slippage() -> None:
    """对比建模与实际的成交价与手续费 —— 整个系统真正的验收测试。"""
    _todo("live slippage")


@rec_app.command("start")
def rec_start() -> None:
    """启动 headless 录制器。"""
    _todo("rec start")


@rec_app.command("status")
def rec_status() -> None:
    """查询录制器状态。"""
    _todo("rec status")


def main() -> None:
    """控制台入口。

    QfError 在此转为退出码而非堆栈 —— 异常类型已携带处置语义(R32.2),
    对 CLI 使用者而言堆栈是噪音。非 QfError 的异常照常抛出,那是 bug。
    """
    try:
        app()
    except QfError as exc:
        typer.secho(f"{type(exc).__name__}: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    main()
