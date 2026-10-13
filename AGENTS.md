# 项目协作规则（Codex 自动读取）

## StoryOS 前端 / UI 任务入口

涉及 Web Console、Production Monitor、Run Detail、Dashboard、Data Grid、Drawer、UI 改版、视觉精修、截图评审或“去 AI 味”时：

1. 先读取根 `DESIGN.md`；
2. 再读取 `skills/storyos-ui-design/SKILL.md`；
3. 先识别现有 Theme / Token / Shared Components，再决定 Direction / Extract / Audit / Build / Polish 模式；
4. 不得用外部 Skill 覆盖 StoryOS 已有 Design Contract、业务状态语义或 API Contract；
5. CREATE / VISUAL REDESIGN / POLISH 完成前按 `skills/storyos-ui-design/checklists/visual-review.md` 做视觉验收；
6. UI 默认目标是高密度生产控制台，不是营销页、AI SaaS 模板或赛博朋克大屏。

外部 UI Skill 只作为参考知识；吸收来源和边界记录在 `skills/storyos-ui-design/references/external-skills.md`。

<!-- STORY_OS_MULTI_EPISODE_PERMANENT_CONTRACT_BEGIN -->
## 多作品并行生产（永久正式能力）

- StoryOS 必须允许**多个不同 Episode 同时执行正式生产**；不得把系统永久改回单 Episode 全局串行。每个 Episode 保持自己的 Driver Owner、队列、Review Authority、MySQL Generation Attempt 和发布状态，严禁跨 Episode 互相改写。
- 同一 Episode 只允许一个正式 Owner/Writer；多 Worktree 并不意味着可以为同一 Episode 多开生产 Driver。
- 同一台机器、同一个 Git Common Directory 下，所有正式图片 Provider 派发**合计最多 5 张在途图片**，不是每部作品各 5 张。单帧、Codex 逻辑批量、原生 n 图片批量与直接 CLI 入口必须全部共用 `global_image_capacity.image_permits`，正式 Gateway 也必须受保护。
- 必须先获得共享容量名额，再预留或消费新的 Generation Attempt；容量繁忙、权限错误、共享锁不可用不能被解释为真实 Provider 失败，不能因此自动重试、退款、覆盖 UNKNOWN 或绕开原有预算。
- 新模型/新 Provider/新运行时加入 StoryOS 时，必须继续走统一受控的图片 Provider Gateway 或等效共享容量守卫，并更新 `tests/system/test_multi_episode_global_image_capacity.py` 相关回归。禁止恢复 OpenCodex 代理或图片转视频流程。
- 多 Episode 启动只可复用 canonical `runtime_driver`，通过 `scripts/storyos_multi_episode.py` 显式启动（需要 `--ack-real-production`）；计划和状态查询不得调用付费模型。Episode 自身的 PREIMAGE、Visual Lock、Revision、Review、Release 等门禁不得因并发能力而跳过。
- 当前保障范围是**单机、同一 Git 仓库的跨进程/Worktree**；跨主机或独立 Git 克隆在具备 MySQL/Redis 分布式租约与 fencing 验收前不得并发正式生图。共享硬上限不等于严格跨 Episode 公平调度，公平配额和真实双 Episode Canary 仍需独立验收。
- 详细设计、只读容量诊断和运维入口见 `docs/StoryOS_多Episode共享图片容量与并发边界_20261009.md`；本规则为仓库协作与防回退边界，**不是绕过任何生产门禁的授权**。
<!-- STORY_OS_MULTI_EPISODE_PERMANENT_CONTRACT_END -->


## R2 自治生产 Watchdog / 每轮极速验证

- 原生 Codex 无人值守恢复仅走 `scripts/storyos_autonomy_watchdog.py` → `storyos_codex_managed.preflight` → canonical `runtime_driver start --resume`，不得增加第二套调度器或绕过旧 Gate。
- Watchdog `plan` 永远只读；`once`/`watch` 必须有明确 `--ack-real-production`；不得自动首次启动新 Episode。只允许确认已死/干净退出的已有 Driver，非零退出、UNKNOWN、活动 Attempt、人工门禁或在线 Writer 来源不确定时必须停在诊断。
- 同 Git Common Directory、同 Episode 的恢复使用跨进程 OS Lock、两次只读权威核验和崩溃前原子落盘的预算 journal；默认 24h 内最多 2 次、300s 冷却。它不是 MySQL/Provider Attempt Authority；跨主机仍不可宣称 Fencing 已验收。
- **每个四槽增量变更必须执行对应 `python scripts/storyos_autonomy_fast_test.py --slot watchdog|budget|authority|e2e`，合并前执行 `--slot all`，整体交付前执行 `--slot all --stress`，失败不得伪装为通过。**
- 文档见 `docs/StoryOS_R2_自治Watchdog_四槽极速验收_20261013.md`。

## R3 原生 Codex 安全自治推进

