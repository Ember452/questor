"""横切：配置加载层（OPT-3）。

职责：把组合根的 **env 读取**收口成一份 frozen 纯数据（:mod:`questor.config.model`）。

- 模块入口：``load_config()`` —— 纯读、无 IO、无缓存，读取时点 = 调用时点；
- 分层：横切层，只 import stdlib；**与 observability 相互独立**（见 .importlinter），
  不得被 L0/L1 import；
- 只负责"读"：``*_from_env`` 的解析/校验/fail-closed 判定仍留在调用点（``surfaces._assembly``
  的 compaction/payload、``__main__`` 的子命令分支），避免"读"与"判"混成一团。
"""
