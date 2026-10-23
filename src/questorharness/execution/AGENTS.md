# execution — Agent Contract

职责：把 shell、网络与沙箱调用包成可测试的执行边界。
不负责：回合循环与策略判定在 `src/questorharness/engine`；沙箱供应商实现在 `src/questorharness/providers/sandbox`。
公开入口：`__init__.py`。
拥有的数据：无持久数据；只拥有子进程与网络调用的生命周期。
允许依赖：`config` + `platform` + `providers`，由 `layers` 契约守住。
不变式：执行入口必须可注入替身；权限判定不在执行层发生。
禁止：不要在这里加权限或审计分支，那是 `src/questorharness/capabilities/policy` 的横切点。
测试：`uv run pytest tests/unit/test_utils tests/integration/test_sandbox -q`
关键文件：`__init__.py`、`shell.py`、`network.py`
