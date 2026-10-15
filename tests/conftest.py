"""测试全局守卫：拦住"未释放的非守护线程"，并保证卡死时进程仍能退出（CI 挂死的根因防线）。

为什么要这两个钩子：本仓的失败模式是 connect 之后忘记 close，症状却出现在很久之后——
pytest 已打印完 summary，进程卡在解释器退出的 ``threading._shutdown()`` join 上，CI 表现为
pytest step 永不结束（本次事故里 6 个 run 各挂了 12~70 分钟）。这种失败在 CI 里几乎无法定位，
所以在测试层就拦住：

* autouse fixture —— 每个测试结束时判泄漏，把不可定位的挂死翻译成"哪个测试泄漏了什么线程"
  的一条红色失败，栈直接指向创建点；
* sessionfinish 看门狗 —— 会话结束时若仍有泄漏线程，先打栈再装守护定时器：正常收尾能退出就
  没事，退出被卡住则几秒后以非零码硬退，绝不把挂死留给 timeout-minutes。

检测与自检逻辑在 scripts/check_thread_leak.py（与分层/契约守卫同一口径：必须自带能判红的
self-test），那里还记录了"为什么不能事后把线程标成守护"这条实测结论。
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_guard() -> ModuleType:
    """按 scripts/ 守卫的既有惯例用 importlib 加载（scripts 不在 import 路径上）。"""
    name = "check_thread_leak"
    cached = sys.modules.get(name)
    if isinstance(cached, ModuleType):
        return cached
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_guard = _load_guard()

#: 会话开始时的非守护线程基线，供 sessionfinish 判断"本会话新造的"线程。
_SESSION_BASELINE = _guard.snapshot()


@pytest.fixture(autouse=True)
def fail_on_non_daemon_thread_leak() -> Iterator[None]:
    """测试前取基线、测试后判泄漏：新增且宽限期后仍存活的非守护线程即判红。"""
    before = _guard.snapshot()
    yield
    leaked = _guard.detect(before)
    if leaked:
        # 只判红、不试图"修好"它：已启动线程的 daemon 标志改不了（见守卫脚本里的说明），
        # 硬退出交给 sessionfinish 的看门狗，以免守卫自己变成新的挂死源。
        pytest.fail(_guard.report(leaked), pytrace=False)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """会话结束时兜底：仍有泄漏线程就打出全部栈，并装上守护退出看门狗。

    为什么不会洗白失败：看门狗只在真检出泄漏时上弹，且以非零码 ``os._exit``；正常退出时
    它是守护线程、根本不参与终结 join，也就永远不会开火。
    """
    leaked = _guard.detect(_SESSION_BASELINE)
    if not leaked:
        return
    print(f"\nthread-leak guard (sessionfinish): {_guard.report(leaked)}", file=sys.stderr, flush=True)
    _guard.arm_exit_watchdog()
