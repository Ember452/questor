"""B5 T4：工具集=数据（OPT-5）+ 六方言 → descriptor 映射（§5.1/§5.2）。"""

from __future__ import annotations

from questor.capabilities.extension_dialects import DIALECTS, descriptor_for, dialect_descriptors
from questor.capabilities.toolset import DEFAULT_PROFILE, PROFILES, TOOL_FACTORIES, build_tools, tool_ids
from questor.contracts.extension import LIVE_POINTS, ExtensionKind
from questor.policy.registry import ExtensionEntry, ExtensionRegistry


def test_default_profile_keeps_the_exact_eleven_tool_order() -> None:
    assert tool_ids() == (
        "read",
        "write",
        "edit",
        "apply_patch",
        "ls",
        "glob",
        "grep",
        "bash",
        "powershell",
        "memory_search",
        "delegate",
    )
    assert [tool.spec.name for tool in build_tools()] == list(tool_ids())


def test_every_factory_produces_the_matching_tool_id() -> None:
    assert set(TOOL_FACTORIES) == set(PROFILES[DEFAULT_PROFILE])
    for tool_id, factory in TOOL_FACTORIES.items():
        assert factory().spec.name == tool_id


def test_unknown_profile_falls_back_to_default_instead_of_empty() -> None:
    assert tool_ids("does-not-exist") == tool_ids(DEFAULT_PROFILE)
    assert [tool.spec.name for tool in build_tools("does-not-exist")] == list(tool_ids(DEFAULT_PROFILE))


def test_six_dialects_map_to_closed_live_points() -> None:
    assert DIALECTS == ("policy", "tool", "memory", "compaction", "permission", "provider")
    descriptors = dialect_descriptors()
    assert len(descriptors) == 6
    assert len({descriptor.id for descriptor in descriptors}) == 6
    for descriptor in descriptors:
        assert descriptor.at in LIVE_POINTS
        assert descriptor.kind in {ExtensionKind.TRANSFORM, ExtensionKind.DECISION, ExtensionKind.OBSERVE}


def test_dialects_can_register_in_the_generic_registry() -> None:
    registry = ExtensionRegistry()
    for descriptor in dialect_descriptors():
        registry.register(ExtensionEntry(descriptor, lambda: None))
    text = registry.render_chain()
    for descriptor in dialect_descriptors():
        assert descriptor.id in text


def test_unknown_dialect_is_rejected() -> None:
    try:
        descriptor_for("nope")
    except ValueError as exc:
        assert "unknown extension dialect" in str(exc)
    else:  # pragma: no cover - 必须抛
        raise AssertionError("unknown dialect must raise")
