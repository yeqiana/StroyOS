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


## 2026-10-19: 审核后修复波次调用签名

真实生产经 PR111 单次恢复，最终审核 19 帧 FAIL 已转入正式 Ledger；可修复帧获得 REPAIR_AUTHORIZED，但 vision_review_executor 错误地传了 evidence= 给仅接受 findings= 的 repair_aggregator.materialize_wave，导致新的退出码 900。

本次修复添加明确命名的 repair_wave_signature 恢复类别。仅允许以下同时满足时再恢复：
- 当前真实退出原始 record SHA256、当前日志 SHA256 和对应修复源码 SHA256 逐项匹配；
- 日志确切包含 materialize_wave 不接受 evidence 关键字参数的 TypeError；
- vision_review_executor.py 的 Git blob 必须等于经过本次跨平台 CI 验证的 afbb49c80cf512312c9a0dd3043ee87e29bdea5a，且存在修正后的 findings= 调用；
- 依旧经过非零退出有界门禁、交互 Codex User Runner、MySQL/Redis、Attempt 活动与 UNKNOWN 校验；同一真实退出只能原子预留一次票据，旧票据不重置。

新入口在原参数上增加：
  --remediation-kind repair_wave_signature

普通 start/watchdog 继续拒绝所有非零退出。每次迭代必须 RED→GREEN、production-regression、all --stress、Story Gates (Windows/Ubuntu) 和 Qodana 通过再部署。


## 2026-10-19：已落账审核的 rc=4 一次性恢复

经过 PR #113 原生 Runner 修复，正式 NextAction（只读重新计算）已确认：MATERIALIZE_REPAIR_WAVE，executor=CODEX_VISION，auto_recoverable=true，hard_stop=false。旧 Driver rc=4 来自 PRODUCTION 后置质量门禁失败，不能混用此前针对 rc=900 RuntimeError 的审计入口。

新恢复类别 --remediation-kind reviewed_repair_handoff 仅允许以下全部成立：
- 当前历史 Driver EXITED/pid=0/DEAD/rc=4，原 Driver record 与当前真实日志逐字节 SHA256 匹配；原始日志必须包含确切 DRIVER EXIT rc=4 终止行。
- 已部署 next_action.py Git blob 必须固定为 PR #113 CI 通过的 e53550f3bd030aafe9c019f9ce761892f036d0cf，vision_review_executor.py 必须固定为 124fd436ce343e4c85fcb07e98514d0606b4c034。
- 同一正式 CODEX_MANAGED 运行环境下，官方 next_action.py show 动态投影必须返回 MATERIALIZE_REPAIR_WAVE + CODEX_VISION + attempt=1 + 可恢复 + 非hard_stop + 非空真实帧集合。重新读 Driver 和 NextAction 依旧完全一致后才可领取一次性票据。
- 独立 MySQL Stage、User Runner、CLI、Generation Attempt active/UNKNOWN 前置准入全部通过，原 Driver 没有存活进程。
- 每条 rc4 历史只允许一个独占 O_EXCL 审计票据；再次失败不能用旧票据重试。任何其他 rc4、尚未验证的审核、或只有 NEEDS_USER 动作均不许通过。

显式生产入口（所有 SHA 取自当前只读证据，绝不从旧会话猜测）：

python scripts/storyos_codex_managed.py remediate-start <episode> --remediation-kind reviewed_repair_handoff --ack-real-production --expected-driver-record-sha256 <sha256> --expected-crash-log-sha256 <sha256> --expected-fixed-source-sha256 <sha256>

原有两个 rc900 类别、普通 start 与 Watchdog 硬门禁保持不变。新测试纳入永久 production-regression，必须 latest HEAD all --stress、Windows/Ubuntu Story Gates、Qodana 全绿后部署。


## 2026-10-19：13个Final Semantic修复帧的原生图片工具能力门禁

PR#114 正式回归生成了 repair-wave-1.json，13 帧修复提示词与队列记录全部持久化。
真实 image_scheduler 调用却在尚未取得任何新 MySQL 图片 Attempt 时，因
LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN 阻断全部 13 行，正式 Driver rc=22。
用户在交互Windows用户登录 Codex 只是认证，不是图片工具能力已经验证。

新生产入口 production_native_repair_pilot.py 只用于《失物归还的那扇门》
本次冻结的 repair-wave-1、且仅限源最早的 Frame02 单帧。要求：
- 当前 MySQL Stage VISUAL_CALIBRATED、CODEX full_auto/dag、账号路由、本地数据库；
- 真实队列精确13个预调度 UNKNOWN 阻断 repair 行，其余12行保持 blocked；
- 第一轮完整审核原始文件 SHA 与不可变修复计划回执完全一致；
- 第一帧原始候选 PNG SHA 与当前 Ledger、修复计划源哈希一致；
- 修复帧队列 ID、source_generation_key、source_artifact_sha256、修复prompt fingerprint 均与波次锁定；
- 第02帧已有且仅消耗原始图片 Attempt #1，MySQL 无 active / UNKNOWN，仍有一次合法 Attempt；
- 显式 --ack-real-production 后，在不占队列锁期间，用原生 Codex 执行非生图工具可见性二次验真。
  UNKNOWN不能当成SUPPORTED；无法验证则不重入。
- 复核全部权威数据后仅修改第02帧为 queued，记录单次 rearm_count 和 visibility SHA，
  其余12帧不变，不在此入口预留任何图片 Attempt。
- 真正执行图像时，Worker 再做一次新鲜原生文本工具可见性验真、比对完全一致的 visibility SHA，
  再由标准容量+MySQL Generation Attempt CAS 决定是否允许下一次真实图片生成。
- 第02帧尚未形成原生 Runner 实际图像 SHA、唯一成功Attempt回执之前，其余12帧绝不批量放行。
- 若图片 Provider 没有能力，或后端派发后结局不明，则维持 BLOCKED/OUTCOME_UNKNOWN，并人工核对。
  不允许复用这张票据、不允许把像素质量审核写为PASS。

入口：
python scripts/storyos_production_env.py episodes/_system/production_native_repair_pilot.py <episode> --ack-real-production

永久回归：
python scripts/storyos_autonomy_fast_test.py --slot production-regression
python scripts/storyos_autonomy_fast_test.py --slot all --stress

上述新入口必须基于已合并最新HEAD完成CI以及现有生产模块SHA对齐之后才能执行。