- Windows 自恢复的计划任务必须由 `storyos_autonomy_carrier.py` 显式授权，在可信交互账号和正式主工作区安装；不得从临时 Worktree 登记可永久存在的任务，不得覆盖或删除不匹配的计划任务。
- 单 Episode Writer 锁必须使用原子 NX+TTL、持有者令牌校验和 Redis Lua compare-and-expire / compare-and-delete；无原子能力时拒绝，不允许 get-then-set 回退、无令牌释放。**Owner Token 不等于跨主机单调 Fencing，未接入所有生产写端前不可声称全局租约完成**。
- 正式单帧 Canary 先走 `storyos_autonomy_canary.py plan` 和已有 Frame01 证据入口；EVIDENCE_ONLY 绝不构成生图授权，不得追加独立图像 Provider 派发。
- **每槽修复须有 RED → GREEN 极速验证**：`--slot carrier|writer|canary|autonomy-integration`；四槽联合 `--slot all`；完整验收 `--slot all --stress`。详见 `docs/StoryOS_R3_四槽自治Carrier_Writer_Canary_极速验收_20261013.md`。

## R4 生产派发前二次 Fence / 四槽极速验收

- 原生 Codex 真实图片派发在 canonical Generation Attempt `DISPATCH_COMMITTED` 后、Provider 网络调用前，必须通过新的 MySQL lease/fencing read-only 复核；批量每帧验证，过期不执行付费调用、不退款已消费 Attempt，不另开 Provider/视频链路。
- Watchdog 的两次准入必须比较 Codex 运行路由与正式 MySQL、创作、视觉权威；任何漂移 fail-closed。Windows 持久载体的工作目录、登录触发器/账号、单实例设置及启用状态必须验证，不能把同名任务视为可信。
- Frame01 Canary 需要双次只读 Native Preflight 与 Episode 证据身份一致，不可把 EVIDENCE_ONLY 当作生图权限。
- 每槽需 RED→GREEN 极速测试：`python scripts/storyos_autonomy_fast_test.py --slot dispatch-fence|carrier-integrity|frame01-fence|r4-integration`；合并 `--slot all`、完成 `--slot all --stress`，见 `docs/StoryOS_R4_四槽自治二次Fence与极速验收_20261013.md`。

## R5 原生 Codex、历史治理、回执 UNKNOWN 与极速测试

- 退役清理仅可用 `scripts/storyos_retired_worktree_gc.py` 先 `plan`/ `branches-plan`，再明确 `--ack-retired-cleanup` 执行；历史 Worktree 须合并到本地+远端主线、无未追踪/未提交文件、72h 以上、无运行进程、来源于受控直接子目录。严禁 force、`git branch -D`、误删 archive、跨库目录和非本仓数据。
- Provider 已返回但持久化回执失败时归类 `OUTCOME_UNKNOWN` 而非可重复普通失败，Generation Attempt 已消耗绝不退款；原生单帧和批量一致。
- `scripts/storyos_autonomy_native_ready.py` 只读检查本机 Codex CLI 参数和交互账号 Runner 授权上下文；`NATIVE_AUTH_CONTEXT_READY` **不能作为真实模型调用能力或生产授权**。
- 第五轮各槽每推进一次必须跑 `python scripts/storyos_autonomy_fast_test.py --slot retirement|provider-receipt|native-login|r5-integrated`，最后跑 `--slot all` 和 `--slot all --stress`；见 `docs/StoryOS_R5_四槽治理_原生Codex与极速验收_20261013.md`。

## R6 四槽继续推进 · 原生 Codex / 结果 UNKNOWN / 安全清理

- 原生 Codex 登录已可经 `storyos_autonomy_native_ready.py` 只读核查，但需要在 Frame01 证据前后双次验证；`EVIDENCE_ONLY` 不授权付费调用。禁止独立 Provider 和 OpenCodex 旁路。
- Provider `TimeoutError`、`ConnectionError`、`subprocess.TimeoutExpired` 在实际进入派发后是**可能付费但结果不确定**：保留 MySQL Generation Attempt 消耗，必须记录/保守处理 UNKNOWN，不得自动重试；批量已成功记账的帧不得错误改写。
- 历史本地分支清理需要在二次主线合并检查前后对引用 SHA 重新核对；`inf`、`nan` 与无效时间戳不得清理，Worktree 没有全部权威证据就保留。不得使用 force / `-D`。
- 每次修改对应槽必须 RED→GREEN 极速测试：`python scripts/storyos_autonomy_fast_test.py --slot gc-fence|provider-timeout|codex-frame01|r6-e2e`，四槽一起执行 `--slot all`，全轮结束执行 `--slot all --stress`。参见 `docs/StoryOS_R6_四槽续推与极限测试_20261013.md`。

## R7 原生 Codex CLI 同路由及 Provider 最后证据门禁

- 清理老分支必须经 `storyos_retired_worktree_gc.py branches-plan`；只对本地/远端均已合并、已解除 Worktree 占用、72h 以上的临时分支执行 Git 原子 ref compare-and-delete；分支提交变动/活跃签出时拒绝。绝不 `--force` 或 `-D`。
- 图片 `image_generation_gateway.py` 的单帧与批量 post-commit MySQL Fence 验证，必须明确返回 `True`；拒绝 False/None/不完整批量提交，绝不可越权进入付费 Provider `call()`。
- Frame01 的 `EVIDENCE_ONLY` 还需要检查 CLI 与交互用户 Runner 的版本和可执行文件指纹完全一致；仅登录或找到 `codex` 命令都不是付费生图许可。只读检查不暴露用户路径、证书或密钥。
- 本轮每次改动 RED→GREEN 的极速入口 `--slot gc-atomic|gateway-proof|native-route|r7-closure`；联合 `--slot all`；整轮 `--slot all --stress`。详见 `docs/StoryOS_R7_四槽原子退役与Codex同路由验收_20261013.md`。

