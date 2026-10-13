# Story OS — START HERE

> 30 秒执行入口。这里不是第二套创作规范，只负责告诉 Agent **先读什么、现在在哪、下一步做什么**。
>
> 创作规则唯一权威：`standards/制作规范_正式版.md`  
> 阶段状态唯一事实源：`<episode>/meta/episode-state.json`

## V2.6.1 Product Runtime First

正常 Agent 恢复上下文时先读 `episodes/_system/MODULE_INDEX.json` 与 `meta/runtime/next-action.json`（若存在），不要默认广扫 `episodes/_system` 的 legacy/test 模块。

默认 Runtime：`WORK`。

**纯 Codex 全流程（显式选择）**：见 `docs/StoryOS_原生Codex全流程自动生产_20261010.md`。
在本机原生 Codex CLI 先执行 `python scripts/storyos_codex_managed.py plan <episode>`，
只在 `READY_TO_START` 后执行 `python scripts/storyos_codex_managed.py run <episode> --ack-real-production`；
新故事可用 `create <故事要求> --ack-real-production`。以上入口将单次会话路由为
`CODEX_MANAGED`（文本/治理/视觉审核与图片执行全走 Codex），并对本地正式 MySQL 和
历史 `OUTCOME_UNKNOWN` 做只读准入；不会跳过审核/Attempt/Revision，也不使用视频生成。

已有 Episode 需要在会话退出后继续生产，优先使用 `python scripts/storyos_codex_managed.py start <episode> --ack-real-production`；`start` 调用已有常驻 Driver，仍先执行全部只读 Attempt / Owner / Stage 准入，不代表可以越过审核。四槽极速测试：`python scripts/storyos_autonomy_fast_test.py --slot all`；改造完成再用 `--stress`。详见 `docs/StoryOS_原生Codex自治生产与四槽极速验收_20261013.md`。
**自治续跑 R2（显式授权）**：已有 Episode 的恢复 Watchdog 使用 `python scripts/storyos_autonomy_watchdog.py plan <episode>` 先只读诊断；需要持久监控时，由可信用户态 Carrier 显式运行 `watch <episode> --ack-real-production`，绝不自动首次启动、清理 UNKNOWN 或绕过人工门禁。新增四槽测试 `--slot watchdog|budget|authority|e2e`，整体仍为 `python scripts/storyos_autonomy_fast_test.py --slot all --stress`。见 `docs/StoryOS_R2_自治Watchdog_四槽极速验收_20261013.md`。
**R3 四槽自治升级**：只读单帧证据 `python scripts/storyos_autonomy_canary.py plan <episode>`；Windows 登录载体先 `python scripts/storyos_autonomy_carrier.py plan <episode>`，安装/卸载必须显式生产授权且仅从主工作区运行。原子 Writer Token 只代表基础锁安全，跨主机生产仍禁止；每槽执行 `python scripts/storyos_autonomy_fast_test.py --slot carrier|writer|canary|autonomy-integration`，整轮执行 `--slot all --stress`。见 `docs/StoryOS_R3_四槽自治Carrier_Writer_Canary_极速验收_20261013.md`。
**R4 完整生产二次权威校验**：官方图片 Provider 发起前增加 MySQL Generation Attempt live Fence 复查，Windows Watchdog 加入实际 Task Scheduler 触发/单实例验真，原生单帧 Canary 双次对齐 Episode/Attempt/模型路由证据；全部 fail-closed，不替代真实生图 Canary。单槽极速命令 `python scripts/storyos_autonomy_fast_test.py --slot dispatch-fence|carrier-integrity|frame01-fence|r4-integration`；整轮 `--slot all --stress`。详见 `docs/StoryOS_R4_四槽自治二次Fence与极速验收_20261013.md`。
**R5 自治治理与原生 Codex 只读验收**：`python scripts/storyos_autonomy_native_ready.py` 核对真实 CLI + 交互用户凭证可见性，零付费、不承诺模型资格。Provider 回执持久化失败按 UNKNOWN 处理不自动重试；退役分支/Worktree 先 `python scripts/storyos_retired_worktree_gc.py plan` 或 `branches-plan`，仅明确授权、二次核验后安全清理。四槽独立极速入口 `--slot retirement|provider-receipt|native-login|r5-integrated`，整体 `--slot all --stress`。见 `docs/StoryOS_R5_四槽治理_原生Codex与极速验收_20261013.md`。
**R6 原生 Codex 与生产结果安全**：本地已登录的 Codex CLI 通过 `storyos_autonomy_native_ready.py` 仅证明 CLI/Runner 授权上下文，Frame01 只读准入额外双检；Provider 网络/CLI 超时应按 UNKNOWN 保护已消耗 Attempt，禁止自动重试。清理前先 `storyos_retired_worktree_gc.py plan`，仅删除可二次验证的退役对象。各槽极速 `--slot gc-fence|provider-timeout|codex-frame01|r6-e2e`，全轮 `--slot all --stress`。详见 `docs/StoryOS_R6_四槽续推与极限测试_20261013.md`。
默认 `COLLABORATIVE` 配置保持不变。

