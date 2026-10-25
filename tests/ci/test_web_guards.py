"""前端骨架守卫：禁 WebSocket、禁 app-server 契约、生成物必须存在。

与 `test_vendor_pristine.py` 分工：那里管“改动登记”，这里管“架构禁令”。
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WEB_SRC = REPO / "apps/web/src"


def scan_forbidden(root: Path, needle: str) -> list[str]:
    """返回包含 needle 的文件（相对路径）。"""
    hits: list[str] = []
    for path in root.rglob("*"):
        if path.suffix not in {".ts", ".tsx"} or not path.is_file():
            continue
        if needle in path.read_text(encoding="utf-8"):
            hits.append(str(path.relative_to(root)))
    return hits


def test_no_websocket_transport() -> None:
    """ADR-0006：传输是 SSE + POST，不得出现 WebSocket。"""
    assert scan_forbidden(WEB_SRC, "new WebSocket") == []


def test_no_app_server_contract() -> None:
    """旧 DeepCode 契约（生成物与类型）不得被引用。"""
    hits = [p for p in scan_forbidden(WEB_SRC, "generated/app-server") if "generated/" not in p]
    assert hits == []


def test_generated_contract_and_fixtures_exist() -> None:
    """wire 生成物与黄金帧必须在仓（由 codegen 步骤保证新鲜）。"""
    assert (REPO / "apps/web/src/generated/app-wire.ts").is_file()
    assert (REPO / "apps/web/src/generated/wire-fixtures.json").is_file()


def test_scanner_self_test(tmp_path: Path) -> None:
    """自证：命中一次就必须报告一次。"""
    (tmp_path / "a.ts").write_text("const x = new WebSocket('ws://x');\n", encoding="utf-8")
    assert scan_forbidden(tmp_path, "new WebSocket") == ["a.ts"]