## R8 Frame01 专用回收分流与 M00 作品级四帧校验

- `storyos_native_frame01_preflight.py` 验证的是《五十亩山地之后》旧 Attempt 的严格 UNKNOWN 回收，禁止把它误当全体新作品的通用首帧准入。普通作品通过 `storyos_autonomy_canary.py plan` 独立核对 MySQL Stage/Attempt、Visual Lock、原生 Codex 只读证据，绝不凭预检直接发起付费图片生成。
- M00 四帧必须按四种固定角色与首帧=1 校验；后三帧在不同作品中可选不同的 1–20 编号，但必须互不重复。原有 1/16/8/17 仅为旧测试样例，不能作为所有分镜的统一强制帧号。
- `storyos_codex_managed.py plan` 的 `READY_TO_START` 仅代表 DAG 可启动；新增 `production_admission.image_ready=false` 和图片阻断原因用于明确区分。真实 Provider 许可仍由正式 Gateway/Attempt/Pixel 权威决定。
- 文件 Episode Stage 只是本地快照，与 MySQL 冲突时以 MySQL 为准；`storyos_stage_drift_readonly.py` 只读报告差异，不修库、不改文件。
- 四槽每次推进分别跑 `--slot frame01-real|native-image-readiness|stage-drift|r8-integration`；最终 `--slot all --stress`，见 `docs/StoryOS_R8_四槽Frame01真实准入与极限验收_20261013.md`。

## R9 真实生产授权 · 原生 Codex、Watchdog SID 与极速回归

- 经明确授权的真实生产只能从主工作区 `storyos_codex_managed.py start --ack-real-production` 进入 canonical Driver，不能直接重复派发裸 `codex exec` 图片。一个真实 Driver 曾处于 `RETRY_WAIT` 并以 rc=3 退出，MySQL Generation Attempt=0，不能谎称已出图；先修复正式审核 WORK shadow 挂起。
- 在 `CODEX_MANAGED` 文本路由下，历史 `*-critic-shadow` 是旁路/非权威 REVIEW 请求，只可从待执行队列过滤、不能改动历史审计；正式 `story-semantic` 必须继续审核并产生 SHA 绑定的正式 PASS/FAIL 回执。
- Windows Task Scheduler 的 principal 显示名可能与交互用户不同；仅 Windows SID 一致（加可执行文件、参数、工作目录、用户 Logon、IgnoreNew、Enabled 全验证）才能判为 `INSTALLED`。注册完成后必须再查任务，未证实则 `REGISTERED_BUT_UNVERIFIED`，不可擅自自动续跑。
- 用 `storyos_autonomy_production_probe.py` 在真正 runtime.env 下读取 Driver/MySQL Stage/Attempt，区别心跳、历史状态和真实 Provider 图片。带 UNKNOWN 的 Attempt 禁止自动新付费请求。每槽极速 `--slot real-canary|watchdog-user|mysql-receipt|r9-integrated`，完工 `--slot all --stress`。参见 `docs/StoryOS_R9_授权生产直连与四槽回归_20261013.md`。

## R10 · Story Critic 有界尝试权威与真实生产审计

- `CREATIVE_STORY` 的 DAG `REUSED` 调度次数不等于正式审核尝试次数；它在旧 Episode 上可达 161+，不能继续传给仅接受 1/2 次正常尝试的 `story_review.py run-critic`。`story_review_attempt_admission.py` 必须使用现存审核 lifecycle + 正式 Review 权威判定，任何超限重试先拦截。
- 如果正式 `story-semantic` 请求出现 `FINALIZED` 但官方 Review 权威不存在，返回 `FINALIZED_REVIEW_WITHOUT_CANONICAL_PROOF`，Driver 使用 `HUMAN_REQUIRED` 非技术重试分支，禁止伪造 PASS 或自动再次发起模型。
- `storyos_story_review_readonly.py` 是原生环境、MySQL Stage 与真实审核请求的双核验只读诊断；`storyos_autonomy_production_probe.py` 的 `NEVER_STARTED` 只能解释为丢失 Driver runtime 证据，不能推断首次启动未发生。`unverified_status_assets` 与 UNKNOWN paid receipts 必须人工/权威对账。
- R10 四槽独立极速：`--slot story-critic-authority|driver-lifecycle|paid-attempt-proof|r10-integrated`；最终 `--slot all --stress`；详情 `docs/StoryOS_R10_真实StoryCritic权威与四槽闭环_20261013.md`。

## R11 真实生产：原字节迁移可修复，rubric SHA 漂移禁止旧 PASS 冒充新审核

