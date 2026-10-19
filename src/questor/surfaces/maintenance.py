"""L6 surfaces：``questor maintenance`` 账本卫生回收触发（P10/Major-2、ADR-0050）。

给 Lane D 的回收方法一个**生产调用方**（审计 Minor-2：回收逻辑正确但从不运行→账本无界增长动机未解）。
只回收**瞬态派生视图**——过期/已释放 `run_lease` + 超 TTL 未 ack 的 in-flight claim；**绝不碰
acked delivery 行**（BLK-2，绑 event_log 裁剪后置）。artifact 孤儿 GC 的 `gc_orphans` 方法已就绪，且
`FileSystemArtifactStore` 现由 ``composition.build_app`` 实例化（#154）；但本 maintenance 命令只持
``StorePort``、未接 artifact 根的调度触发，故此处仅回收账本、artifact GC 诚实标"方法就绪、触发未接本命令"。
"""

from __future__ import annotations

import time

from questor.contracts.ports import StorePort


async def run_maintenance_command(store: StorePort) -> str:
    """触发一次账本回收：删过期 lease + 超 TTL 未 ack claim；返回计数摘要。

    幂等、可重复运行；acked delivery 行与其它耐久数据不受影响（见 `reclaim_stale_claims` 实现）。"""
    now = time.time()
    leases = await store.reclaim_expired_leases(now)
    claims = await store.reclaim_stale_claims(now)
    return f"maintenance: reclaimed_leases={leases} reclaimed_stale_claims={claims}"
