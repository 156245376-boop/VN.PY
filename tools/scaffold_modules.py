"""生成各模块的 README 存根与空 __init__.py(Phase 0 一次性使用)。

README 小节顺序固定 —— 固定的顺序使模型知道去哪一段找,不必通读(R26.2)。
Phase 0 阶段各模块尚无实现,故「不变式 / 否决过的方案 / 已知局限」三节按需求
留待对应 Phase 填写:这些内容事后补是补不出来的,但提前编造更糟。

本脚本幂等,重复执行不覆盖已存在的 README 与 __init__.py。core 模块已手写,跳过。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (模块, 层级, 职责, 禁止 import 及理由, 落地 Phase)
MODULES: list[tuple[str, str, str, list[tuple[str, str]], str]] = [
    (
        "config",
        "L1",
        "加载、校验、保存用户选择类配置,并使凭证不进入版本库(R22)。",
        [
            ("市场事实类取值", "费率、保证金、时段属于 meta/ 的 SCD-2 表。放进配置意味着回测 2019 年用今天的保证金(R22.3)"),
            ("策略、委托、数据库", "配置是被读取方,不得反向依赖使用方"),
        ],
        "Phase 0(骨架)/ Phase 2(完整)",
    ),
    (
        "obs",
        "L1",
        "结构化日志、State_Snapshot 写入、告警推送(R20/R21)。",
        [
            ("策略、委托、数据库", "可观测性是横切关注点。反向依赖会使日志模块参与业务,进而无法在任意位置调用"),
        ],
        "Phase 2",
    ),
    (
        "meta",
        "L2",
        "某日期下的市场参考事实:合约表、交易日历与时段、费率保证金 SCD-2、合约代码规范化(R3/R27/R30)。",
        [
            ("vnpy", "参考数据须能被自研引擎与 research notebook 独立使用"),
            ("策略、委托、回测、实盘状态", "meta 是被查询方,查询走显式函数调用而非事件(R24.7)"),
        ],
        "Phase 1(calendar/symbols)/ Phase 4(contracts/params)",
    ),
    (
        "data",
        "L3",
        "采集、存储、聚合、质量校验、主力连续序列构造(R4–R10/R25/R28)。",
        [
            ("vnpy —— 唯一例外是 `data/vnpy_db.py`", "该文件是供 vnpy 回测引擎读 Bar 的垫片(A5),隔离在单个叶子文件内使存储层可被自研引擎复用"),
            ("策略、委托、风控、实盘", "数据层不知道数据被谁使用"),
        ],
        "Phase 3(存储/聚合/质量)/ Phase 4(回填/连续)",
    ),
    (
        "indicators",
        "L4",
        "纯 numpy 技术指标,每个提供标量式与序列式双形态(R33.7)。",
        [
            ("vnpy", "复用 vnpy 的 ArrayManager 会把 vnpy 拖进 strategy 的 import 闭包(ADR-0010)"),
            ("行情来源、磁盘、pandas", "指标是数组上的自由函数,不持有状态也不知道数据从哪来"),
        ],
        "Phase 5b",
    ),
    (
        "strategy",
        "L4",
        "策略纯逻辑类与 Strategy_Context 协议。以目标持仓表达交易意图(R11)。",
        [
            ("任何交易框架(vnpy 及其插件)", "直接继承框架基类会永久锁死 vnpy,换引擎需重写每个策略(ADR-0004)。由 `.importlinter` 强制(R24.13)"),
            ("交易所身份、平今平昨、费率、保证金、委托号、券商、数据库、网络", "策略说「我要净持 −2 手」,不说「用 CLOSE_TODAY 买 2 手」—— 后者要求策略知道上期所规则与今昨仓拆分,任何自研引擎都无法复现(ADR-0003)"),
            ("pandas / polars / duckdb", "策略须可在向量化引擎内逐根调用,DataFrame 开销与之不相容"),
        ],
        "Phase 5b",
    ),
    (
        "costs",
        "L5",
        "手续费、滑点、保证金占用计算。回测与实盘调用同一批函数(R29)。",
        [
            ("引擎身份", "本模块不知道调用方是回测还是实盘 —— 这个同一性正是防止回测实盘分裂的机制(ADR-0005)"),
            ("vnpy", "vnpy 回测只支持 turnover×rate,收不到按手固定费与平今差异(A3),故费用计算必须在框架之外"),
        ],
        "Phase 5b",
    ),
    (
        "execution",
        "L6",
        "目标持仓差额 → 委托意图:开平方向解析、平今平昨决策、限价定价与涨跌停钳制(R17)。",
        [
            ("vnpy、网关", "本模块产出 OrderIntent,由 engines/ 或 gateway/ 翻译成框架词汇"),
            ("策略类", "执行层只读目标持仓数值,不认识策略对象"),
            ("磁盘", "开平决策须为纯函数以便表驱动测试"),
        ],
        "Phase 6",
    ),
    (
        "risk",
        "L6",
        "纯否决函数 `screen(intents, state, limits) -> Verdict`(R19)。",
        [
            ("execution", "风控不得依赖执行细节,否则无法在下单前独立校验(R19.2)"),
            ("vnpy、网关、磁盘", "风控须可在测试中以构造的账户状态直接调用"),
        ],
        "Phase 6",
    ),
    (
        "engines",
        "L7",
        "Strategy 到具体引擎的适配器,以及回测装配(R12/R13)。",
        [],
        "Phase 5a(选型)/ Phase 5b(桥)",
    ),
    (
        "gateway",
        "L7",
        "CTP 连接与重连、流控令牌桶、穿透式监管前置检查、每日费率快照(R1/R2/R30)。",
        [
            ("策略", "网关不知道谁在交易"),
        ],
        "Phase 2",
    ),
    (
        "runtime",
        "L8",
        "实盘会话装配、状态持久化、持仓对账、交易日调度、到期换月强平(R16/R18/R31)。",
        [],
        "Phase 6",
    ),
    (
        "apps",
        "L9",
        "CLI 单一入口 `qf`、只读监控面板、headless 录制器(R23)。",
        [
            ("", "`apps/monitor.py` 不得 import 除 obs 与 core 之外的任何本项目模块。这条可机械检查,它保证监控面板不可能意外拿锁、开 CTP 会话或碰交易库 —— 双进程方案(ADR-0008)的技术兑现(R24.14)"),
        ],
        "Phase 0(CLI 骨架)/ Phase 2(录制器与监控)",
    ),
]

TEMPLATE = """# {name}   (层级:{layer})