- `storyos_manifest_relocation.py` 对旧 Episode 文件路径修复必须匹配 69e7a2a8 Git blob old/new 身份，以及独立 Critic 请求冻结 story/board SHA。生产版只允许在无活跃 Driver/用户明确授权后修复 release-manifest.artifacts 三个原字节路径，不能改动 Reviewer、故事、分镜、MySQL 或图片。
- 旧 `story-semantic` 官方 Review 文件即使存在且原 payload/provenance 校验通过，如果第 2 次冻结来源（例如制作规范）SHA 不同于当前正式规范，`storyos_relocated_review_recovery.py` 必须返回 `CRITIC_SOURCE_SHA_DRIFT`，不能从历史 FINALIZED 拼装新的 PASS；需独立真实审核与当前 Policy Authority。
- `storyos_autonomy_resume_admission.py` 要同时核对 MySQL Attempt/Driver Stage、Review 生命周期与迁移证据；任意 UNKNOWN 或正式 Critic 缺失不得重复付费或自动声明准入。M00 像素和首帧生图仍须 canonical Gateway/Attempt + 五图额度许可。
- 四槽 RED-GREEN 秒速回归：`--slot review-relocation|review-restore-guard|frame01-after-review|r11-closure`，最终 `--slot all --stress`。见 `docs/StoryOS_R11_真实迁移证据与四槽验收_20261013.md`。

## Story OS 当前执行入口

涉及 `story` 分支的选题、分镜、出图、字幕、审核、发布、复盘任务，Codex 必须先读取仓库根目录 `START_HERE.md`，再读取 `SKILL.md`。

每次流程先读取并校验 `config/storyos.yaml`，再按 `config/index.yaml` 的最小读取集工作。当前产品版本仍从 `story_os_manifest.json` 读取；不要在 Agent 入口另维护一份版本号。

- `AGENTS.md`：Codex 自动入口与仓库协作规则。
- `SKILL.md`：Story OS 执行协议。
- `standards/制作规范_正式版.md`：唯一创作规范权威。
- `episode_state_persistence`：唯一阶段读取/更新入口；`mysql` 模式以 MySQL 为阶段权威，不回退本地 JSON；`dual` 优先 MySQL 并按兼容规则回退；`json` 模式使用 `meta/episode-state.json`。
- `meta/story-gates.json`：门禁证据，不保存 stage，不得成为第二状态机。


唯一权威规范：[standards/制作规范_正式版.md](standards/制作规范_正式版.md)

传播评分与发布后数据诊断按 [standards/抖音推流评分与发布后漏斗规范_V1.4.md](standards/抖音推流评分与发布后漏斗规范_V1.4.md) 执行；该文件仅解释主规范 8.4/8.5/12.4/12.5，不建立第二权威，冲突时以主规范为准。V1.3 新增发布时间分层实验与 1h 冷启动快照：1h 仅用于时间实验，不替代主规范正式 6h/24h/48h/7d 验收窗口。

生产真实性、共享画风和字幕人话化按以下从属执行细则：
- [standards/风格锚点_MP4_网吧_流水席_旧数码_V1.2.md](standards/风格锚点_MP4_网吧_流水席_旧数码_V1.2.md)
- [standards/真实性与共享风格锚点规范_V1.1.md](standards/真实性与共享风格锚点规范_V1.1.md)
- [standards/字幕人话化与声音卡规范_V1.1.md](standards/字幕人话化与声音卡规范_V1.1.md)
- [standards/生产引擎与画幅规范_V1.2.md](standards/生产引擎与画幅规范_V1.2.md)

这些从属细则均不建立第二权威；冲突时以 `standards/制作规范_正式版.md` 为准。M00「现实生活纪实母版」在用户未指定时默认启用；MP4、网吧、流水席、误入小镇只作为校准来源。显式视觉体系可覆盖，且年代/采集设备物理真实性永远高于母风格质感。


<!-- STORY_OS_RUNTIME_REQUEST_P0_AGENTS_BEGIN -->
## Runtime Request P0｜一句话入口

涉及新篇全自动任务时，Codex 必须先把用户自然语言编译/记录为 Runtime Request，再进入 Story OS 创作流程。Runtime Request 只表示“用户要什么、怎么执行”，不得提前决定高潮帧、impact、天气或 Visual Lock 帧。

标准规则：

- 用户不传剧情：`auto_create`。不得反问用户补剧情；必须由 Story OS 自己发散候选、通过 Concept Ambition、写完整 Story。
- 用户说“剧情大概是…”：`user_seed`。必须强化和重写，禁止把用户原文直接拆成 20 张。
- 用户说“必须保留/结尾必须”：`core_constraints`。硬约束必须保留，其他结构允许优化。
- 只有用户明确说“剧情已经定了/不要改剧情”才使用 `locked_story`。
- 用户不写 image：默认模型和质量必须读取 `config/storyos.yaml:models.profiles.image_payload`；正式生产不得静默降级 Quality。
- 用户显式指定 image：强绑定，禁止静默替换。
- 当前 V2.1 Visual Lock 永远按 4 张口径执行；“3 张校准”只允许出现在明确 legacy-only 的兼容代码/历史说明中。

请求可先写入 `runtime/requests/<request_id>.json`，Episode 创建后绑定到 `<episode>/meta/runtime-request.json`。绑定后的请求默认不可变；执行状态写 checkpoint/observability，不回写 Request。
<!-- STORY_OS_RUNTIME_REQUEST_P0_AGENTS_END -->

<!-- STORY_OS_RUNTIME_DAG_REFACTOR_AGENTS_BEGIN -->
## Runtime DAG / Resume / Quota

