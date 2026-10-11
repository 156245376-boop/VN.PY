# engines   (层级:L7)

## 职责

Strategy 到具体引擎的适配器,以及回测装配(R12/R13)。

## 公开接口

必须与 `__init__.py` 的 `__all__` 完全一致,由 `tests/test_docs_contract.py` 强制(R26.6)。

_本模块尚未实现,`__all__` 为空。_

## 不变式

_待 Phase 5a(选型)/ Phase 5b(桥) 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 禁止 import

本层没有额外的禁止导入项,并且是系统内**唯一**可同时依赖交易框架与 Strategy 的位置(R11.7)。vnpy 回测与实盘共用同一个 CtaTemplate,故只有一个桥而不是两个;拆开会招致分裂,而分裂是回测实盘不一致的头号来源。

## 为什么这么设计

见 [`docs/IMPLEMENTATION_PLAN.md`](../../docs/IMPLEMENTATION_PLAN.md) 与 `docs/adr/`。本模块于 Phase 5a(选型)/ Phase 5b(桥) 落地。

## 否决过的方案

_待 Phase 5a(选型)/ Phase 5b(桥) 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 已知局限

_待 Phase 5a(选型)/ Phase 5b(桥) 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 测试

```powershell
.venv\Scripts\python.exe -m pytest tests/engines -q
```
