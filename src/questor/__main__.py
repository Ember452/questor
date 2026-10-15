"""入口：启动 CLI 传输面（P1 的交互演示）。

用 ``python -m questor`` 运行。Python sidecar / Tauri 启动点在后续阶段接入；P1 这里
启动“问一句、流式答一句”的终端。"""

from questor.surfaces.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
