# config   (层级:L1)

## 职责

加载、校验、保存用户选择类配置,并使凭证不进入版本库(R22)。

## 公开接口

必须与 `__init__.py` 的 `__all__` 完全一致,由 `tests/test_docs_contract.py` 强制(R26.6)。

_本模块尚未实现,`__all__` 为空。_

## 不变式

_待 Phase 0(骨架)/ Phase 2(完整) 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 禁止 import

- **不得 import 市场事实类取值** —— 费率、保证金、时段属于 meta/ 的 SCD-2 表。放进配置意味着回测 2019 年用今天的保证金(R22.3)
- **不得 import 策略、委托、数据库** —— 配置是被读取方,不得反向依赖使用方

## 为什么这么设计

见 [`docs/IMPLEMENTATION_PLAN.md`](../../docs/IMPLEMENTATION_PLAN.md) 与 `docs/adr/`。本模块于 Phase 0(骨架)/ Phase 2(完整) 落地。

## 否决过的方案

_待 Phase 0(骨架)/ Phase 2(完整) 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 已知局限

_待 Phase 0(骨架)/ Phase 2(完整) 实施时填写。_ 事后补写不出当时的约束与否决理由,但提前编造更糟。

## 测试

```powershell
.venv\Scripts\python.exe -m pytest tests/config -q
```
