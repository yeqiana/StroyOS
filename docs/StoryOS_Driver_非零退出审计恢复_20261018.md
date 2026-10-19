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

## 2026-10-19：原生 Codex 429 文本不等于图片 Provider 终态

PR #115 正式单帧第02修复试跑中，Windows native Codex User Runner 登录正常，
真实单Worker调度后没有图像。Codex JSONL 只有 thread.started / turn.started /
item.completed(agent_message) / turn.completed，没有可信 image_generation_call、Runner
exported PNG 或正式生图成功回执。agent_message 文本包含429，旧调度器因此归类
RATE_LIMIT_429，但真正 MySQL Generation Attempt #2 已 DISPATCH_COMMITTED，
然后记录 OUTCOME_UNKNOWN；剩余共享预算0。不能把文本错误直接解释为
Provider 明确拒绝，更不能返还可能派发的 Attempt。

新增最小预防性防护：
- image_scheduler 两条 Worker 失败事件路径都在写失败代码前查真实 MySQL
  Generation Attempt 当前索引与终态，并匹配本次队列 ID、持久 Worker 生命周期
  Attempt 索引及 generation_key。
- 属于同一次 OUTCOME_UNKNOWN 时，用 IMAGE_ATTEMPT_OUTCOME_UNKNOWN 覆盖表象
  RATE_LIMIT_429；保留原消息作为诊断证据，标记 blocked，禁止技术重试。
- MySQL不可用、原始生命周期identity不一致时，明确
  IMAGE_ATTEMPT_AUTHORITY_UNVERIFIED；不当作已验证限流允许再生图。
- 没有实际图片 Attempt / 之前独立可信 FAILED_AFTER_DISPATCH 回执时，
  不误改原有429分类，也不扩大额度。
- 不改MySQL schema或不可变历史。没有 JSONL image_generation 事件不能证明
  未调用工具，原生Runner可能未暴露该事件。成功须由可信原生工具回执和图像SHA验证。
- 历史Frame02 UNKNOWN原样保留，不直接清空/再发第三次Attempt；
  其余12帧缺少成功 native proof 时仍 blocked。

永久用例：tests/system/test_native_429_attempt_reconciliation_fence.py；
所有相关修改基于最新主线运行 production-regression 与 all --stress，
CI Windows/Ubuntu Story Gates 与 Qodana 全通过方可部署。

## 2026-10-19：生产R9探针不得丢失MySQL UNKNOWN事实

原有 scripts/storyos_autonomy_production_probe.py.inspect() 仅允许 attempt readonly
preflight 的 rc=0。然而正式表出现 OUTCOME_UNKNOWN 时，
scripts/storyos_attempt_readonly_preflight.py 正常只读返回
status=OUTCOME_UNKNOWN_BLOCKED/rc=2。原探针把权威结果丢弃，错误报
AUTHORITIES_UNVERIFIED，连历史Attempt数和UNKNOWN数量也丢失。

修复规则：允许 rc=2 作为需进一步严审的事实输入，不是可恢复/生产授权；
assess 仅接受已知只读 blocked 类别，要求对应 UNKNOWN/ACTIVE/
UNVERIFIED 资产列表非空且MySQL Stage权威有效。满足时返回
PAID_ATTEMPT_RECONCILIATION_REQUIRED 与准确计数，
may_retry_paid_attempt=false、image_generation_verified=false、sql_writes=0、
model_calls=0。缺失事实、坏状态、伪造blocked类别继续保留 AUTHORITIES_UNVERIFIED。

正式Episode的真实只读回放：preflight rc2、OUTCOME_UNKNOWN_BLOCKED、
26历史Attempt、1 UNKNOWN、0 ACTIVE；新探针正确返回待对账而不是
AUTHORITIES_UNVERIFIED。不改 MySQL、历史回执、队列或 Provider。

测试更新 tests/system/test_storyos_autonomy_r9_probe.py（已有永久 production-regression
槽位），所有相关修改使用最新合并代码跑 production-regression 和
all --stress，Ubuntu/Windows Story Gates、Qodana 全绿后再部署。

## 2026-10-19：原生 Codex 第02帧 429/OUTCOME_UNKNOWN 的线程级只读对账

经 PR#116/117 合并部署，正式 Episode「失物归还的那扇门」Frame02 Attempt#2
在 MySQL 记录 OUTCOME_UNKNOWN（全剧26历史Attempt，1未决，0活动）。
Native Codex Runner request receipt 存在，原始stdout base64 SHA-256/字节长度与
不可变回执一致，task_type=image、request_id与Generation Attempt完全对应、
唯一thread.started能与Runner thread_ids匹配。CLI rc=0，不代表生图成功。
唯一 agent_message 声称图像服务 HTTP 429，JSONL没有image_generation工具事件；
该消息不是独立Provider财务/调度终态。Runner完成时的图片导出0张、
2秒settle后0张；之后从同一用户的CODEX_HOME/generated_images唯一线程目录
再做了只读核验，仍无PNG。以上只能证明**没有可恢复的图像**，不能证明
Provider一定没有调用/收费，绝不能替代PAID_ATTEMPT_OUTCOME_UNKNOWN的结算证据。

新增 scripts/storyos_native_image_outcome_evidence.py（只读；标准env wrapper调用）
安全核查 exact MySQL Generation Key + Attempt + Queue ID + lifecycle Runner request_id、
Runner receipt stdout SHA、Codex Thread ID、仅该线程的 generated_images。
若有后落盘的有效PNG，输出 RECOVERY_CANDIDATE_NEEDS_SHA_ADMISSION
（只是原始候选，不会直接改MySQL为SUCCEEDED）。
若线程目录和图片均不存在，输出 PAID_ATTEMPT_UNRESOLVED_NO_PIXEL
（不授权重试或变更Attempt）；若任何身份/凭据路径/文件检验失败则fail closed。
任何诊断结果都没有生产授权，保持 may_retry_paid_attempt=false、model_calls=0、
sql_writes=0、image_generation_verified=false。

