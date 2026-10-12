# StoryOS R34 · Generation Attempt 完整性、Writer 诊断与全局图片容量验收

日期：2026-10-12
分支：story-platform-v3-rever
基线：R33 提交 35cb20ba

## 一、目标与授权边界

R34 按四槽推进：① Task/Attempt/Worker 只读证据；② 多 Episode Writer 身份与无凭据环境的安全失败；③ 单 Git 仓库跨 Worktree 全局 5 图额度及 Attempt 幂等恢复；④ 控制台生产证据和真实 Chrome 视觉验收。

只执行只读命令、隔离非付费 pytest、Web Console Chrome GET。**没有启动正式 Driver、没有真正派发图片、没有操作生产 MySQL/Redis 写接口、没有绕过生产 Ack。** 现有平台不提供授权的在线 Task/Attempt/Worker 明细 API，因此不能声称“R34 已打通在线任务执行”，只能完成权威证据缺口显示和恢复前置的安全校验。

根 AGENTS.md 多 Episode 永久要求不变：不同 Episode 可并行；同一 Episode 只有一个 Owner；同一 Git common dir 的所有生产图像 Provider 共享严格最多 5 张；拿到名额之前不准消费新的 Generation Attempt；离线/锁忙/未知不得计作 Provider 失败。

## 二、四槽落地

### 槽 1：MySQL Attempt 只读数据完整性

修改 scripts/storyos_attempt_readonly_preflight.py 与 tests/system/test_storyos_attempt_readonly_preflight.py。

在原只读 SELECT 后、输出任何“历史清洁”分类之前，新增严格检查：
- LOGICAL_ASSET_KEY 必须是当前 Episode 的层级子资源，否则返回 ATTEMPT_HISTORY_INTEGRITY_BLOCKED，报告只显示 OUT_OF_SCOPE，不泄露其他 Episode 的完整标识。
- 重复 (LOGICAL_ASSET_KEY, ATTEMPT_INDEX) 或重复 Asset State 行标记完整性阻塞。
- Attempt Index、Active Attempt Index 只允许该项目既有 Authority 定义的 1/2，不能把 bool、float、乱码或越界值当有效。
- ATTEMPTS_CONSUMED 必须是 0..2；对已 DISPATCH_COMMITTED / SUCCEEDED / FAILED_AFTER_DISPATCH / OUTCOME_UNKNOWN 的尝试，若对应 State 的已消费次数小于最大已提交 Attempt，则阻塞。
- RESERVED 尚未提交 Provider 的 Attempt 不误计为已消费预算；其活动租约仍不能重复派发。
- 原 UNKNOWN、活动 Attempt 和非法状态逻辑保留；返回 status=ATTEMPT_HISTORY_READ_ONLY 也永远 production_authorization=false。
- 读库异常只输出异常类名，不泄漏连接配置；不新增任何 SQL UPDATE/INSERT。

### 槽 2：Episode Driver Owner 和状态探针 fail-closed

修改 scripts/storyos_multi_episode.py 与 tests/system/test_multi_episode_driver_launcher.py。

复现发现：在未通过真实 production.env 接入配置时，直接运行只读 multi-episode status 会由于 canonical MySQL 不可连接输出 Python 完整 traceback。R34 修复为：
- 每个 Episode 状态独立处理；无法读取时 driver_state=UNKNOWN、diagnostic_error=DRIVER_STATUS_READ_FAILED、error_type=异常类名；其余 Episode 已读结果保留；不回退伪造 JSON 权威数据。
- 状态未知、服务读失败或全局 OS 锁容量快照失败，结果 diagnostic_incomplete=true，production_authorization=false；容量失败时不提供虚假 observed_available。
- plan/status 只读命令一旦诊断不完整返回非零状态码 3，而不是表现为“计划可启动”。正式 start 仍强制 --ack-real-production。
- 真正进入 start_episodes 前必须成功读取全部 Episode Owner；任何一次连接失败直接返回 MULTI_EPISODE_DRIVER_OWNER_UNVERIFIED，starts_attempted=0，不提前启动另一个 Episode，不打印连接堆栈或凭据。
- 原来已有 RUNNING Episode 不重复启动，其他 Episode 独立启动、无跨 Episode rollback 的安全规则继续保留。

**注意**：没有在缺少授权环境时强行连接实际生产 MySQL 做在线验证；本轮对这些回退路径使用隔离 FakeConnection 和 Mock Driver 实测。

### 槽 3：共享硬容量和真实失败恢复回归

不重写现有 global_image_capacity.image_permits 实现。其 OS 级 slot-00..04 锁、线程局部 Gateway 内层复用、批量全占或全不占、进程崩溃自动释放，是唯一单机共享容量权威。

以下测试通过时方可验收：
- tests/system/test_multi_episode_global_image_capacity.py：隔离真实多进程 OS 锁，两个 Episode 同时持有 2+3 张、第 6 张无法取得，释放后才能继续；涵盖 batch、direct CLI 和 crash 情形。
- tests/system/test_shared_generation_attempt_budget.py：Attempt 重试预算（2）保持共享权威。
- tests/system/test_runtime_recovery.py：现有失败恢复规则不能因这轮诊断变更被破坏。
- tests/system/test_storyos_multi_episode_plan_never_starts.py：plan/status 始终不会启动付费任务。

