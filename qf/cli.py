import argparse
import contextlib
import getpass
import json
import logging
import os
import signal
import sys
from pathlib import Path

from qf.config import load_config
from qf.runtime import execute


def console_progress(stream):
    messages = {
        "credentials_received": "凭证输入完成，准备启动（不会显示账号和密码）。",
        "sdk_loading": "正在加载天勤 SDK……",
        "sdk_ready": "天勤 SDK 已加载。",
        "record_creating": "正在创建本机实验记录……",
        "connecting": "正在连接天勤账户并完成认证，请稍候……",
        "waiting_data": "账户已连接，正在等待主力合约、行情和分钟数据……",
        "data_ready": "行情、分钟线和账户数据已就绪。",
        "backtesting": "正在进行历史回测……",
        "stopping": "正在收尾并核对状态，请稍候……",
        "done": "本次运行已结束，正在输出结果。",
    }

    def notify(stage, **fields):
        if stage in {"observing", "paper_active", "heartbeat"}:
            elapsed = fields.get("elapsed", 0)
            duration = fields.get("duration", 0)
            if (type(elapsed) is not int or type(duration) is not int
                    or elapsed < 0 or duration < 0):
                return
            total = f" / {duration} 秒" if duration else " 秒（持续运行）"
            prefix = {"observing": "模拟账户只读观察已开始，不发送委托",
                      "paper_active": "模拟交易已启用", "heartbeat": "程序仍在运行"}[stage]
            message = f"{prefix}；已运行 {elapsed}{total}。"
        else:
            message = messages.get(stage)
        if message:
            print(message, file=stream, flush=True)

    return notify


def main(argv=None):
    parser = argparse.ArgumentParser(description="天勤研究与快期模拟；不提供实盘入口")
    parser.add_argument("mode", choices=["data-check", "backtest", "paper"])
    parser.add_argument("--config", type=Path, default=Path("experiments/rb-demo.toml"))
    parser.add_argument("--activate", action="store_true", help="显式允许快期模拟委托")
    parser.add_argument("--resume", help="恢复同一 run_id，先对账")
    parser.add_argument("--duration", type=int, default=0, help="模拟秒数，0 表示持续运行")
    args = parser.parse_args(argv)
    if (args.duration < 0
            or ((args.activate or args.resume or args.duration) and args.mode != "paper")):
        parser.error("activate/resume/duration 仅适用于 paper，duration 不可负数")
    root = Path(__file__).resolve().parent.parent
    try:
        config = load_config(args.config)
    except Exception:
        print("配置读取失败；请使用公开实验 TOML，禁止把凭证写入配置。")
        return 2
    user, password = os.environ.get("TQ_USER"), os.environ.get("TQ_PASSWORD")
    if not user or not password:
        if not sys.stdin.isatty():
            print("需要交互终端安全输入，或同时提供本进程 TQ_USER / TQ_PASSWORD。")
            return 2
        user = getpass.getpass("快期账号（隐藏输入）：")
        password = getpass.getpass("快期密码（隐藏输入）：")
    if not user or not password:
        print("未提供完整快期凭证。")
        return 2
    stop = False

    def request_stop(_signum, _frame):
        nonlocal stop
        stop = True

    previous = signal.signal(signal.SIGINT, request_stop)
    logging_level = logging.root.manager.disable
    progress = console_progress(sys.stdout)
    try:
        progress("credentials_received")
        # SDK通知、认证异常、第三方输出一律不进入终端与实验文件。
        logging.disable(logging.CRITICAL)
        with open(os.devnull, "w", encoding="utf-8") as sink:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                result = execute(args.mode, config, root / "results", (user, password),
                                 activate=args.activate, resume=args.resume, duration=args.duration,
                                 stop_requested=lambda: stop, progress=progress)
    except Exception:
        result = {"status": "failed", "reason": "startup_or_local_record_error"}
    finally:
        logging.disable(logging_level)
        signal.signal(signal.SIGINT, previous)
        user = password = None
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if "run_id" in result:
        print(f"实验目录：{root / 'results' / result['run_id']}")
    return 0 if result["status"] in {"data_ready", "backtest_finished", "stopped"} else 1
