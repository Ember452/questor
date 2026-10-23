# platform — Agent Contract

职责：文件系统、路径、锁与原子写入原语。
不负责：领域语义与词表在 `src/questorharness/contracts`；会话结构语义在 `src/questorharness/runtime`。
公开入口：`__init__.py`。
拥有的数据：磁盘布局（会话目录、配置目录）与文件锁。
允许依赖：`contracts` 而已，由 `layers` 与 `config-is-leaf` 守住。
不变式：写入一律走 `io.atomic_write_text`；路径解析只在这一处。
禁止：不要在这里读配置或判权限；不要再开 `utils.py` 式杂物文件。
测试：`uv run pytest tests/unit/test_platform tests/unit/test_paths -q`
关键文件：`__init__.py`、`paths.py`、`io.py`