### 槽 4：Task/Attempt/Worker/Writer/容量证据矩阵

修改 web-console/src/components/views/RuntimeRecoveryInsight.tsx，使用**现有 Ant Design Descriptions**，复用 R33 恢复安全诊断，不新造 UI 组件。

两个生产详情抽屉显示 5 个清晰检查点：Task ID 与 Lease、MySQL Generation Attempt / fencing、Worker 心跳、Episode Writer Owner、全局图片容量。
- 本机只读文件来源一律显示“未接入权威 Task/Attempt/Worker”，不会将阶段摘要当在线状态。
- 仅当非本地来源真实报告 execution_status/heartbeat 时，显示“接口报告”，但仍不宣称验证过 Task、Worker 进程身份或租约。
- 只可声明永久规则“全仓库全局最多 5 张”；实时持锁数未通过专用可信渠道接入 UI 前，必须说明**不能推断剩余名额**。
- 继续不提供开始、恢复、跳过门禁、生产重试等不授权按钮。

新增 web-console/scripts/test-r34-evidence-browser.mjs 及 npm run test:r34，真实 Chrome 以 1440/1024 两种尺寸点击工作流和监控详情：验证 AntD 5 行证据矩阵、来源清晰、实际 GET、没有 POST 和恢复按钮、440px Drawer 不越界。实际截图存放：
- .storyos-tmp/ui-qa/r34/storyos-r34-workflow-1440.png
- .storyos-tmp/ui-qa/r34/storyos-r34-workflow-1024.png
- .storyos-tmp/ui-qa/r34/storyos-r34-monitor-1440.png
- .storyos-tmp/ui-qa/r34/storyos-r34-monitor-1024.png

## 三、验收与安全说明

| 检查 | 预期 |
|---|---|
| Attempt 只读预检和完整性问题 | 所有隔离场景通过 |
| 跨 Episode Driver Owner / 缺连接 / 缺共享容量 | 不执行 Driver 启动，输出显式不可授权诊断 |
| 真实 OS 锁并发上限与失败恢复 | 使用现有隔离测试验收共享硬上限 5，保持原恢复契约 |
| R34 Chrome 生产证据矩阵 | 4/4，实际两个 Drawer × 1440/1024 |
| R33 工作流历史行为 | 4/4，含真实 GET 与身份一致性 |
| R28 一级页面 | 14/14，视图不回退 |
| R25 故事制作 / 作品详情 | 6/6，冻结布局保留 |
| TypeScript & Vite build | npm run lint 和 npm run build -- --base=./ |
| git diff --check | 提交前通过 |

### 本轮最终实测记录

- 后端隔离测试合并运行：**93/93 passed**（Attempt 只读预检、Driver Owner、plan/status 不产生模型调用、global_image_capacity 跨进程上限、共享 Retry Budget、Runtime Recovery）。
- R34 新控制台两页面 × 1440/1024：**4/4 通过**，包含 Ant Design 证据矩阵、真实 GET、缺失权威信息提示、无执行按钮、Drawer 不溢出。
- R33 原工作流/生产监控抽屉回归：**4/4 通过**。
- R28 七个一级菜单 × 1440/1024：**14/14 通过**。
- R25 故事制作与作品库：**6/6 通过**。
- `npm run lint`、`npm run build -- --base=./`：**通过**。
- 一次高并发 Chrome 回归遇到 `Inspected target navigated or closed`，不能认定为业务成功；已在减少并行浏览器压力后**顺序复测 R33/R28 均通过**。异常属于先前并发浏览器验收过程，不是通过跳过断言处理。
- 已查看本轮真实浏览器截图：`.storyos-tmp/ui-qa/r34/storyos-r34-workflow-1440.png` 与 `storyos-r34-monitor-1024.png`，其他两个宽度和页面组合亦有同目录截图。

## 四、后续 R35 阻塞项

P0：目前本机只读 API 仍只持有 Episode 阶段文件，不具备受控的 MySQL Attempt/Task/Worker/Driver Writer 真实在线来源。R34 不能自行开启它们或为 UI 伪造有数据；R35 须在明确授权的只读后端环境建立对应数据源，验证 episode_id 与 fencing、任务血缘、当前 Attempt、租约与心跳，再允许评估 Canary。

P0：跨主机和跨独立 Git 克隆不能借用同一个本机 OS 五图锁来声称分布式安全，仍需跨主机 MySQL/Redis Lease 的独立验收。

P1：用户授权真实生产 Canary 时，应按容量→Attempt→Provider Gate→Writer 验证顺序进行，必须单独获取实质生产授权，不在本轮执行。

## 五、版本治理

本轮只修改两个已有 Python 只读/启动保护脚本、两个相关测试文件、一个既有 AntD 证据组件、新 Chrome 测试、package scripts 和本验收文档；不修改原 Provider Gateway 的派发路径、不改 StoryOS 剧情和素材、不写生产 DB、不碰其他任务的未提交及未跟踪文件。所有 Git 操作只 staging R34 修改。
