"""L2 Kernel/Harness —— 纯机制：turn 循环、事件总线、权限引擎、恢复。

只调度、判权限、写状态、发事件；绝不 import 模型或 UI。依赖
:mod:`questor.contracts` + :mod:`questor.state` 与注入的 Port——绝不 import policy/surfaces
的具体实现（C1/C14）。"""
