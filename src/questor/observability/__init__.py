"""横切可观测性（ADR-0027；STRUCTURE S7）：日志 = ``event_log`` 的人类可读旁路镜像（DESIGN §1/§9）。

内部三层（DESIGN §3）：
- 内核九文件（``entry``/``scope``/``redact``/``exporter``/``sink_console``/``sink_file``/``bridge``/
  ``pipeline``/``configure``）——零 ``questor.*`` 外部依赖（连 contracts 都不许），可整体抽包。
- 适配层 ``projection``——**唯一允许 import** ``questor.contracts``；把 ``Envelope`` 投成 ``LogEntry``。
只读上报、绝不改状态（S7）；完整 tracing/metrics 归 P10。"""