```text
ChatGPT / Work + DevSpace
→ WORK Runtime
→ Story OS deterministic scripts + product-host model/image actions
→ machine/evidence gates
```

**本机存在 `codex.exe` 只代表“可用能力”，不再代表整个 Runtime=CODEX。** 默认唯一生产模式入口是 `config/storyos.yaml:production.mode=COLLABORATIVE`；执行器入口统一为 `execution.workspace.provider=webcodex`、`execution.image.executor=CODEX`、`execution.vision_review.executor=CODEX`。协作宿主不可用时不会自动切到本地 Codex。需要整条链由 Codex 管理时，显式设置 `production.mode=CODEX_MANAGED` 或单次覆盖 `STORY_OS_PRODUCTION_MODE=CODEX_MANAGED`。旧 `STORY_OS_RUNTIME` 仅保留兼容/调试用途。图片控制模型与生图模型分别读取 `config/storyos.yaml:models.profiles.image_controller` 和 `models.profiles.image_payload`。

Concept / Story / Legacy Visual 独立评审允许 `WORK_ISOLATED / WEB_ISOLATED / CODEX_ISOLATED`，均必须 fresh + SHA-bound。图片执行层可用 `STORY_OS_IMAGE_EXECUTOR=CODEX|PRODUCT_RUNTIME|AUTO` 覆盖；旧 `STORY_OS_IMAGE_RUNTIME` 暂作兼容。只有显式选择 `PRODUCT_RUNTIME` 时，缺文件传输能力才返回 `HOST_ACTION_REQUIRED / HOST_WAIT`。Host Action 以 request_id 保存历史，Product Review 以 attempt-scoped request 保存历史。WORK `--full-auto` 必须进入统一 Runtime DAG 连续推进；`PREIMAGE_COMPILE` 是独立 Runtime 节点但不是第八个 Episode stage。每次宿主/审图动作后读取派生 `meta/runtime/next-action.json` 自动继续，不得因为正常 Host Action 再询问用户。Visual Lock baseline 与每个 Production Logical Batch 生成后都必须回 WORK 做 actual-pixel review，再放行后续生成。

<!-- STORY_OS_V2_1_CONCEPT_BEGIN -->
## V2.1 概念野心与图像传播入口

新篇 Story Lock 前：最近机制上下文 → 8–12 候选放飞 → Concept Ambition → Cover/Mid/Climax 三传播图 → 无字测试 → 最终题 → Story/Storyboard → Story Critic + Recent-5 Semantic。

核心原则：**概念不要克制，镜头必须真实。** 真实性限制采集表现，不限制异常尺度、虚构遗址、梦境空间或不存在的世界规则。
<!-- STORY_OS_V2_1_CONCEPT_END -->

<!-- STORY_OS_V2_1_PHASE3_BEGIN -->
## V2.1 Phase 3：Environment / Impact

Story Lock 通过后、Visual Lock 前必须完成：
`Environment Contract → Frame Directive → environment_contract.py verify`。

环境是物理条件，不是滤镜；异常可以很大，但高冲击帧必须有现实尺度参照、明确 escalation_from，并保持真实拍摄物理。
<!-- STORY_OS_V2_1_PHASE3_END -->

