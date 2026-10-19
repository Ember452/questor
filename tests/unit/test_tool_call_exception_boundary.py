"""#168：工具调用入参 schema 校验是失败域、绝不打穿 drive 循环。"""

from __future__ import annotations

from questor.kernel.loop import _schema_error


def test_schema_error_never_raises_on_pathological_schema() -> None:
    """不可信/畸形 schema（含无法解析的 $ref、坏 type）必须返回错误串而非抛出（否则 run 不落终态）。"""
    for bad in (
        {"$ref": "#/definitions/Missing"},
        {"$ref": "http://unresolvable.invalid/s.json"},
        {"type": 123},
        {"properties": {"a": {"type": 999}}},
    ):
        result = _schema_error(bad, {"a": 1})  # 绝不抛
        assert result is None or isinstance(result, str)


def test_schema_error_still_flags_invalid_args() -> None:
    """正常 schema + 非法入参：仍返回 'invalid arguments:'（fail-closed 语义不变）。"""
    err = _schema_error({"type": "object", "required": ["name"]}, {})
    assert err is not None and err.startswith("invalid arguments")


def test_schema_error_passes_valid_args() -> None:
    assert _schema_error({"type": "object", "required": ["name"]}, {"name": "x"}) is None
