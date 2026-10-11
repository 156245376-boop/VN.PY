# apps   (层级:L9)

## 职责

CLI 单一入口 `qf`、只读监控面板、headless 录制器(R23)。

## 公开接口

必须与 `__init__.py` 的 `__all__` 完全一致,由 `tests/test_docs_contract.py` 强制(R26.6)。

_本模块尚未实现,`__all__` 为空。_

## 不变式

_待 Phase 0(CLI 骨架)/ Phase 2(录制器与监控) 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 禁止 import

- **`apps/monitor.py` 不得 import 除 obs 与 core 之外的任何本项目模块** —— 这条可机械检查,它保证监控面板不可能意外拿锁、开 CTP 会话或碰交易库 —— 双进程方案(ADR-0008)的技术兑现(R24.14)。

## 为什么这么设计

见 [`docs/IMPLEMENTATION_PLAN.md`](../../docs/IMPLEMENTATION_PLAN.md) 与 `docs/adr/`。本模块于 Phase 0(CLI 骨架)/ Phase 2(录制器与监控) 落地。

## 否决过的方案

_待 Phase 0(CLI 骨架)/ Phase 2(录制器与监控) 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 已知局限

_待 Phase 0(CLI 骨架)/ Phase 2(录制器与监控) 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 测试

```powershell
.venv\Scripts\python.exe -m pytest tests/apps -q
```
