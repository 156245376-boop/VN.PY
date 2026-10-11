# strategy   (层级:L4)

## 职责

策略纯逻辑类与 Strategy_Context 协议。以目标持仓表达交易意图(R11)。

## 公开接口

必须与 `__init__.py` 的 `__all__` 完全一致,由 `tests/test_docs_contract.py` 强制(R26.6)。

_本模块尚未实现,`__all__` 为空。_

## 不变式

_待 Phase 5b 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 禁止 import

- **不得 import 任何交易框架(vnpy 及其插件)** —— 直接继承框架基类会永久锁死 vnpy,换引擎需重写每个策略(ADR-0004)。由 `.importlinter` 强制(R24.13)
- **不得 import 交易所身份、平今平昨、费率、保证金、委托号、券商、数据库、网络** —— 策略说「我要净持 −2 手」,不说「用 CLOSE_TODAY 买 2 手」—— 后者要求策略知道上期所规则与今昨仓拆分,任何自研引擎都无法复现(ADR-0003)
- **不得 import pandas / polars / duckdb** —— 策略须可在向量化引擎内逐根调用,DataFrame 开销与之不相容

## 为什么这么设计

见 [`docs/IMPLEMENTATION_PLAN.md`](../../docs/IMPLEMENTATION_PLAN.md) 与 `docs/adr/`。本模块于 Phase 5b 落地。

## 否决过的方案

_待 Phase 5b 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 已知局限

_待 Phase 5b 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 测试

```powershell
.venv\Scripts\python.exe -m pytest tests/strategy -q
```