- 新篇有 `meta/runtime-request.json` 且 `runtime.execution_mode=dag` 时，优先由 `runtime_dag.py` 分段调度，不再默认启动单个全程大 Codex supervisor。
- Runtime DAG 不是第二状态机；每个 Step 最终必须通过 `episode_state_persistence` 当前配置的 canonical 阶段权威，以及 validate/machine/evidence gates。
- 中断恢复先验证已经到达的目标阶段；证据有效则 REUSED，不为“保险”重做昂贵 Step。
- 图片 worker pool 只复用 Python 进程/模块，不复用跨帧 Codex 对话上下文。
- Quota observability 仅记录真实日志计数或用户明确提供的 `/status` 百分比，不允许推测 Plus 剩余额度。
- 本地 StoryOS 生产环境由 git-ignored `.storyos/runtime-launcher/runtime.env` 提供实际数据库/缓存连接参数。WebCodex 或终端单独运行验证/生产 Python 脚本时，必须通过 `python scripts/storyos_production_env.py episodes/_system/<script>.py ...` 加载现有运行配置，禁止把 `config/storyos.yaml` 的 localhost 默认值误当成正式生产库，也不得打印或提交凭据。
<!-- STORY_OS_RUNTIME_DAG_REFACTOR_AGENTS_END -->

<!-- STORY_OS_RUNTIME_PERFORMANCE_PACK_AGENTS_BEGIN -->
## Runtime Performance Pack

- Image Scheduler 使用 continuous first-completed 调度，image max workers 上限为 5，Ledger 仍单写。
- Scoped Codex 优先使用 `meta/runtime/execution-capsules/*.json`；Capsule 是 derived cache，冲突时源规范优先。
- 高风险 rolling review 只能输出 PASS_PREVIEW / REPAIR_NOW / UNCERTAIN；PASS_PREVIEW 永远不是最终通过。
- Prompt Package 是 derived cache，Frame Contract/scene SHA 漂移时必须重新编译。
- Provisional Release 只能写 runtime 临时草稿，不得改 release-manifest / snapshot / stage。
<!-- STORY_OS_RUNTIME_PERFORMANCE_PACK_AGENTS_END -->

<!-- STORY_OS_CHARACTER_ENTRY_POOL_AGENTS_BEGIN -->
## Character / Entry Pool

- CREATIVE_STORY 前准备 `meta/character-contract.json`；它是 Story Build Input Contract，不是新 Stage。
- 默认主角从 2004–2010 或 2020年代二十来岁普通青年池选择，可单人、两人、4–5人朋友团。
- 第一人称 POV 也必须固定人物锚点；小团体固定 P01/P02...、年龄、性别、衣着。
- 进入异常优先旅行、返乡、聚会、喝酒/游戏、挑战、废弃场所、户外、自驾、生活化工作/课题/科考、偶然绕路。
- 抢修员、电工、维修工、警察、记者、调查员、专业探灵人、秘密异常研究人员不得作为默认主角发动机。
- 工作/科考只能解释“为什么来到这里”，不能让专业技能成为解决异常的剧情捷径。
- Story Lock 前 Character Contract 必须 LOCKED，NO-ANOMALY TEST PASS，ORDINARY_PERSON_SCORE >= 75。
- Character Contract 绑定 Resolved Frame Contract；后续生图不得随意漂移人物。
<!-- STORY_OS_CHARACTER_ENTRY_POOL_AGENTS_END -->

<!-- STORY_OS_RUNTIME_OPTIMIZATION_R2_AGENTS_BEGIN -->
## Runtime Optimization R2

- `preproduction_only`：完成全部非图片前期资产并生成 `meta/preproduction-handoff.json`；禁止调用 image_generation。
- `image_continue`：先校验 Handoff Authority SHA；Story/Storyboard/Character 为冻结权威，禁止重写；Derived Cache 可重建。切换模式写 `meta/runtime-execution.json`，不得覆盖 immutable runtime-request。
- Shared Resource Library 只复用参考/描述，不默认复用旧集最终成片。
- Visual Lock 使用 1+3：baseline PASS 后，worst/first anomaly/high-impact 才可并行。
- RELEASE 必须先 resolve intro policy；四类开头是结构参考，不是机械模板。
- 标题只生成 1 个内部候选；不作为 PUBLISH_READY 必填项。
- `.storyos_cache/` 为本地全局缓存，不入 Git，不是权威资产。
<!-- STORY_OS_RUNTIME_OPTIMIZATION_R2_AGENTS_END -->

## V2.6.1 Product-Runtime-First Multi-Runtime 执行路由

涉及 story 分支任务时，先读 `config/storyos.yaml` 和 `config/index.yaml`，再读 `START_HERE.md`，并按 Runtime Contract 自动路由。

默认优先级：

1. `WORK`：ChatGPT/Work + DevSpace，默认路径；
2. `CODEX`：仅显式选择时启用；
3. `WEB`：无本地工作区能力时的产品运行时。

- ChatGPT Work：`runtimes/WORK.md`
- 显式本地 Codex：`runtimes/CODEX.md`
- 普通 ChatGPT Web：`runtimes/WEB.md`