<!-- STORY_OS_V2_1_PHASE4_BEGIN -->
## V2.1 Phase 4：Resolved Frame Contract

Environment / Impact Contract PASS 后、Visual Lock 校准前：

```text
python episodes/_system/frame_contract.py compile-all <episode>
python episodes/_system/frame_contract.py verify <episode>
```

每帧正式生成与最终审核必须绑定同一个 `frame_contract_sha256`。`meta/runtime/contracts/` 只是派生缓存，不是新权威源。
<!-- STORY_OS_V2_1_PHASE4_END -->

<!-- STORY_OS_V2_1_PHASE56_BEGIN -->
## V2.1 Phase 5 + 6：Visual Lock / 并发生产

Visual Lock 固定为四层准入：

`ordinary baseline → worst condition → first anomaly → high-impact admission`

baseline 先生成，后三张允许有界并发。统一 Visual Lock Critic PASS 后，Batch 统一使用 `image_scheduler.py`，并发上限从 `config/storyos.yaml:production.max_inflight_images` 读取（当前为 5；修复任务的 4 槽位不等于图片 Worker 数）；技术失败只阻塞依赖帧，无关帧继续。
<!-- STORY_OS_V2_1_PHASE56_END -->

<!-- STORY_OS_V2_1_PHASE78_BEGIN -->
## V2.1 Phase 7 + 8：Fast Scout / Final Snapshot

Phase 7：高风险帧生成后做 Fast Scout；`PASS_FAST` 不是 Production PASS，`REPAIR_NOW` 才提前返修，低风险/不确定统一交给 Final Critic。

Phase 8：Release/Compliance/Text/Frame 全部 PASS 后冻结 `meta/final-candidate-snapshot.json`。PUBLISH_READY 和 Delivery Adapter 都必须验证该 Snapshot；ZIP 不再重新扫描“当前最新文件”。
<!-- STORY_OS_V2_1_PHASE78_END -->

<!-- STORY_OS_V2_1_PHASE910_BEGIN -->
## V2.1 Phase 9 + 10：系统闭环

Phase 9：`migrate_v21.py` 默认只读；旧 Episode 保持 LEGACY_COMPAT，不补造 V2.1 PASS evidence。安装时运行完整 regression matrix，并用 `workflow_observability.py` 汇总慢步骤、并发、失败类型和证据状态。

Phase 10：真实发布后记录 `meta/publish-event.json`，不要修改已被 Final Snapshot 冻结的 release-manifest。6h/24h/48h/7d 数据写入 post-publish evidence；48h 达标后推进唯一 Stage `DATA_REVIEWED`，并生成下一篇 `learning packet`。
<!-- STORY_OS_V2_1_PHASE910_END -->

<!-- STORY_OS_RUNTIME_REQUEST_P0_CORE_BEGIN -->
## Runtime Request P0

新篇自然语言入口先编译为 `runtime-request`。未提供剧情时必须 `auto_create`；粗剧情必须 `user_seed → strengthen_and_rewrite`；未指定 image 时默认模型与质量读取 `config/storyos.yaml:models.profiles.image_payload`；显式 image 禁止静默替换或降级 Quality。当前 Visual Lock 固定为 4 张准入帧。
<!-- STORY_OS_RUNTIME_REQUEST_P0_CORE_END -->

## 0. 黄金路径（Golden Path）

```text
恢复上下文
→ 选题 / 去同质化
→ 锁故事与专业分镜
→ 建真实性卡与连续性锚点
→ 四张 Visual Lock 准入（baseline / worst / first anomaly / high-impact）
→ Visual Lock
→ 批量生产
→ 逐帧审核 / 必要返修
→ Final Checklist
→ 发布
→ 6h / 24h / 48h / 7d 数据回填
```

机器状态仍只使用仓库原生七阶段：

```text
IDEA_LOCKED
→ STORYBOARD_LOCKED
→ VISUAL_CALIBRATED
→ PRODUCTION_PASSED
→ PUBLISH_READY
→ PUBLISHED
→ DATA_REVIEWED
```

**不要新建第二套 stage / status / workflow 状态。**

