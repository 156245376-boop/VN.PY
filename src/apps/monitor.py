"""只读监控外壳(R23.4/R24.14)。

**本文件的导入清单本身就是一项契约。** `.importlinter` 强制它只依赖 `obs` 与
`core` —— 这条可机械检查的约束保证监控面板不可能意外拿 DuckDB 写锁、开 CTP
会话或碰交易库,即双进程方案(ADR-0008)的技术兑现。

为什么值得用机械手段而非纪律:监控代码是最容易"顺手加一行查询"的地方,而那一行
会让面板与录制器争夺 warehouse.duckdb 的排他锁 —— 表现是**录制器丢 tick**,而
丢掉的历史数据买不回来。

Phase 0 只建立文件与契约检查点。真正的实现在 Phase 2,届时读取 State_Snapshot 与
事件流文件(R20.11),写入操作一概没有。
"""

from __future__ import annotations

__all__: list[str] = []


def main() -> None:
    """监控面板入口。Phase 2 落地。"""
    print("apps.monitor 尚未实现,计划于 Phase 2 落地。")
    print("届时只读 data/runtime/snapshot.json 与 events.jsonl,不建立 CTP 连接。")


if __name__ == "__main__":
    main()