示例：
python scripts/storyos_production_env.py scripts/storyos_native_image_outcome_evidence.py <episode> --frame 2 --attempt 2

永久回归 tests/system/test_native_image_outcome_evidence.py，
每次相关改动随最新主线跑 production-regression 与 all --stress，
CI Ubuntu/Windows Story Gates + Qodana PASS 后方可部署。正式恢复下一付费图像Attempt
仍需明确合法额度、独立可信Provider终态证据和按项目已有治理流程的授权，
不得由CLI自然语言/rc=0/缺失PNG推断。

## 2026-10-19 原生 Codex 真生图但文字声称没得到图片的正式回归

独立真实原生Codex 0.162.1 User Runner生图一次，request_id=e74ce937dd3340eda1c1c3181fde6005，
Runner task_type=image、transport_route=native_codex，持久stdout原始SHA验证成功。
Codex JSONL仅有thread/turn/agent_message事件，文字回复说没有图片；
但Runner generated_artifacts确实保存一个1254x1254有效PNG，1,940,102字节，
sha256=827f4b89cdfae98ce35cf9e13f73ada1359fff378d1144398c6fac36b9e73b0c。

最小修复：
- codex_subscription_image.runner_verified_exported_candidate检查原生Runner
  request_id、task_type=image、native_codex、returncode=0、stdout摘要和字节长度、
  唯一thread.started与Runner thread_id相同、generated_artifacts路径属于同一线程。
- 必须仅找到一个有效且满足最小RAW尺寸的PNG/JPEG；原始候选必须验证完整图像，
  路径不逃逸，不再依赖目录mtime扫描可能串图。只有真实产物可信时，
  才能覆盖Codex的错误文字回复。没有可信回执则拒绝不当认定成功。
- 用户本地独立Canary的成功不代表Episode13旧Frame02 UNKNOWN已结算；
  旧MySQL Generation Key/预算和队列继续原样保护，绝不重发第三次Attempt。
- 尺寸仍由provider_capability.inspect与canvas_normalize归一；1254方形图可归一
  到匹配方形发布画布，不能未经原有比例许可直接用作竖屏1080x1350的正式图。

永久用例tests/system/test_native_runner_artifact_first_success.py，
纳入production-regression。每次相关代码变动基于最新代码树跑
production-regression + all --stress，GitHub Windows/Ubuntu Story Gates与Qodana全绿再部署。

## 2026-10-19 第二轮内容审核 FAIL 收敛规则统一（唯一普通 Repair Wave）

核查发现旧 production_ledger_run.cmd_review() 在普通图片已用尽普通内容返修额度时，
即使审查刚得到真实 FAIL，仍可能隐式调用
production_ledger_manage.force_pass_content_exhaustion() 将 Ledger 标记 PASSED。
旧函数只校验现有图片、候选 SHA、成功生成Attempt和基本来源契约，
但标记 visual_quality_reviewed=false，**没有审核本次 FAIL 是不是仅含可接受软问题**。
因此同一张真实失败图，经普通 Ledger CLI 路径可能被隐式PASSED，
经 frame_semantic_review（显式 prevent_exhaustion_force_pass=True）却是 NEEDS_USER。
此行为违反语义真实性/人物/物理硬缺陷不得自动通过的要求。

统一生产契约：
- 初轮有效图片 + 审核FAIL：仍只授权已有冻结预算内的一次普通内容返修。
- 二轮有效图片 + 审核PASS：Ledger PASSED，继续最终审核。
- 二轮有效图片 + 审核FAIL（无独立已验证弱通过凭证）：
  无论是 CLI直接review、局部auto_repair_enqueue或正式全帧语义审核，
  都必须收敛为 NEEDS_USER；既不伪造PASS也不触发第三轮自动图片生成。
- 只有经过**独立严格图像/审核凭证验证**的现有 Visual Lock WEAK_PASS
  通道才能低分接受（必须保留图像、SHA、画风审核记录，并排除身份、场景、
  语义、物理真实性、合同、安全等硬问题）；不能凭评论文本、候选文件存在、
  生成预算耗尽就自动赋予WEAK_PASS。普通内容二审目前没有与Visual Lock等价
  的可验证低分接受凭证，所以保持 NEEDS_USER，不能先放宽。
- 需要额外第三张候选时，继续走已有的显式用户一次例外返修授权；
  不动 max_content_repairs_per_frame=1 或 MAX_AUTOMATIC_REPAIR_WAVES=1。
- 429/超时/OUTCOME_UNKNOWN 属于技术未决，不可视作内容FAIL、耗尽低分接受的依据，
  也不因此回收或增加付费Attempt。

实现：删除 cmd_review 耗尽预算后未经审查的隐式强制PASS逻辑；
废弃旧无审核 force_pass_content_exhaustion 方法，保留其兼容导出并默认抛错，
防止绕过真实软问题审核；原显式Visual Lock WEAK_PASS、已审核PASS和用户
例外审批保持原样。不得转换、批量重写已有历史审计/图片/Attempt。
新增 tests/system/test_second_round_review_convergence.py 并加入永久
production-regression，每次相关更新用最新HEAD跑 production-regression、
all --stress、Ubuntu/Windows Story Gates与Qodana 后才能部署。