## 1. 每次任务只按这个顺序读

1. `config/storyos.yaml`：当前生效生产配置，先校验
2. `config/index.yaml`：仓库索引与当前阶段最小读取集
3. 本文件 `START_HERE.md`
4. 根目录 `SKILL.md`
5. 根目录 `AGENTS.md`
6. `standards/制作规范_正式版.md`
7. `standards/AUTHORITY_INDEX.json` 中与当前任务匹配的 active 从属细则
8. 目标剧集 README / docs / 锁定分镜
9. 目标剧集 `meta/episode-state.json`
10. 若 strict=true，再读索引声明的必要 evidence

不要为了“更保险”把整个 `standards/` 全部读一遍。旧版本和 superseded 文件只用于历史追溯。

## 2. 三个正式人工锁点 + 返修范围授权

除非用户已经明确授权连续执行，否则以下节点必须显式确认后再继续：

1. **Story Lock**：故事与专业分镜是否锁定。
2. **Visual Lock**：四张准入帧是否完成统一 Critic 并锁定。
3. **Release Lock**：标题、封面、字幕、简介、话题、发布图是否为最终版。

**返修不是第四个 Lock。** 返修使用 Production Ledger 已有的 repair authorization / reopen lane：只授权明确失败或被用户点名的帧；未授权的已通过帧不得连带重做。它是范围授权，不创造新的状态或 Gate。

以上三个 Lock 不是新状态机，只是人工决策 Gate。

## 3. Visual Baseline → Trial → Batch

所有新篇统一使用：

```text
人物 / 场景 / 设备真实性基线
→ 四张 Visual Lock 准入帧
   A. ordinary baseline
   B. worst capture condition
   C. first major anomaly
   D. high-impact admission
→ VISUAL_CALIBRATED
→ 剩余图片批量生产
```

禁止“先把 20 张都出完，再回头找画风”。

## 4. 最小修改协议

用户说：

- “只改字幕 / 底图别动” → `subtitle_only`
- “只裁切” → `crop_only`
- “保持原画风重做这一张” → `regenerate_frame`
- “整段重做” → `regenerate_sequence`

未被点名的已通过帧默认锁定，不得顺手重做。

## 5. 一条命令知道下一步

```bash
python episodes/_system/story_os.py next <episode_dir>
```

仓库健康检查：

```bash
python episodes/_system/story_os.py doctor
```

生成最终验收清单：

```bash
python episodes/_system/story_os.py checklist <episode_dir>
```

只看状态，不修改：

```bash
python episodes/_system/story_os.py status <episode_dir>
```

## 6. 文档权威规则

`standards/AUTHORITY_INDEX.json` 只做路由，不创造规则：

- `canonical`：唯一主规范。
- `active_subordinate`：当前有效执行细则。
- `series_overlay`：系列覆盖层，只能补充，不得反向覆盖主规范硬规则。
- `reference`：参考材料，不是门禁。
- `superseded`：历史版本，默认禁止作为当前规则引用。

出现冲突：

```text
制作规范_正式版
> active subordinate
> series overlay
> reference
> superseded
```

## 7. Final QA 只生成，不再造第五套规范

`final_checklist.py` 只从现有状态、门禁和 manifest 汇总一份：

`<episode>/meta/FINAL_CHECKLIST.md`

它不是规范源，也不得保存 stage。最终人工仍需回答：

- 像不像真实手机相册 / 合理采集设备？
- 人物、地点、关键道具是否连续？
- 前 5 张有没有继续滑的欲望？
- 高潮是否足够强，且不是近期作品的重复机制？
- 结尾是否回收前文，并产生回看价值？
- 字幕是否像人话、位置是否压住主体？
- 封面 / 标题 / 简介 / 话题是否和成片一致？

## 8. 一句话原则

**规则可以很多，决策入口只能有一个。**

当前配置自检：

```bash
python episodes/_system/story_os.py config validate
```

<!-- STORY_OS_V1_7_RELIABILITY_BEGIN -->
## 9. V1.7 生产可靠性

Golden Path 七阶段不变。V1.7 只在两个位置增加事务保护：

