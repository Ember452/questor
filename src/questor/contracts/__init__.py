"""L0 Contracts —— 全系统共享的“词汇”（schema、事件、Port 协议）。

最内、最稳定层：只放**抽象接口 + frozen 数据 + 确定性纯函数**（如 ``errors.classify_provider_error``、
``profile.normalize``）；**零 IO、零外层 import、无业务分支**（HARD C1/C14；STRUCTURE S4）。
旧文案写“无实现”易被读成“无任何代码”——实际存在的是与 IO/状态无关的纯词汇函数，此处按实物改口。
此处改动一律只增不改（C6/C11）。
"""
