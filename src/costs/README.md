# costs   (层级:L5)

## 职责

手续费、滑点、保证金占用计算。回测与实盘调用同一批函数(R29)。

## 公开接口

必须与 `__init__.py` 的 `__all__` 完全一致,由 `tests/test_docs_contract.py` 强制(R26.6)。

_本模块尚未实现,`__all__` 为空。_

## 不变式

_待 Phase 5b 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 禁止 import

- **不得 import 引擎身份** —— 本模块不知道调用方是回测还是实盘 —— 这个同一性正是防止回测实盘分裂的机制(ADR-0005)
- **不得 import vnpy** —— vnpy 回测只支持 turnover×rate,收不到按手固定费与平今差异(A3),故费用计算必须在框架之外

## 为什么这么设计

见 [`docs/IMPLEMENTATION_PLAN.md`](../../docs/IMPLEMENTATION_PLAN.md) 与 `docs/adr/`。本模块于 Phase 5b 落地。

## 否决过的方案

_待 Phase 5b 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 已知局限

_待 Phase 5b 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 测试

```powershell
.venv\Scripts\python.exe -m pytest tests/costs -q
```
