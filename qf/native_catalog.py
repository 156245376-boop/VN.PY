"""TqSdk 原生能力与随包资源的离线目录；从不创建账户或执行示例。"""

from __future__ import annotations

import base64
import contextlib
import csv
import hashlib
import importlib
import importlib.metadata
import inspect
import io
from pathlib import Path, PurePosixPath
from types import ModuleType

_DOC = "https://doc.shinnytech.com/tqsdk/latest/"
_VERIFY_ACCOUNT = "免费权限与数据范围待实际账户核验；安装成功不代表账户可用。"
_LATER = "已安装，按需接入"
_SKILL_ROOT = Path.home() / ".codex/skills/tqsdk-trading-and-data"
_SKILL_FILES = (
    "SKILL.md", "agents/openai.yaml", "scripts/check_environment.py",
    "references/account-type-matrix.md", "references/accounts-and-trading.md",
    "references/environment-setup.md", "references/error-faq.md", "references/example-map.md",
    "references/market-data.md", "references/object-fields.md",
    "references/order-functions-and-position-tools.md", "references/scenario-and-margin.md",
    "references/simulation-and-backtest.md", "references/wait-update-and-update-loop.md",
)

# 每项为用户说明及实际可导入符号；不实例化类、不请求数据或账户。
_CAPABILITIES = (
    ("market_data", "行情、K线、Tick与合约查询",
     "get_quote / get_kline_serial / get_tick_serial / query_quotes；主流程已接入观察。",
     "reference/tqsdk.api.html", "已接入主流程：观察与分钟数据", _VERIFY_ACCOUNT,
     (("tqsdk", "TqApi.get_quote", "TqApi.get_kline_serial", "TqApi.get_tick_serial",
       "TqApi.query_quotes"),)),
    ("indicators", "技术指标与序列函数",
     "ta 技术指标和 tafunc 序列计算；可对现有 pandas 数据使用。",
     "reference/tqsdk.ta.html", _LATER, _VERIFY_ACCOUNT,
     (("tqsdk.ta", "MA"), ("tqsdk.tafunc", "ma", "ref"))),
    ("backtest", "本地模拟与历史回测",
     "TqSim / TqBacktest；主流程采用固定样本及独立双费回放。",
     "usage/backtest.html", "已接入主流程：固定样本回测", _VERIFY_ACCOUNT,
     (("tqsdk", "TqSim", "TqBacktest"),)),
    ("quick_simulation", "快期模拟账户",
     "TqKq；主流程单模拟账户，默认观察，模拟委托须显式启用。",
     "reference/tqsdk.tqkq.html", "已接入主流程：单模拟账户", _VERIFY_ACCOUNT,
     (("tqsdk", "TqKq"),)),
    ("target_position", "目标持仓管理",
     "TargetPosTask 自动调整目标持仓；同一账户合约须明确唯一控制方式。",
     "usage/targetpostask.html", "已接入主流程：目标持仓", _VERIFY_ACCOUNT,
     (("tqsdk", "TargetPosTask"),)),
    ("scheduler", "计划持仓调度",
     "TargetPosScheduler 按时间表分步调整目标持仓。",
     "advanced/scheduler.html", _LATER, _VERIFY_ACCOUNT,
     (("tqsdk", "TargetPosScheduler"),)),
    ("algorithm", "Twap与TWAP/VWAP时间表",
     "algorithm.Twap / twap_table / vwap_table；Twap 不支持回测，时间表配合调度器。",
     "reference/tqsdk.algorithm.html", _LATER, _VERIFY_ACCOUNT,
     (("tqsdk.algorithm", "Twap", "twap_table", "vwap_table"),)),
    ("downloader", "历史数据下载",
     "DataDownloader 将行情历史数据写入 CSV；当前目录检查不会下载数据。",
     "reference/tqsdk.tools.download.html", _LATER,
     "DataDownloader 需要专业版 tq_dl 权限；数据范围待实际账户核验。",
     (("tqsdk.tools", "DataDownloader"),)),
    ("scenario", "期货场景试算",
     "TqScenario 仅支持期货单账户快照，试算保证金与风险度，不代表可成交。",
     "reference/tqsdk.scenario.html", _LATER, _VERIFY_ACCOUNT,
     (("tqsdk", "TqScenario"),)),
    ("reporting", "原生报告与图形",
     "TqReport 及 draw_text / draw_line / draw_box / draw_report；随包 web 图形资源。",
     "reference/tqsdk.api.html#tqsdk.TqApi.draw_report",
     "已接入主流程：原生图形与回测报告；自定义绘图按需接入", _VERIFY_ACCOUNT,
     (("tqsdk.report", "TqReport"),
      ("tqsdk", "TqApi.draw_text", "TqApi.draw_line", "TqApi.draw_box", "TqApi.draw_report"))),
    ("notifications", "服务器通知读取",
     "TqNotify 在同步代码中接收服务器通知，不是短信或邮件服务。",
     "reference/tqsdk.lib.html#tqsdk.TqNotify", _LATER, _VERIFY_ACCOUNT,
     (("tqsdk", "TqNotify"),)),
    ("channels", "异步通道与更新通知",
     "TqChan / register_update_notify，配合 wait_update 驱动异步数据更新。",
     "reference/tqsdk.channel.html", _LATER, _VERIFY_ACCOUNT,
     (("tqsdk", "TqChan", "TqApi.register_update_notify", "TqApi.wait_update"),)),
    ("trading_status", "合约交易状态",
     "get_trading_status 获取合约交易状态；不支持回测。",
     "reference/tqsdk.api.html#tqsdk.TqApi.get_trading_status", _LATER,
     "交易状态需要专业版 tq_trading_status 权限；待实际账户核验。",
     (("tqsdk", "TqApi.get_trading_status"),)),
    ("extended_data", "合约扩展、期权与EDB",
     "合约详情、历史主连、期权链与Greeks、结算、排名及 EDB 经济数据库查询。",
     "reference/tqsdk.api.html", _LATER,
     "EDB及部分扩展/期权接口需要专业版；具体接口、数据范围待实际账户核验。",
     (("tqsdk", "TqApi.query_symbol_info", "TqApi.query_his_cont_quotes",
       "TqApi.query_options", "TqApi.query_option_greeks", "TqApi.query_edb_data",
       "TqApi.query_symbol_settlement", "TqApi.query_symbol_ranking"),)),
    ("risk_rules", "四类本地风控规则",
     "risk_rule：交易日开仓次数、单合约开仓手数、累计开仓手数、每秒订单操作次数。",
     "reference/tqsdk.risk_rule.html", _LATER,
     "本地风控 add_risk_rule 需要专业版 tq_lc_rk 权限；待实际账户核验。",
     (("tqsdk.risk_rule", "TqRuleOpenCountsLimit", "TqRuleOpenVolumesLimit",
       "TqRuleAccOpenVolumesLimit", "TqRuleOrderRateLimit"),)),
    ("multi_account", "多账户工具",
     "TqMultiAccount；账户相关操作需显式指定 account，主流程暂不提供多账户运行。",
     "reference/tqsdk.multiaccount.html", _LATER,
     "按所用账户、数据与接口分别核验权限；不能把多账户工具笼统视为付费功能。",
     (("tqsdk", "TqMultiAccount"),)),
    ("direct_accounts", "企业直连与资管账户类",
     "TqCtp / TqRohon / TqJees / TqYida / TqO32 / TqIS / TqXuntou 等接入类。",
     "enterprise.html", _LATER,
     "直连模式需要企业授权及对应柜台配置；实盘登录和交易需另行明确授权。",
     (("tqsdk", "TqAccount", "TqZq", "TqCtp", "TqRohon", "TqJees", "TqYida",
       "TqO32", "TqIS", "TqXuntou", "TqTradingUnit"),)),
    ("stock_accounts", "股票模拟账户类",
     "TqSimStock / TqKqStock；股票不使用期货 offset 或 TargetPosTask。",
     "reference/tqsdk.sim.html", _LATER,
     "股票行情、回测与模拟权限须按实际账户核验，不能按期货免费范围推定。",
     (("tqsdk", "TqSimStock", "TqKqStock"),)),
    ("examples", "官方示例源码",
     "随包示例仅只读参考；含过期合约、占位凭证及旧写法，使用前须逐项适配。",
     "demo/index.html", "已接入工作台：只读浏览", _VERIFY_ACCOUNT, ()),
)