```text
Batch 生图请求
→ production_ledger begin
→ transport_guard preflight
→ 调用生图
→ success / technical failure

已锁图片只修文字
→ text_revision start
→ 编辑
→ diff + text_audit
→ submit
→ 用户明确批准 approve / 不满意 revert
```

技术失败不得消耗内容返修次数；技术重试不得改变请求指纹。文字专修不得触碰批准/发布图片、reference、release manifest、production ledger、episode state 或 story gates。
<!-- STORY_OS_V1_7_RELIABILITY_END -->

<!-- STORY_OS_V1_8_DEFAULT_STYLE_BEGIN -->
## 10. V1.8 默认视觉 IP 与三道不可漂移锁

用户没有明确指定画风/质感时，默认解析：

`M00｜现实生活纪实母版`

但它只统一视觉语言；**本集年代和实际采集设备的物理表现优先**，禁止把现代手机硬做成旧低清设备。

V1.8 不新增 episode stage，只给现有 Golden Path 增加证据锁：

```text
Story Lock → story + storyboard approval SHA
Visual Lock → visual spec + calibration + references + resolved profile SHA
Batch → 现有 V1.7 production / transport
Text Audit → text-audit.json 必须 PASS 且 captions SHA 不漂移
Release → release-package.json 锁最终封面/正文/字幕/发布文案/传播卡 SHA
```

常用命令：

```bash
python episodes/_system/story_os.py visual-profile <episode_dir> show
python episodes/_system/story_os.py approval <episode_dir> story --user-approved
python episodes/_system/story_os.py approval <episode_dir> visual --user-approved
python episodes/_system/story_os.py audit-text <episode_dir>
python episodes/_system/story_os.py release-package <episode_dir> build --user-approved
```
<!-- STORY_OS_V1_8_DEFAULT_STYLE_END -->

<!-- STORY_OS_V2_MULTI_RUNTIME_BEGIN -->
## 11. V2.0 Multi-Runtime

启动时按 `runtimes/runtime-contract.json` 自动判断执行环境，不询问用户选择模式：

`可写仓库+terminal/code execution → CODEX；ChatGPT Work → WORK；其他普通 ChatGPT → WEB`

三个 runtime 只改变执行方式，不改变创作权威和 episode stage。

用户明确说“全自动执行 / 一次做完 / 做到最终交付 / 不要每步问我”时，视为连续执行授权。正常 Golden Path 不重复询问是否继续；自动审查必须标记为 delegated_auto_review，不得写成用户亲眼审核。

统一恢复证据：`<episode>/meta/runtime-checkpoint.json`。它不是 stage。
<!-- STORY_OS_V2_MULTI_RUNTIME_END -->

<!-- STORY_OS_V2_0_1_ENGINEERING_BEGIN -->
## 12. V2.0.1 工程补强

CODEX runtime 新增一键入口：

```bash
python episodes/_system/story_os.py run <episode_dir> --full-auto
```

它使用当前 Codex CLI 登录态启动独立全自动 worker；正式图片可通过 `codex_subscription_image.py` 落成真实文件，不要求 API Key。全自动审查统一记为 `delegated_auto_review`，不得伪造 `direct_user_review` 或 Release Lock。

证据门禁外部稳定名统一为 `evidence_gate.py`；`v18_gate.py` 只作为历史兼容实现保留。
<!-- STORY_OS_V2_0_1_ENGINEERING_END -->

<!-- STORY_OS_V2_0_2_CLOSURE_BEGIN -->
## Story OS V2.0.2 Production Closure

CODEX 全自动完成必须经过 deterministic postflight；worker 正常退出不等于完成。生图必须使用 `generate-for-frame` 走 raw→canvas normalize→ledger。全自动 Story/Visual/Release 使用 delegated approval 证据，不伪造用户亲审。最终 delegated ZIP 禁止 approved fallback，必须包含真实 publish 资产和完整文本/manifest/hash。
<!-- STORY_OS_V2_0_2_CLOSURE_END -->


## V2.0.3.3 Frame Semantic Enforcement