**本机存在 `codex.exe` 不再自动推导整个 Runtime=CODEX。** 唯一生产模式入口为 `production.mode`（默认 `COLLABORATIVE`）；执行器分别配置在 `execution.workspace.provider`、`execution.image.executor`、`execution.vision_review.executor`。宿主不可用时不得自动改走本地 Codex。只有显式设为 `CODEX_MANAGED` 或单次设置 `STORY_OS_PRODUCTION_MODE=CODEX_MANAGED` 才启用整条 CODEX Runtime；旧 `STORY_OS_RUNTIME` 仅保留兼容/调试用途。图片控制模型与生图模型分别读取 `config/storyos.yaml:models.profiles.image_controller` 和 `models.profiles.image_payload`；生图质量固定为 `high`。图片生成功能仅允许 Codex 原生 ChatGPT/Codex 通道，不得自动切换到 OpenCodex（10100）代理，且无真实会话工具能力证明时不得消耗生图 Attempt。Story、PREIMAGE、Critic、Review、Gate、Release 不得因图片执行器而交给 Codex full-auto。

Runtime DAG 使用通用 `scoped_model`；WORK/WEB 的非图片步骤通过 `product_runtime_adapter.py` 暴露宿主动作，CODEX 整体 Runtime 才使用 `scoped_codex_worker.py`。图片 Scheduler 读取 `execution.image.executor`（旧 `runtime.image_execution_runtime` / `STORY_OS_IMAGE_RUNTIME` 暂保留兼容）。宿主请求使用 `meta/runtime/host-requests/<request_id>.json` 保存不可覆盖历史，正常等待宿主执行记为 `HOST_WAIT`；Product Review 使用 attempt-scoped request。Concept/Story/Legacy Visual 独立评审允许 `WORK_ISOLATED / WEB_ISOLATED / CODEX_ISOLATED`，但都必须 fresh + source-SHA-bound。

Codex 不再被全局限制为“只能生成网页交接单”。当用户**明确选择 CODEX Runtime**且当前 Codex 原生工具能生成/编辑图片和保存文件时，应直接按 CODEX runtime 执行；缺媒体能力时才降级 checkpoint/handoff。

全自动授权后：当前 V2.1 统一先完成 4 张 Visual Lock（ordinary baseline / worst condition / first anomaly / high-impact admission），再进入 Batch；每帧最多一次内容返修；已通过且 SHA 未漂移资产必须复用；自动审查不得冒充用户亲眼审核。

<!-- STORY_OS_V2_1_AGENTS_BEGIN -->
## V2.1 Concept Ambition / Image-first

V2.1 新篇不得直接从一个稳妥题目开始写完整故事。先生成 8–12 个候选；不因现实不存在、异常太大或世界规则太怪而提前降级；每个候选先定义 Cover/Mid/Climax；至少 3 个候选进入 A4/A5；运行独立 `concept_ambition.py run-critic`，只允许基于 Concept Voltage ≥80 且无字测试全 PASS 的 selected_id 进入 Story/Storyboard。旧 2.0.x Episode 不追溯补造该 evidence。
<!-- STORY_OS_V2_1_AGENTS_END -->

<!-- STORY_OS_V2_1_PHASE3_AGENTS_BEGIN -->
## V2.1 Phase 3 Environment / Anomaly Impact

Story Lock 后先完成环境合同与逐帧 impact 设计，再进入 Visual Lock。天气不得滤镜化；高冲击异常不得只靠字幕说“更大”，必须在像素中通过尺度参照和前后级差成立。
<!-- STORY_OS_V2_1_PHASE3_AGENTS_END -->

<!-- STORY_OS_V2_1_PHASE4_AGENTS_BEGIN -->
## V2.1 Phase 4 Resolved Frame Contract

Environment / Impact Contract 通过后先编译全部 Frame Contracts，再进入 Visual Lock 校准。正式生图不得只依赖临时 scene prompt；scene prompt 与 Resolved Frame Contract 分层存在，后者是当次生产的完整机器合同。若合同 SHA 漂移，旧 generation attempt 不得直接冒充当前合同。
<!-- STORY_OS_V2_1_PHASE4_AGENTS_END -->

<!-- STORY_OS_V2_1_PHASE56_AGENTS_BEGIN -->
## V2.1 Phase 5/6 Execution

Visual Lock 不再只看三张“风格图”：先 baseline，随后 worst condition / first anomaly / high-impact admission 三张可并行，最后统一 Critic。正式 Batch 不允许手工连续调用 image backend 形成隐式串行，应建立 production queue 并由 `image_scheduler.py run --max-workers 5` 执行。Scheduler 返回 PARTIAL 时先处理/重试技术失败，不得把缺帧当 PASS。
<!-- STORY_OS_V2_1_PHASE56_AGENTS_END -->

<!-- STORY_OS_V2_1_PHASE78_AGENTS_BEGIN -->
## V2.1 Phase 7/8 Execution

在 Visual Lock 前启用 Fast Scout，使 Scheduler 对高风险生成结果并行做早期像素 triage；REPAIR_NOW 只影响该帧与依赖链。不要把 PASS_FAST 写成正式通过。Release 完成 release_preflight 后必须 build+verify Final Candidate Snapshot，再记录 release_lock/推进 PUBLISH_READY。Delivery 只能消费 verified Snapshot。
<!-- STORY_OS_V2_1_PHASE78_AGENTS_END -->

<!-- STORY_OS_V2_1_PHASE910_AGENTS_BEGIN -->
## V2.1 Phase 9/10 Closure

新故事开题前先 `account_learning_index.py rebuild --limit 5`，只把账号历史数据当 evidence。真实发布后用 `post_publish_review.py mark-published` 推进 PUBLISHED；之后按实际后台数据 record 6h/24h/48h/7d。48h 后 `complete` 才可推进 DATA_REVIEWED。不要改冻结的 release-manifest，也不要手写假数据。
<!-- STORY_OS_V2_1_PHASE910_AGENTS_END -->

