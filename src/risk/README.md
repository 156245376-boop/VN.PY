# risk   (层级:L6)

## 职责

纯否决函数 `screen(intents, state, limits) -> Verdict`(R19)。

## 公开接口

必须与 `__init__.py` 的 `__all__` 完全一致,由 `tests/test_docs_contract.py` 强制(R26.6)。

_本模块尚未实现,`__all__` 为空。_

## 不变式

_待 Phase 6 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 禁止 import

- **不得 import execution** —— 风控不得依赖执行细节,否则无法在下单前独立校验(R19.2)
- **不得 import vnpy、网关、磁盘** —— 风控须可在测试中以构造的账户状态直接调用

## 为什么这么设计

见 [`docs/IMPLEMENTATION_PLAN.md`](../../docs/IMPLEMENTATION_PLAN.md) 与 `docs/adr/`。本模块于 Phase 6 落地。

## 否决过的方案

_待 Phase 6 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 已知局限

_待 Phase 6 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 测试

```powershell
.venv\Scripts\python.exe -m pytest tests/risk -q
```
