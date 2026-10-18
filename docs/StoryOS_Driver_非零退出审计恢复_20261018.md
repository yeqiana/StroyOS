# Driver 非零退出后的单次审计恢复

现有普通 start/plan 与 Watchdog 对非零退出仍一律阻断。本流程只为已经证明且在 CI 验证完成的特定崩溃提供单次恢复；不是通用重试开关。

适用条件：
- 历史状态 EXITED、PID 0、liveness DEAD、退出码 900；崩溃日志确切包含 final semantic source bindings changed before commit。
- 修复文件是 PR #110 经 Ubuntu/Windows Story Gates 及 Qodana 验证的 frame_semantic_review.py，Git blob a9e66908c5fb92e43908a42a0c4d60e74535fe90。
- SHA256 要对原始 Driver record 的规范 JSON、真实崩溃日志原字节、已部署源码原字节分别计算；源文件并非这个已验证版本时严禁恢复。
- 所有其他 MySQL Stage、Revision、Generation Attempt/UNKNOWN、原生 Codex User Runner、模型客户端及 Owner 门禁独立复核。
- 只有显式生产授权才可执行，原始退出历史及所有 Attempt 不作改写。
- 每条旧退出由 meta/runtime/driver-remediation-<driver_sha256>.json 原子独占预留一次，记录恢复审批和修复 SHA。任何重放、缺证据或再次异常都不能自动用同一票据再次启动。
- 恢复入口只委派给正式 runtime_driver start --resume；图片生成仍走原独立授权。

入口示例（只在三个 SHA256 现场真实确认后执行）：

python scripts/storyos_codex_managed.py remediate-start <episode> --ack-real-production --expected-driver-record-sha256 <hex64> --expected-crash-log-sha256 <hex64> --expected-fixed-source-sha256 <hex64>

每次更改恢复相关代码，使用最新候选 HEAD 跑：
python scripts/storyos_autonomy_fast_test.py --slot production-regression
python scripts/storyos_autonomy_fast_test.py --slot all --stress

新类型崩溃或新修复文件必须提交另一个明确范围的审核补丁，经 RED/GREEN 和 CI 后扩大范围。不能为一般退出码 20/21/25/901 放行。