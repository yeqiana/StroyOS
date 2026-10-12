# StoryOS R36｜Worker TTL、Writer 唯一租约与 Attempt namespace 修复验收

日期：2026-10-12
分支：`story-platform-v3-rever`
基线：R35 `64d49f7e`
执行方式：四槽滚动。仅隔离测试、可选只读 Adapter、真实本地 Chrome GET；**没有运行正式 Driver，没有接入线上生产 Redis/MySQL，没有付费生图或发布**。

## 目标与现网发现

R35 建立了可选择性注入权威读取器的 GET `/api/v1/runtime/authority?episode=...`。但在 R36 仓库审计时发现：
1. `TB_TASK.EPISODE_ID` 关联的是 `TB_EPISODE.EPISODE_ID` 存储 UID；`TB_GENERATION_ATTEMPT.EPISODE_ID` 在正式表 DDL 中明确存储**稳定 Episode namespace**。R35 读端错误地对二者复用存储 UID，可能查询不到真实 Generation Attempt。R36 已修复且加入参数级测试。
2. `platform/state/worker_heartbeat.py` 把 Redis 心跳写到 `storyos:worker:{worker_id}:heartbeat`，正式 Phase9 Worker 会设置 TTL。读到该键本身**并不能**证明它属于所选 Episode、仍有 TTL、或者拥有有效 Task 执行租约。
3. `episodes/_system/runtime_driver.py` 的 status 函数输出 Driver PID、process liveness 和 beacon，但不产生“唯一 Writer 已获取有效单调 fencing 租约”这一授权结论。**PID 存在、心跳正常不得成为 Writer Lease 的替代证据**。

## 四槽实现

### 槽 1：MySQL Task/Attempt 身份修复与 UNKNOWN

文件：`platform/operations/runtime_authority_readers.py`、`tests/platform/test_runtime_authority_readers.py`。

- 所有读端请求仍先执行 `SELECT DATABASE(), @@lower_case_table_names`，确认 `STORY_OS_RUNTIME` 及 case_mode=0，再验证唯一 ACTIVE `TB_EPISODE.EPISODE_NAMESPACE` 归属。
- Task 按解析出的存储 UID `WHERE EPISODE_ID=%s`；**Generation Attempt 改为按已验证的 namespace** `WHERE EPISODE_ID=%s`，不混用 UID。
- Attempt 只读聚合除 `attempt_count`、`unresolved_count` 外增加 `unknown_count`，对 `OUTCOME_UNKNOWN` 明确标注“禁止自动重试”；若 `unknown > unresolved > count` 则 BLOCKED/UNAVAILABLE，防止错读的结果授权任何重试。
- 无 SQL INSERT/UPDATE/DELETE，保留 R34 严格 Attempt fencing 与全局容量门禁，不对已发生 Provider 调用进行补偿派发。

### 槽 2：MySQL Task 归属与 Redis Worker TTL 核验

新建 `platform/operations/runtime_live_authority_readers.py` 的 `EpisodeWorkerHeartbeatReadOnlyReader`，测试 `tests/platform/test_runtime_live_authority_readers.py`。

- 调用方须显式注入经授权的 `MySqlAuthorityReadOnlyReaders` 与只读 Redis 客户端。不自动读取任何生产 env、没有默认连接。
- 对当前 Episode 的存储 UID 做唯一 ACTIVE Task Owner 定位：`SELECT TASK_ID, EPISODE_ID, OWNER_ID, STATUS FROM TB_TASK WHERE EPISODE_ID=%s AND STATUS='RUNNING' ... LIMIT 2`。
- 必须唯一一条有效 RUNNING Task，具有合法 OWNER_ID，返回的 EPISODE_ID 必须和本次目标完全相同。0 条或 2 条、跨作品、非法 OWNER_ID、其他状态均不读 Redis 且 FAIL-CLOSED。
- Redis 仅通过 GET 和 PTTL 读取 `storyos:worker:{owner_id}:heartbeat`，不得执行写命令。TTL 必须为正且不超过本次严格上界，拒绝 -1 永不过期、-2 无键、错误类型、伪造过高 TTL。
- 心跳 JSON worker_id 必须一致、status 必须 ONLINE、heartbeat_time 必须有时区且满足不超过 120 秒的时间窗口；未来漂移超过 5 秒拒绝。
- 验证的仅是“该 Task 记录所列 Worker 有一条有效 Redis 心跳”；**不宣称它握有 Task Lease / Writer Lease，不宣称生产可运行**。输出只含布尔证明与来源，不包含 worker_id/Task ID/Redis key/凭据。

### 槽 3：Writer fencing 与共享容量 Fail Closed

同一新模块 `EpisodeWriterFenceReadOnlyReader`。