Batch 完成后，`PRODUCTION_PASSED` 前必须运行 `episodes/_system/frame_semantic_review.py` 的 fresh isolated full-frame-set critic；实际图片必须与 Story Lock / Storyboard / Authenticity Card / Continuity Anchors 一致，并通过 SHA-bound review 与 near-duplicate audit。该证据不新增机器状态。
<!-- STORY_OS_V2_0_3_4_INCREMENTAL_WORKSPACE_BEGIN -->
## V2.0.3.4 最小闭环 + 本地媒体工作区

默认先做增量计划，不再无条件重跑整篇：

```bash
python episodes/_system/incremental_closure.py plan <episode_dir> --json
```

帧审核统一入口：

```bash
python episodes/_system/incremental_frame_review.py review <episode_dir> --attempt 1
```

- CLEAN 的 Story / Visual / Frame 证据按 SHA 直接复用。
- 只改 1~N 张图时默认审核 dirty frame ±1；终局高风险帧默认 ±2。
- Story / Storyboard / Visual Contract 改变，或 dirty > 25%，自动升级 FULL_FRAME_SET。
- 全局 SHA、尺寸、近重复仍执行廉价全量审计。

新篇本地媒体统一放：`media/calibration|raw|candidates|approved|publish|review|archive`；交付放 `release/`；Git 只跟踪 `meta/media-index.json` 与文本/证据，不跟踪这些像素资产。

例外且为强制项：**系列剧本的母版图必须提交 Git**。被 `episodes/**/meta/series-character-identity.json` 引用的 `group_identity_asset` / `primary_asset` / `supporting_assets` 落在 `assets/characters/`，必须入库；`python episodes/_system/contract_sync.py` 会对未入库的母版图 FAIL。

媒体工具：

```bash
python episodes/_system/media_workspace.py inventory
python episodes/_system/media_workspace.py migrate --dry-run
python episodes/_system/media_workspace.py ensure <episode_dir>
```

历史未纳管 episode 不自动搬图；重新进入制作时再迁移。
<!-- STORY_OS_V2_0_3_4_INCREMENTAL_WORKSPACE_END -->

<!-- STORY_OS_RUNTIME_DAG_REFACTOR_CORE_BEGIN -->
## Runtime DAG Refactor
绑定 Runtime Request 的新篇默认使用 Runtime DAG：Creative Story → Visual Lock → Production → Release。每步完成立即落 checkpoint；恢复时验证后复用。DAG 不建立第二 stage。图片采用 continuous max3 调度；Scoped Worker 优先用 Execution Capsule；Prompt Package / Rolling Review / Provisional Release 都是派生执行优化，不替代正式 Gate。图片 pool 只复用 Python worker，不复用 Codex 跨帧上下文。
<!-- STORY_OS_RUNTIME_DAG_REFACTOR_CORE_END -->

<!-- STORY_OS_CHARACTER_ENTRY_POOL_CORE_BEGIN -->
## Character / Entry Pool
新篇 Concept 前先准备 Character Contract：优先普通二十来岁青年/朋友团，以旅行、返乡、聚会、挑战、废弃场所、户外、生活化工作/科考等日常理由进入异常；默认禁用抢修/维修/警察/记者/调查员等功能型主角。第一人称也锁人物锚点。Story Lock 前 NO-ANOMALY TEST 必须 PASS，随后 Character Contract 绑定进 Frame Contract。
<!-- STORY_OS_CHARACTER_ENTRY_POOL_CORE_END -->

<!-- STORY_OS_RUNTIME_OPTIMIZATION_R2_CORE_BEGIN -->
## Runtime Optimization R2
支持 `preproduction_only`（只做生图前资产并写 Handoff）和 `image_continue`（校验 Handoff 后从 Visual/Image 继续，禁止重写 Story）。启用 `.storyos_cache/` 多级缓存、`library/` 共享参考资源库、Visual Lock 1+3、简介四类开头策略和“标题仅1个内部候选”规则。正式 Story/Visual/Production/Release Gate 均不删除。
<!-- STORY_OS_RUNTIME_OPTIMIZATION_R2_CORE_END -->

<!-- STORY_OS_V230_AGENT_RUNTIME_BEGIN -->
## Story OS V2.3 Agent Runtime