## Episodes 机器状态与发布清单

> 当前 Story OS：阶段读取与更新必须走 `episode_state_persistence`；MySQL 模式由数据库提供阶段权威，`episode-state.json` 仅在允许的模式下作为文件状态；`story-gates.json` 仍只记录门禁证据，不得保存或覆盖 stage。

1. 新建具体剧集时，按 [`episodes/_system/README.md`](episodes/_system/README.md) 初始化 `meta/episode-state.json`、`meta/release-manifest.json` 与 `meta/story-gates.json`；历史剧集不批量伪造状态，只在重新进入制作/发布/复盘时迁移。
2. 机器状态固定为：`IDEA_LOCKED → STORYBOARD_LOCKED → VISUAL_CALIBRATED → PRODUCTION_PASSED → PUBLISH_READY → PUBLISHED → DATA_REVIEWED`。
3. 阶段权威由 `episode_state_persistence` 的当前存储模式决定；README 文案冲突时修 README，不得为迎合旧文案绕过持久化接口或直接覆盖数据库/JSON。
4. 正向推进必须使用 `episodes/_system/episode_state.py transition`，只能相邻前进。脚本会先用 `validate_episode.py --target` 验收目标门禁，失败时不得手工越级修改 JSON。
5. `release-manifest.json` 只记录实际发布版本事实，不替代分镜、制作规范或数据报告；路径统一使用仓库根目录相对路径。
6. `PUBLISH_READY` 前必须完成制作门禁与九项传播卡，并写明 `publish_decision=go`；`conditional/not_recommended` 若仍发布必须填写 `decision_note`。
7. 发布图可继续被 `.gitignore` 排除；完整张数/封面存在性校验在本地工作区执行。只检查 Git 元数据时才使用 `--metadata-only`。

## 提交规则

1. **系列剧本的母版图必须提交 Git。** 凡被 `episodes/**/meta/series-character-identity.json` 引用的 `group_identity_asset` / `primary_asset` / `supporting_assets`，都是系列身份权威的像素锚点，必须入库并保持 SHA 绑定一致；它们在本地存在但未提交，等于让 fresh clone 拿到悬空身份绑定。落盘沿用 `episodes/**/assets/characters/`，不搬迁既有已冻结证据引用的文件。
   - 校验：`python episodes/_system/contract_sync.py` 会对未入库的系列母版图 FAIL。不得用「像素资产默认不入 Git」把母版图留在本地。
2. 允许提交 git 的图片/大文件仅限以下两类：
   - 角色参考图：`episodes/**/assets/characters/`（含上一条的系列母版图）
   - 竞品与账号截图：`research/competitors/`、`research/account/`
3. 其他图片、视频、音频、压缩包一律禁止提交，已由 `.gitignore` 默认忽略，包括：
   - 各集 `images/`、`publish/` 成片
   - `assets/` 下 frames、subtitled、references、shenshi、materials 等中间资产
   - 发布包 zip、`workbench/` 中间处理资产、`.playwright-cli/` 截图
4. 新增大文件前先 `git status` 确认只出现白名单文件；可用 `git check-ignore <文件>` 验证是否被忽略。
5. 已误提交的非白名单文件用 `git rm --cached` 移出索引（保留本地），不要删本地文件。

<!-- STORY_OS_V1_8_AGENTS_BEGIN -->
## V1.8 默认视觉路由

Codex 若未收到用户明确画风/质感指令，必须先解析 `M00 / 现实生活纪实母版`，再按本集真实性卡决定实际设备表现。MP4、网吧、流水席、误入小镇只是校准来源；不得把“默认 M00”误解成“所有作品都必须旧低清”。

当前推进统一调用稳定外部名 `evidence_gate.py`；`v18_gate.py` 只保留为历史兼容实现。Story/Visual Approval provenance、最新 Text Audit 与 Release 证据都不得漂移。
<!-- STORY_OS_V1_8_AGENTS_END -->

<!-- STORY_OS_V2_0_1_AGENTS_BEGIN -->
## V2.0.1 Codex 可执行全自动

在 CODEX runtime 且用户明确要求“全自动执行 / 做到最终交付”时，优先使用 `python episodes/_system/story_os.py run <episode_dir> --full-auto` 或遵循同等底层流程。不要再把 CODEX runtime 降级成只写交接提示词。

自动返修必须记录为 `delegated_auto_review`；正式 Story/Visual/Release 的 `user_approved` 只能来自真实直接批准。外部证据门禁统一调用 `evidence_gate.py`。
<!-- STORY_OS_V2_0_1_AGENTS_END -->

<!-- STORY_OS_V2_0_2_AGENTS_BEGIN -->
## V2.0.2 Production Closure

- `story_os.py run --full-auto` 的成功条件是 postflight COMPLETE，不是 Codex worker rc=0。
- 正式图片用 `codex_subscription_image.py generate-for-frame`；raw 与 exact-canvas candidate 分离。
- full-auto self review 后用 `delegated_approval.py record` 锁 Story/Visual；不得伪造 `--user-approved`。
- Evidence Gate 接受 direct_user_review 或已授权的 delegated_auto_review。
- delegated delivery 只接受真实 publish 资产，禁止 approved fallback。
<!-- STORY_OS_V2_0_2_AGENTS_END -->
<!-- STORY_OS_V2_0_3_4_AGENTS_BEGIN -->
## V2.0.3.4 Incremental Workspace