def _import_module(name: str, issues: list[str], modules: dict) -> ModuleType | None:
    if name not in modules:
        try:
            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                modules[name] = importlib.import_module(name)
        except Exception as exc:
            modules[name] = None
            issues.append(f"无法导入 {name}（{type(exc).__name__}）")
    return modules[name]


def _skill_status(issues: list[str]) -> dict:
    files, missing = [], []
    for name in _SKILL_FILES:
        try:
            raw = (_SKILL_ROOT / name).read_bytes()
            if not raw:
                raise OSError("empty skill file")
            files.append(name)
        except OSError:
            missing.append(name)
    if missing:
        issues.append("官方 TqSdk 技能缺失或不可读：" + "、".join(missing))
    return {"installed": not missing, "root": str(_SKILL_ROOT),
            "files": files, "missing": missing}


def _resources(distribution, sdk_root: Path, issues: list[str]) -> tuple[list[str], int, int]:
    """核验 wheel RECORD 中 demo/web 的所有文件，同时发现未记录的额外资源。"""
    recorded: dict[str, tuple[str, str]] = {}
    # Distribution.files 会过滤已缺失的文件；必须读原始 RECORD 才能发现缺失。
    for row in csv.reader(io.StringIO(distribution.read_text("RECORD") or "")):
        if len(row) != 3:
            issues.append("wheel RECORD 存在无效记录")
            continue
        relative = PurePosixPath(row[0])
        if relative.parts[:2] in (("tqsdk", "demo"), ("tqsdk", "web")):
            recorded[str(relative.relative_to("tqsdk"))] = (row[1], row[2])
    for directory in ("demo", "web"):
        if not any(name.startswith(directory + "/") for name in recorded):
            issues.append(f"wheel RECORD 缺少 {directory} 资源清单，不能验证完整性")
    checked, examples, web_assets = 0, [], 0
    for name, (recorded_hash, recorded_size) in sorted(recorded.items()):
        try:
            path = Path(distribution.locate_file("tqsdk/" + name)).resolve()
            if not path.is_relative_to(sdk_root / name.split("/")[0]):
                raise OSError("resource outside SDK directory")
            raw = path.read_bytes()
            if not recorded_hash:
                issues.append(f"wheel RECORD 缺少资源哈希：{name}")
                continue
            algorithm, expected = recorded_hash.split("=", 1)
            digest = hashlib.new(algorithm, raw).digest()
            actual = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
            if actual != expected or (recorded_size and len(raw) != int(recorded_size)):
                issues.append(f"wheel RECORD 资源校验失败：{name}")
                continue
            checked += 1
            if name.startswith("demo/") and name.endswith(".py") and path.name != "__init__.py":
                examples.append(name.removeprefix("demo/"))
            if name.startswith("web/"):
                web_assets += 1
        except (OSError, ValueError) as exc:
            issues.append(f"资源缺失或不可读：{name}（{type(exc).__name__}）")
    for directory in ("demo", "web"):
        try:
            for path in (sdk_root / directory).rglob("*"):
                relative = path.relative_to(sdk_root)
                if path.is_file() and "__pycache__" not in relative.parts:
                    if relative.as_posix() not in recorded:
                        issues.append(f"资源未在 wheel RECORD 中记录：{relative.as_posix()}")
        except OSError:
            issues.append(f"无法读取资源目录：{directory}")
    return examples, web_assets, checked


