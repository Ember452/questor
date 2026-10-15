"""L0 Contracts —— 全系统共享的“词汇”（schema、事件、Port 协议）。

最内、最稳定层：只放**抽象接口 + frozen 数据**；无实现、无 I/O，绝不 import 任何外层
（HARD C1/C14；STRUCTURE S4）。此处改动一律只增不改（C6/C11）。
"""
