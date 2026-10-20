"""T14：ToolRegistry 与 run 内工具面冻结（design/03 §6；04 §6）。"""

from __future__ import annotations

from pathlib import Path

from questor.capabilities.tools.read import ReadTool
from questor.capabilities.tools.registry import RunToolSurface, ToolRegistry
from questor.contracts.tool import Capability, Risk, Tool, ToolContext, ToolResult, ToolSpec


def _spec(name: str, description: str, *, available: bool = True) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        params={"type": "object", "properties": {}, "additionalProperties": False},
        capability=Capability.READONLY,
        risk=Risk.LOW,
        read_only=True,
        available=available,
    )


class _NamedTool(Tool):
    def __init__(self, spec: ToolSpec, *, available: bool = True) -> None:
        self.spec = spec
        self._available = available

    def available(self) -> bool:
        return self._available

    async def execute(self, args, ctx: ToolContext) -> ToolResult:  # noqa: ANN001
        return ToolResult(status="success", result=self.spec.name)


def test_register_get_has_unregister() -> None:
    registry = ToolRegistry()
    tool = _NamedTool(_spec("alpha", "an available alpha reading tool for tests"))
    registry.register(tool)
    assert registry.has("alpha")
    assert registry.get("alpha") is tool
    registry.unregister("alpha")
    assert not registry.has("alpha")
    assert registry.get("alpha") is None


def test_list_available_and_definitions_skip_unavailable() -> None:
    registry = ToolRegistry()
    registry.register(_NamedTool(_spec("on", "this tool is available for use")))
    registry.register(_NamedTool(_spec("off", "this tool is disabled by default"), available=False))
    names = {tool.spec.name for tool in registry.list_available()}
    spec_names = {spec.name for spec in registry.definitions()}
    assert names == {"on"}
    assert spec_names == {"on"}


def test_description_sanitized_and_bounded() -> None:
    registry = ToolRegistry()
    # too short -> 退化到含工具名的说明；超长 -> 截断；控制字符 -> 去除。
    registry.register(_NamedTool(_spec("tiny", "x")))
    registry.register(_NamedTool(_spec("long", "y" * 5000)))
    registry.register(_NamedTool(_spec("ctl", "dea\u0000dful description with control chars inside")))
    specs = {spec.name: spec for spec in registry.definitions()}
    assert len(specs["tiny"].description) >= 20
    assert specs["tiny"].description  # 仍含工具名可辨识
    assert "tiny" in specs["tiny"].description
    assert len(specs["long"].description) <= 2000
    assert "\x00" not in specs["ctl"].description


def test_freeze_for_run_is_snapshot_isolated() -> None:
    registry = ToolRegistry()
    registry.register(_NamedTool(_spec("a", "first available tool for snapshot test")))
    surface = registry.freeze_for_run("run-1")
    assert isinstance(surface, RunToolSurface)
    assert {s.name for s in surface.specs} == {"a"}
    # run 之后再改注册表，不影响已冻结 surface。
    registry.register(_NamedTool(_spec("b", "second available tool added later")))
    assert {s.name for s in surface.specs} == {"a"}
    assert surface.get("b") is None
    assert registry.freeze_for_run("run-2").get("b") is not None


def test_surface_tool_for_reads_from_frozen_view(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(ReadTool())
    surface = registry.freeze_for_run("run-x")
    assert surface.tool_for("read") is not None
    assert surface.tool_for("missing") is None
    assert {s.name for s in surface.specs} == {"read"}


def test_candidates_hint_for_unknown_tool() -> None:
    registry = ToolRegistry()
    registry.register(_NamedTool(_spec("read", "read a workspace file")))
    registry.register(_NamedTool(_spec("write", "write a workspace file")))
    candidates = registry.candidates("redi")
    assert "read" in candidates
    assert registry.candidates("zzzzz") == ()


def test_spec_level_available_flag_is_wired_not_dead() -> None:
    """G7：`ToolSpec.available=False` 现在真的把工具关在外露面之外（仍已注册）。"""
    registry = ToolRegistry()
    quiet = _NamedTool(_spec("quiet", "a tool switched off at declaration time", available=False), available=True)
    registry.register(quiet)
    registry.register(_NamedTool(_spec("loud", "a tool switched on everywhere")))
    assert registry.get("quiet") is quiet  # 注册仍在，只是不外露
    assert {tool.spec.name for tool in registry.list_available()} == {"loud"}
    assert {spec.name for spec in registry.definitions()} == {"loud"}
    surface = registry.freeze_for_run("run-g7")
    assert {spec.name for spec in surface.specs} == {"loud"}
    assert surface.get("quiet") is None


def test_default_tools_keep_spec_available_true_so_nothing_disappears() -> None:
    """接线 `spec.available` 对现有名册零行为变更（无人写 False）。"""
    registry = ToolRegistry()
    registry.register(ReadTool())
    assert ReadTool().spec.available is True
    assert {spec.name for spec in registry.definitions()} == {"read"}
