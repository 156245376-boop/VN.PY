# execution   (层级:L6)

## 职责

目标持仓差额 → 委托意图:开平方向解析、平今平昨决策、限价定价与涨跌停钳制(R17)。

## 公开接口

必须与 `__init__.py` 的 `__all__` 完全一致,由 `tests/test_docs_contract.py` 强制(R26.6)。

_本模块尚未实现,`__all__` 为空。_

## 不变式

_待 Phase 6 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 禁止 import

- **不得 import vnpy、网关** —— 本模块产出 OrderIntent,由 engines/ 或 gateway/ 翻译成框架词汇
- **不得 import 策略类** —— 执行层只读目标持仓数值,不认识策略对象
- **不得 import 磁盘** —— 开平决策须为纯函数以便表驱动测试

## 为什么这么设计

见 [`docs/IMPLEMENTATION_PLAN.md`](../../docs/IMPLEMENTATION_PLAN.md) 与 `docs/adr/`。本模块于 Phase 6 落地。

## 否决过的方案

_待 Phase 6 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 已知局限

_待 Phase 6 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 测试

```powershell
.venv\Scripts\python.exe -m pytest tests/execution -q
```