- 全自动执行前先运行 `incremental_closure.py plan`；已有有效 SHA-bound PASS 证据不得无条件重跑。
- Production 结束后使用 `incremental_frame_review.py review`，由它自动选择 NOOP / PATCH / FULL。
- PATCH 只看 dirty roots + 必要邻帧；Story/Storyboard/Visual Contract 漂移或 dirty >25% 自动 FULL。
- 新生产媒体必须写入 `<episode>/media/`；交付写入 `<episode>/release/`。图片/视频/ZIP 保留本地，Git 只保存路径与 SHA 索引。
- 不得删除被 `.gitignore` 忽略的旧媒体来“整理目录”；迁移必须通过 `media_workspace.py` 的 copy→SHA verify→reference rewrite→remove-old 流程。
<!-- STORY_OS_V2_0_3_4_AGENTS_END -->

<!-- STORY_OS_V230_AGENT_RUNTIME_BEGIN -->
## Story OS V2.3 Agent Runtime

执行链：
`Raw Request → Intent Resolver → immutable Runtime Request → Request Router → Workflow DAG → Tool/Model Execution → Trace/Evidence`

- 阶段状态由 `episode_state_persistence` 的配置权威持有；`meta/episode-state.json` 在 MySQL 模式下不是可回退的阶段源。
- `meta/runtime-route.json` 只记录路由决策，不是第二状态机。
- `meta/runtime/trace-events.jsonl` 只记录执行事实，不授予 PASS。
- 当前 GPT-Image-2 桌面通道不假设 exact RAW canvas；记录真实 RAW 尺寸与 Provider Receipt，再由 NP01 安全 Normalize。
<!-- STORY_OS_V230_AGENT_RUNTIME_END -->

<!-- STORY_OS_V240_BATCH_RUNTIME_BEGIN -->
## Story OS V2.4 Batch Image Runtime

正式 Production 默认使用 5 图 Batch Runtime：

`5 Frame Contracts → 1 image_generation call → 5 mapped images → per-frame Receipt/Normalize/Ledger/Review`

- Visual Lock 继续保持 1+3，不走 Batch。
- Provider 首个真实 Batch 同时作为 Capability Probe。
- Batch Transport 失败自动回退现有 single-frame worker。
- Deviation >= 80 且 Criticality >= 80 才允许 High×High 紧急单帧返修。
- 其他内容失败等待 Batch 原始生成完成后进入 Repair Arbiter。
- Batch / Trace / Receipt 都是 Evidence，不改变 `episode_state_persistence` 所选择的唯一阶段权威。
<!-- STORY_OS_V240_BATCH_RUNTIME_END -->

<!-- STORY_OS_V241_IMAGE_PROVIDER_RUNTIME_BEGIN -->
## Story OS V2.4.1 Image Provider Runtime（历史记录，当前生产已退役）

本节原先的“API Key 优先选择 OpenAI Images API、失败再回退”仅保留为**历史设计背景**，不得作为当前生产执行指令。当前 StoryOS 图片生成必须使用**原生 ChatGPT/Codex 登录通道**（`codex_subscription` / `native_codex`），严格禁止 OpenCodex 本地代理、API 图片 Provider 和 Product Runtime 图片旁路。
`image_payload_transport.payload_capability_preflight` 在模型/图片 Attempt 之前拒绝非原生 Provider；有无 `OPENAI_API_KEY` 都不会自动授予图片 API 权限。API Key 可按独立模型策略用于被授权的非图片任务，但不能擅自启用图片供应商。
旧 `config/providers/image-provider-runtime.json` 及旧 API 尺寸/n=5 约定不再是当前图片生产路线或正式 Authority，禁止凭其声明通过审核。
API Key / Authorization Header 仍禁止写入仓库文件和 Episode Evidence；每帧实际像素必须独立核验。
<!-- STORY_OS_V241_IMAGE_PROVIDER_RUNTIME_END -->

<!-- STORY_OS_V242_CODEX_SUBSCRIPTION_BATCH_BEGIN -->
## Story OS V2.4.2 Codex Subscription Batch Runtime

当图片执行器显式为 `CODEX` 且通过原生能力门禁时，Production Batch 正式走：

`1 Story OS Logical Batch = 5 frames; up to 5 isolated Codex image workers in flight`

这是 Logical Batch，不是 Provider-native `n=5`：

- `logical_batch=true`
- `native_multi_image=false`
- `single_http_request=false`
- 不需要 API Key，使用本机 ChatGPT/Codex 登录态
- Logical Batch 仍按 5 帧管理，但默认最多 5 个 Codex 图片 worker 同时在途
- 全局 Logical Batch 并发按 CODEX 资源预算与 Scheduler 门禁控制，不因存在 API Key 而自动扩大
- 技术失败自适应 5→4→3→2→1，只重试失败帧
- 成功帧永不因为同批其他帧技术失败而重生
- Fast Scout 延迟到 5 帧原始生成 barrier terminal 后再执行
<!-- STORY_OS_V242_CODEX_SUBSCRIPTION_BATCH_END -->
