"""租约/幂等/排队/提示归属的状态机单测。"""

from __future__ import annotations

import asyncio

import pytest

from questorharness.bootstrap.hosts.serve import refusals
from questorharness.bootstrap.hosts.serve.authority import Authority


def test_first_submit_starts_and_second_is_queued() -> None:
    """单写者：第二个提交进容量为 1 的排队槽。"""
    authority = Authority()
    first = authority.begin("c1", "r1", "one")
    second = authority.begin("c2", "r2", "two")
    assert first.kind == "started"
    assert second.kind == "queued"
    assert second.position == 1


def test_third_submit_is_busy() -> None:
    """队列满后必须显式拒绝，而不是静默丢弃。"""
    authority = Authority()
    authority.begin("c1", "r1", "one")
    authority.begin("c2", "r2", "two")
    with pytest.raises(refusals.Refusal) as excinfo:
        authority.begin("c3", "r3", "three")
    assert excinfo.value.code == refusals.TURN_BUSY


def test_repeated_request_id_is_replay_not_a_second_turn() -> None:
    """同一 clientRequestId 只产生一个回合。"""
    authority = Authority()
    first = authority.begin("c1", "same", "one")
    replay = authority.begin("c1", "same", "one")
    assert replay.kind == "replay"
    assert replay.turn_id == first.turn_id


def test_finish_releases_lease_and_queue_can_promote() -> None:
    """回合结束后可取出排队回合。"""
    authority = Authority()
    first = authority.begin("c1", "r1", "one")
    authority.begin("c1", "r2", "two")
    authority.finish(first.turn_id)
    assert authority.active_turn is None
    promoted = authority.pop_queued()
    assert promoted is not None
    assert promoted.state == "running"
    assert authority.active_turn is not None


def test_owner_check_requires_same_client() -> None:
    """只有持有者通过 is_owner。"""
    authority = Authority()
    begin = authority.begin("c1", "r1", "one")
    assert authority.is_owner(begin.turn_id, "c1")
    assert not authority.is_owner(begin.turn_id, "c2")


def test_approval_settles_once_and_only_for_owner() -> None:
    """审批：非持有者与重复结算各有独立拒绝码。"""

    async def scenario() -> None:
        authority = Authority()
        authority.begin("owner", "r1", "one")
        waiter = asyncio.create_task(authority.permission_prompt("bash", "rm -rf x"))
        await asyncio.sleep(0)
        prompt_id = next(iter(authority._prompts))  # noqa: SLF001 - 单测读取内部表
        with pytest.raises(refusals.Refusal) as excinfo:
            authority.settle(prompt_id, True, "intruder")
        assert excinfo.value.code == refusals.APPROVAL_NOT_OWNER
        authority.settle(prompt_id, True, "owner")
        assert await waiter is True
        with pytest.raises(refusals.Refusal):
            authority.settle(prompt_id, False, "owner")

    asyncio.run(scenario())


def test_ask_uses_ask_specific_refusal_codes() -> None:
    """提问走 ask.* 拒绝码，不与审批混用。"""

    async def scenario() -> None:
        authority = Authority()
        authority.begin("owner", "r1", "one")
        waiter = asyncio.create_task(authority.ask_user_prompt("which file?"))
        await asyncio.sleep(0)
        prompt_id = next(iter(authority._prompts))  # noqa: SLF001
        with pytest.raises(refusals.Refusal) as excinfo:
            authority.settle(prompt_id, "a.txt", "intruder")
        assert excinfo.value.code == refusals.ASK_NOT_OWNER
        authority.settle(prompt_id, "a.txt", "owner")
        assert await waiter == "a.txt"

    asyncio.run(scenario())