执行链：
`Raw Request → Intent Resolver → immutable Runtime Request → Request Router → Workflow DAG → Tool/Model Execution → Trace/Evidence`

- `meta/episode-state.json` 仍是唯一阶段状态源。
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
- Batch / Trace / Receipt 都是 Evidence，不改变 `meta/episode-state.json` 唯一阶段权威。
<!-- STORY_OS_V240_BATCH_RUNTIME_END -->

<!-- STORY_OS_V241_IMAGE_PROVIDER_RUNTIME_BEGIN -->
## Story OS V2.4.1 Image Provider Runtime

Production Batch 先读取 `config/providers/image-provider-runtime.json`：

- 存在 `OPENAI_API_KEY`：优先 OpenAI Image API，GPT-Image-2 可用 `n=5`（上限10）执行 native multi-image。
- 无 API Key 或 API transport 失败：保持 Codex Subscription fallback。
- API Key / Authorization Header 禁止写入任何仓库文件或 Episode Evidence。
- `output_index -> Frame` 是 Story OS 映射约定，不是 Provider 创作权威，仍必须逐帧 Review。
- 4:5 API 请求使用 1088×1360，9:16 使用 1152×2048，之后无裁切 Normalize 到正式 Release Canvas。
<!-- STORY_OS_V241_IMAGE_PROVIDER_RUNTIME_END -->

<!-- STORY_OS_V242_CODEX_SUBSCRIPTION_BATCH_BEGIN -->
## Story OS V2.4.2 Codex Subscription Batch Runtime

没有 `OPENAI_API_KEY` 时，Production Batch 正式走：

`1 Story OS Logical Batch = 5 frames; up to 3 isolated Codex image workers in flight`

这是 Logical Batch，不是 Provider-native `n=5`：

- `logical_batch=true`
- `native_multi_image=false`
- `single_http_request=false`
- 不需要 API Key，使用本机 ChatGPT/Codex 登录态
- Logical Batch 仍按 5 帧管理，但最多 3 个 Codex 图片 worker 同时在途
- 无 API Key 时全局只允许 1 个 Logical Batch 在途，避免多个 Logical Batch 叠加造成并发放大
- 技术失败自适应 3→2→1，只重试失败帧
- 成功帧永不因为同批其他帧技术失败而重生
- Fast Scout 延迟到 5 帧原始生成 barrier terminal 后再执行
<!-- STORY_OS_V242_CODEX_SUBSCRIPTION_BATCH_END -->

<!-- STORY_OS_V2_5_1_RUNTIME_FAST_PATH_BEGIN -->
## V2.5.1 Runtime Fast Path

恢复/新上下文先执行：`python episodes/_system/story_os.py fast-path prepare <episode>`。优先读 `meta/runtime/resume-capsule.json` 与当前 step Execution Capsule；只在 source SHA 漂移、缺字段或 Gate 报 drift 时才广泛重读仓库。未显式验证像素视觉能力的 Rolling Reviewer 只能 `UNCERTAIN → Final Review`，不得 `REPAIR_NOW`。主会话每次再次生成原始候选前必须先 claim Raw Candidate Budget；默认同一 original/repair/exception 最多 2 次，技术失败不计。
<!-- STORY_OS_V2_5_1_RUNTIME_FAST_PATH_END -->

<!-- STORY_OS_V2_5_1_1_FORCED_CANDIDATE_GATE_BEGIN -->
## V2.5.1.1 Forced Candidate Gate
正式生图入口自动执行 Raw Candidate Budget；技术失败释放预算；同一 Queue Item 技术重试复用 token；候选额度耗尽后硬停止内容生图循环。
<!-- STORY_OS_V2_5_1_1_FORCED_CANDIDATE_GATE_END -->

<!-- STORY_OS_V2_6_0_PERFORMANCE_RUNTIME_BEGIN -->
## V2.6.0 Performance Runtime / Cross-Shell Contract

