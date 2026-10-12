# StoryOS Runtime Tick 日志无损轮转（2026-10-12）

## 范围与安全约束

- 仅限 Phase9 Worker 的 worker-ticks.jsonl 遥测文件；不触碰 worker-alerts.jsonl、MySQL、Episode、Review Authority、Trace/Event/Artifact 证据。
- 在单 Worker 下一次 tick 写入之前，达到阈值的旧日志重命名至 tick-archives，然后以 gzip 无损归档。
- 压缩成功必须经过 SHA-256 解压校验才能删除 raw 临时源；压缩故障留下 raw 快照，不丢记录。
- 阈值默认 64 MiB，可由 --tick-log-max-mib 0 禁用；归档不会自动删减，保留全部历史数据。
- 多进程写同一日志路径不受支持。每个并发 Worker 必须使用不同的 --tick-log 路径；本轮不会变更活动进程。

## 上线与验收

新 Launcher 进程的启用方式：

    python scripts/phase9_runtime_launcher.py --tick-log-max-mib 64

当前运行中的 Python 进程不会热更新，直到按正常运维窗口重启；不得擅自为了清理磁盘而打断生产。
禁止从外部进程截断或删除热日志，禁止用 Git clean 或 force 删除运行数据。
验收命令：

    pytest -q tests/platform/test_storyos_runtime_tick_rotation.py tests/platform/test_phase9_runtime_worker.py tests/platform/test_phase9_runtime_launcher.py

日志保留是运维治理而非正式发布权限，不能改变 Episode Review/Gate 结论。