- 必须由授权后端明确注入**两个独立只读来源**：canonical Driver 的 `driver_status(episode_ref)` 与可信 Writer Owner/Fence 的 `owner_fence(episode_ref)`。不默认从 Driver 文件、PID 或旧的 JSON 里臆造 fencing。
- Driver 要求 episode_ref 一致、`RUNNING + ALIVE`、正整数 PID、beacon_age_seconds 0–90 秒且 beacon_at 有效。
- Writer fence 要求 source=`runtime_driver_owner_fence`、episode_ref 一致、owner_active=true、owner_count 严格等于 1、driver_pid 与 Driver 相同、fencing_epoch 为正整数、observed_at 新鲜、有效租约到期时间大于当前且在受控上界内。
- 缺 callback、重复 Owner、lease 过期、PID 不一致、时钟错位、token epoch 无效都返回 `UNAVAILABLE`，绝不向前端暴露原始租约或身份令牌。
- `RuntimeAuthorityEvidenceService._inspect` 新增第二层强制布尔证明校验：`heartbeat_verified`、`owner_fence_verified` 不为严格 `True` 时即便 reader 自称 verified，也**不得**输出 READ_ONLY_VERIFIED。
- 保留单机同 Git Common Directory 全局图片**最多五张**、先取共享容量再消费 MySQL Generation Attempt、不同 Episode 可并行但同 Episode 唯一 Writer 的永久规定；本次不操作 Provider Gateway。

### 槽 4：控制台 Ant Design 证据展示与 Chrome

文件：`web-console/src/api/runtimeAuthorityPresentation.ts`、`platformApi.ts`、`RuntimeRecoveryInsight.tsx` 等；故事制作与作品详情布局不动。

- 前端增加严格校验：verified/advisory 结果必须有受信任源、120 秒内的观测时间、Worker/Writer 实际证明位；容量必须明确 `advisory_snapshot_only=true` 且 busy+available=5。否则丢弃整份不可信报告，保留原未验证提示。
- 阶段 Drawer 新增克制的来源计数 **“R36 · TTL / fencing · 已核验 0/5”**，明确计数的是五类只读来源，**不是图片配额**。
- Attempt `OUTCOME_UNKNOWN` 使用“禁止自动重试”提示；Worker 的 MySQL Task 与 Redis TTL 缺一不可；Writer 的 PID/心跳不能替代唯一 Fence Lease；实际授权回读完成时也只作为证据展示，不出现启动/恢复/发布按钮。
- 浏览器脚本 `npm run test:r36` 在真实本机 Console 1440 / 1024 下实际点击工作流和生产监控，两页面 × 两视口合计 4 项；验证 GET、Episode 身份、0/5、上述提示、无 mutation、440px Drawer 不越界。
- 测试启动一度因旧 detached 本机只读 Vite 服务退出出现 `Cannot find default execution context` 与 `timeout nav`。核验发现 `127.0.0.1:3100`、`19117` 均拒绝连接，重新启动正式本机只读 launcher 后**原页面交互场景全部重新跑通**。脚本仅增加 Chrome renderer 初始上下文的有限重试，没有跳过任何业务断言。

## 验收矩阵

| 类别 | 实测 |
|---|---|
| Platform HTTP + SQL 读端 + Worker/Writer 和安全 API | **124/124 passed**（含配置上限、跨作品、UNKNOWN 等新增边界） |
| R34/R35 Attempt/Driver/5图容量/恢复 | **93/93 passed** |
| R36 前端来源安全与 UNKNOWN | **4/4 passed** |
| R35 兼容前端守卫 | **3/3 passed** |
| R35 原版详情浏览器行为回归 | **4/4 真实 Chrome passed** |
| R36 真实 Chrome 工作流/生产监控 × 1440/1024 | **4/4 passed** |
| TypeScript (`npm run lint`) | 通过 |
| R28 七个一级菜单 × 两视口 | **14/14 真实 Chrome passed** |
| R25 故事制作/作品详情 | **6/6 真实 Chrome passed** |
| Vite 生产构建 | **通过，3215 modules transformed** |

实际截图：`.storyos-tmp/ui-qa/r36/storyos-r36-workflow-1440.png`、`storyos-r36-workflow-1024.png`、`storyos-r36-monitor-1440.png`、`storyos-r36-monitor-1024.png`。截图在前端展示的是主工作区真实阶段文件，**不代表 MySQL/Redis 已接入在线平台**。

## 尚未具备的生产授权与 R37 阻塞

- **P0**：实际生产 Platform API 尚未显式注入受限 SELECT-only MySQL + read-only Redis + 独立 Writer Fencing Source；无这些权威配置时默认仍返回未配置/不可用，**不能声称真实 Worker/Writer 数据上线**。
- **P0**：Driver Owner/Fence 需要可信、带 CAS/fencing 的后端实际记录与 lease 快照。R36 完成了 Adapter、判定规则及 Fake 上的完整失败情境，**没有在现网创建缺失的可信 Writer Lease**。
- **P0**：真实图像容量仅有单机同 Git Common Directory 的共享 OS 锁；跨主机 / 不同 Git Clone 必须另有分布式 fencing 验收，不能依靠五图只读快照启动正式生产。
- **P1**：下一轮优先在获得明确授权的只读环境验证实际 Task→Worker→Writer 证据血缘与状态新鲜度；独立批准的双 Episode Canary 仍需再获生产执行许可。

## Git 保护

只 stage R36 明确修改的新增读端、原 R35 只读查询及证据、前端 React 展示/guard、Chrome 测试和本验收 MD。根目录其他人的 `reports/account-pattern-registry.json`、`reports/account-learning-index.json` 和全部既有 untracked/Story 资产保持原样，不作为本次提交内容。不修改生产 MySQL/Redis、Provider Dispatch、正式 Runtime Driver、发布、Story 内容、冻结的制作/详情布局。