def inspect_installation() -> dict:
    """返回可 JSON 序列化的本机安装状态；不登录、不创建 TqApi、不执行示例。"""
    issues: list[str] = []
    modules: dict[str, ModuleType | None] = {}
    result = {
        "ready": False, "issues": issues, "sdk_version": "", "sdk_root": "",
        "ta_functions": 0, "tafunc_functions": 0, "web_assets": 0, "examples": [],
        "capabilities": [], "skill": _skill_status(issues),
        "example_dependencies": {"sklearn": {"installed": False, "version": ""}},
        "resource_integrity": {"method": "wheel RECORD hashes (demo + web)", "checked_files": 0},
    }
    sdk = _import_module("tqsdk", issues, modules)
    if sdk is not None:
        sdk_root = Path(sdk.__file__).resolve().parent
        result["sdk_root"] = str(sdk_root)
        try:
            distribution = importlib.metadata.distribution("tqsdk")
            result["sdk_version"] = distribution.version
            examples, web_assets, checked = _resources(distribution, sdk_root, issues)
            result["examples"], result["web_assets"] = examples, web_assets
            result["resource_integrity"]["checked_files"] = checked
        except (importlib.metadata.PackageNotFoundError, OSError, ValueError) as exc:
            issues.append(f"无法读取 TqSdk wheel RECORD（{type(exc).__name__}）")
    for name in ("ta", "tafunc"):
        module = _import_module("tqsdk." + name, issues, modules)
        if module is not None:
            result[name + "_functions"] = sum(
                not key.startswith("_") and inspect.isfunction(value)
                and value.__module__ == module.__name__ for key, value in vars(module).items()
            )
    sklearn = _import_module("sklearn", issues, modules)
    if sklearn is not None:
        try:
            result["example_dependencies"]["sklearn"] = {
                "installed": True, "version": importlib.metadata.version("scikit-learn"),
            }
        except importlib.metadata.PackageNotFoundError:
            issues.append("scikit-learn 已导入但版本元数据缺失")
    else:
        issues.append("官方机器学习示例额外依赖 scikit-learn 缺失或不可导入")
    for key, title, description, doc, integration, permission, groups in _CAPABILITIES:
        installed = sdk is not None
        for module_name, *symbols in groups:
            module = _import_module(module_name, issues, modules)
            for symbol in symbols:
                value = module
                for attribute in symbol.split("."):
                    value = getattr(value, attribute, None)
                if value is None:
                    installed = False
                    issues.append(f"缺少原生接口：{module_name}.{symbol}")
        if key == "examples":
            installed = bool(result["examples"]) and not any("demo" in issue for issue in issues)
        elif key == "reporting":
            installed = installed and bool(result["web_assets"])
            installed = installed and not any("web/" in issue for issue in issues)
        result["capabilities"].append({
            "key": key, "title": title, "description": description, "doc": _DOC + doc,
            "installed": installed, "integration": integration, "permission": permission,
        })
    result["ready"] = not issues
    return result


def read_example(relative_name: str) -> str:
    """只读取清单中通过 RECORD 校验的示例源码；拒绝路径变形和目录穿越。"""
    if not isinstance(relative_name, str) or not relative_name or "\\" in relative_name:
        raise ValueError("请选择清单中的示例相对路径")
    relative = PurePosixPath(relative_name)
    if relative.is_absolute() or ":" in relative_name or any(
        part in ("", ".", "..") for part in relative_name.split("/")
    ):
        raise ValueError("示例路径不在允许范围内")
    inventory = inspect_installation()
    if relative_name not in inventory["examples"]:
        raise ValueError("示例未在已验证清单中")
    demo_root = (Path(inventory["sdk_root"]) / "demo").resolve()
    path = (demo_root / relative_name).resolve()
    if not path.is_relative_to(demo_root):
        raise ValueError("示例路径超出 SDK demo 目录")
    return path.read_text(encoding="utf-8-sig")