## 职责

{duty}

## 公开接口

必须与 `__init__.py` 的 `__all__` 完全一致,由 `tests/test_docs_contract.py` 强制(R26.6)。

{api}

## 不变式

{invariants}

## 禁止 import

{forbidden}

## 为什么这么设计

{rationale}

## 否决过的方案

{rejected}

## 已知局限

{limits}

## 测试

```powershell
.venv\\Scripts\\python.exe -m pytest tests/{name} -q
```
"""

PENDING = "_待 {phase} 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。"


def build(name: str, layer: str, duty: str, forbidden: list[tuple[str, str]], phase: str) -> str:
    api = "_本模块尚未实现,`__all__` 为空。_" if name != "core" else ""
    lines = [
        f"- **不得 import {what}** —— {why}" if what else f"- **{why}**"
        for what, why in forbidden
    ]
    forbidden_text = "\n".join(lines) or "本层没有额外的禁止导入项;仍须遵守 `.importlinter` 的层级契约。"
    return TEMPLATE.format(
        name=name,
        layer=layer,
        duty=duty,
        api=api,
        invariants=PENDING.format(phase=phase),
        forbidden=forbidden_text,
        rationale=f"见 [`docs/IMPLEMENTATION_PLAN.md`](../../docs/IMPLEMENTATION_PLAN.md) 与 `docs/adr/`。本模块于 {phase} 落地。",
        rejected=PENDING.format(phase=phase),
        limits=PENDING.format(phase=phase),
    )


def main() -> None:
    created: list[str] = []
    for name, layer, duty, forbidden, phase in MODULES:
        pkg = ROOT / "src" / name
        pkg.mkdir(parents=True, exist_ok=True)

        init = pkg / "__init__.py"
        if not init.exists():
            init.write_text(
                f'"""{name} ({layer}) —— {duty}\n\n'
                f"公开接口、不变式与禁止 import 见同目录 README.md。\n"
                f'本模块于 {phase} 落地,当前为 Phase 0 存根。\n"""\n\n'
                "__all__: list[str] = []\n",
                encoding="utf-8",
            )
            created.append(str(init.relative_to(ROOT)))

        readme = pkg / "README.md"
        if not readme.exists():
            readme.write_text(build(name, layer, duty, forbidden, phase), encoding="utf-8")
            created.append(str(readme.relative_to(ROOT)))

        test_dir = ROOT / "tests" / name
        test_dir.mkdir(parents=True, exist_ok=True)
        keep = test_dir / ".gitkeep"
        if not keep.exists() and not any(test_dir.glob("test_*.py")):
            keep.touch()
            created.append(str(keep.relative_to(ROOT)))

    for path in created:
        print(f"  + {path}")
    print(f"共创建 {len(created)} 个文件")


if __name__ == "__main__":
    main()