性能优先，但不降低创作门禁。恢复优先使用 Resume Capsule；正式图片候选走原子 Candidate Lifecycle。
禁止 Agent 使用 Bash heredoc、PowerShell here-string、嵌套 `powershell -Command`、`shell=True` 或把大段 JSON/多行 Python 塞进 shell。
多行/结构化内容必须走 UTF-8 文件、stdin 或仓库 file edit/write API；路径作为 argv 元素传递，不手工拼引号。
Final Visual Freeze 只绑定视觉 SHA，Caption 变化只触发 Caption ↔ Image Audit，不得重新拉起全量 Visual Critic。
Golden/性能回归（B5）：`golden_episode_regression.py run` 读 `reports/golden-episode-registry.json` 逐项回归（当前空骨架：现役候选未同时具备 density/voice/capture/world/lineage/propagation/text 全零错误输入，不降门槛注册）；`performance_regression_v211.py replay` 回放 `tests/performance/replays/PERF-REPLAY-V2.1.1-20260831-停电夜蜕壳.json`。两入口已由 story-gates.yml `golden-replay` job（workflow_dispatch）接线，本机与远端执行同一命令。
<!-- STORY_OS_V2_6_0_PERFORMANCE_RUNTIME_END -->

<!-- STORY_OS_SINGLE_DRIVER_BEGIN -->
## V2.6.1.1 单一驱动契约（Single Driver）

一个剧集同时只能有一个驱动者。**唯一常驻驱动**是：

```text
python episodes/_system/story_os.py runner <episode_dir>
```

它转发 `episode_runner.py`，是**唯一**会写 `meta/runtime-runner-state.json`、持续心跳、并在每个循环落 `HOST_LOOP` 证据的进程。宿主 Agent 的职责是**确保它在跑**，不是手工替代它。

`python episodes/_system/story_os.py run <episode_dir> --full-auto` 是**有界排空**：进入统一 Runtime DAG 连续推进，遇到宿主动作（`HOST_ACTION_REQUIRED`）即退出交回，不常驻。它是这条驱动的一个受限入口，不是第二套驱动。

长任务必须脱离宿主调用的生命周期。**官方分离入口**是：

```text
python episodes/_system/story_os.py driver start <episode_dir> [--codex <codex>] [--resume]
```

它启动的**就是上面那一个常驻驱动**（同一个 owner lock、同一份心跳），只是不再挂在发起调用的进程下面——宿主 tool 调用的 300 秒预算杀不掉它，退出码与 stdout 由它自己落盘，`driver status` / `driver logs` 只读地报告它是否还活着、退出码是什么、日志在哪。`driver recover` **不杀任何进程**：恢复动作就是再 start 一次。`meta/runtime/in-flight-codex.json` 记录在跑的 Codex 任务，重启后的驱动领取前任已经付过钱的结果，而不是把同一个 scoped 步骤再跑一遍。

**`runtime_dag.py`（`story_os.py dag run`）是步骤引擎，不是驱动器。** 它执行被点名的节点后返回：不启动宿主循环、不写心跳、不落 `HOST_LOOP` 证据。绕过驱动的手工 DAG 推进会得到一个「看起来在推进、实际无人负责」的剧集。

判活只读派生字段，不要靠猜：

- `host_loop`：只有 `RUNNING` 证明有活着的循环；其余（含 `HOST_WAIT` / `RECOVERY_REQUIRED` / `UNKNOWN`）一律 `IDLE`。
- `orphaned_pending_work`：`true` 表示**有工作欠着、却没人在跑循环**——这正是 2026-09-14 `尸解仙` 的形态。

读取点：`meta/runtime/next-action.json`（`host_loop`、`runner_status`、`orphaned_pending_work`、`suppressed_product_reviews`）。

**这不是自动重启信号。引擎不提供看门狗：** 没有任何**自动**路径会 start / stop / restart 一个 runner——`story_os.py driver start` 是**显式**入口，只在你（或宿主 Agent）明确调用时启动一次，不轮询、不自愈、不代替判断。看到 `orphaned_pending_work: true`，正确反应是**由人重新拉起驱动者**，不是等引擎自愈。

`runtime.continuous_host_loop` 只影响 `run --full-auto` 内部的一次有界排空，不改变上述任何一条。
<!-- STORY_OS_SINGLE_DRIVER_END -->
