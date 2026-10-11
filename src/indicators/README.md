# indicators   (层级:L4)

## 职责

纯 numpy 技术指标,每个提供标量式与序列式双形态(R33.7)。

## 公开接口

必须与 `__init__.py` 的 `__all__` 完全一致,由 `tests/test_docs_contract.py` 强制(R26.6)。

_本模块尚未实现,`__all__` 为空。_

## 不变式

_待 Phase 5b 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 禁止 import

- **不得 import vnpy** —— 复用 vnpy 的 ArrayManager 会把 vnpy 拖进 strategy 的 import 闭包(ADR-0010)
- **不得 import 行情来源、磁盘、pandas** —— 指标是数组上的自由函数,不持有状态也不知道数据从哪来

## 为什么这么设计

见 [`docs/IMPLEMENTATION_PLAN.md`](../../docs/IMPLEMENTATION_PLAN.md) 与 `docs/adr/`。本模块于 Phase 5b 落地。

## 否决过的方案

_待 Phase 5b 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 已知局限

_待 Phase 5b 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 测试

```powershell
.venv\Scripts\python.exe -m pytest tests/indicators -q
```
