# runtime   (层级:L8)

## 职责

实盘会话装配、状态持久化、持仓对账、交易日调度、到期换月强平(R16/R18/R31)。

## 公开接口

必须与 `__init__.py` 的 `__all__` 完全一致,由 `tests/test_docs_contract.py` 强制(R26.6)。

_本模块尚未实现,`__all__` 为空。_

## 不变式

_待 Phase 6 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 禁止 import

本层负责汇合其下全部层级,没有额外的禁止导入项。`engines` 与 `gateway` 同属 L7 且互不导入,只能由本层汇合;该约束由 `.importlinter` 强制。

## 为什么这么设计

见 [`docs/IMPLEMENTATION_PLAN.md`](../../docs/IMPLEMENTATION_PLAN.md) 与 `docs/adr/`。本模块于 Phase 6 落地。

## 否决过的方案

_待 Phase 6 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 已知局限

_待 Phase 6 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 测试

```powershell
.venv\Scripts\python.exe -m pytest tests/runtime -q
```
