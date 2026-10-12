# StoryOS Web Console R33 · Runtime 读端、任务恢复安全诊断与四槽验收

日期：2026-10-12
分支：story-platform-v3-rever
基线：R32 Git 4899067b
模式：受控非付费、只读生产接线验收。**本轮不授予任何正式生产指令、重试、发布、生图或 Runtime Writer 权限。**

## 一、范围与四槽任务

| 槽位 | 本轮落地 | 真实性边界 |
|---|---|---|
| 1 Runtime 接口 | 走实际 GET /api/v1/runtime/statuses 和 GET /api/v1/runtime/status?episode=...，增加本机能力就绪报告 | /healthz=200 仅说明 API 服务可用；不能用阶段记录推测在线 Worker |
| 2 状态追踪 | 工作流和生产监控两个 Ant Design Drawer 显示同一套生产恢复安全诊断；按 episode_ref 核对详情身份 | 后端没有提供实时执行或心跳时显示 UNKNOWN，不从阶段强行推断执行 |
| 3 门禁与失败恢复 | 只读恢复分类器覆盖本地文件/隔离数据/UNKNOWN/人工介入/阻塞/FAILED/BLOCKED/RETRYING/运行与完成，所有分类 canStartRecovery=false | 即使 auto_recoverable=true 也必须由授权 Runtime 复核 Owner、Attempt、门禁与全局图片 permits，不能提供重试按钮 |
| 4 浏览器体验 | Chrome 1440px 与 1024px 逐一点击两个详情抽屉、检查真实 GET、信息和只读行为、窗口宽度、截图 | 不重构 R28–R32 已冻结布局与 Story Canvas |

## 二、核心改造

### 1. 单一失败恢复判断（R33）

文件：web-console/src/api/runtimeRecoveryAssessment.ts

只读判定顺序：

1. source 为本机作品文件或 isolated-test：无论后端标记如何，恢复资格一律未知；不推导 Worker、Writer 或预算。
2. detail 未返回或 execution_status 为 UNKNOWN：恢复不可判定；必须核对权威执行源。
3. needs_user=true 或存在非空 blocking_reason：须人工介入。
4. RETRYING：按“后端报告已有重试过程”处理，禁止前端重复创建 Attempt。
5. FAILED/BLOCKED 且 auto_recoverable=true、needs_user=false：仅标记“候选，待授权”，不下发任务。
6. FAILED/BLOCKED 证据不足：恢复资格未确认；不允许盲重试。
7. RUNNING/COMPLETED/WAITING 等其它状态：仅展示来源状态，不做恢复决定。

所有路径返回 canStartRecovery=false。不将心跳字段“unknown”解释为健康；无任何可执行按钮。

新增 runtimeDetailMatchesEpisode：实际详情必须返回与当前所选 episode_ref 完全一致的身份，否则视为扩展详情不可用，杜绝跨 Episode 状态、异常原因或恢复标记混接。

### 2. 两个生产排障抽屉一致

- web-console/src/components/views/WorkflowDetailPanel.tsx
- web-console/src/components/views/RuntimeAuthorityPanel.tsx
- web-console/src/components/views/RuntimeRecoveryInsight.tsx

沿用 Ant Design Drawer、440px 宽度与现有文字、分割线 Token；展示“恢复安全诊断 / 只读建议 / 未授权执行”。详情通过既有平台 GET API 读取，不增加生产动作端点和隐藏的 POST 请求。

截图在本机忽略目录：

- .storyos-tmp/ui-qa/r33/storyos-r33-workflow-1440.png
- .storyos-tmp/ui-qa/r33/storyos-r33-monitor-1440.png
- .storyos-tmp/ui-qa/r33/storyos-r33-workflow-1024.png
- .storyos-tmp/ui-qa/r33/storyos-r33-monitor-1024.png

### 3. 实际本机 Runtime 能力审查

新增 web-console/scripts/test-r33-runtime-readiness.mjs，仅允许在 http://127.0.0.1 的本机服务查询 GET。

观察结果：

| 能力 | 实测 | 可以证明什么 |
|---|---|---|
| /healthz | HTTP 200 | 本机 API 进程在线；不是生产 Worker |
| /api/v1/runtime/statuses | 20 / 20、HTTP 200 | 20 条主工作区只读状态文件摘要 |
| /api/v1/runtime/status | HTTP 200、详情 episode_ref 匹配 | 对应 Episode 的阶段证据；execution_status=UNKNOWN，heartbeat=unknown，auto_recoverable=null |
| /api/v1/runtime/events | HTTP 403 READ_ONLY_LOCAL_EVIDENCE | 此本地环境无审计 Event 授权 |
| /api/v1/agents | HTTP 403 READ_ONLY_LOCAL_EVIDENCE | 此本地环境无 Agent Registry 授权 |
| 启动、重试、正式生图、发布 | **未调用** | 不具备生产动作授权，未做 Canary |

生成：.storyos-tmp/ui-qa/r33/runtime-readiness.json。该报告同时明确记录 can_start_workflow / can_retry_generation / can_modify_stage / can_auto_recover / can_publish 均为 false，避免将网页“有数据”误判为能执行。

## 三、测试与验收

新增：

- npm run test:r33:safety：恢复安全 14/14；Episode 详情身份核对 5/5。
- npm run test:r33：真实 Chrome 四场景 4/4；工作流和监控两页面 × 1440/1024。断言点击详情后确实发出 GET /api/v1/runtime/status、显示来源为本机状态文件、诊断 fail-closed、没有非 GET API 或恢复按钮、Drawer 不越界，生成对应真实截图。
- npm run test:r33:readiness：本机真实读端与权限边界 2/2，输出只读报告。

兼容：

- npm run test:r32:boundary：本机读端、图片与写操作权限 5/5。
- npm run test:r28：七个一级页面 × 1440/1024，14/14。
- npm run test:r25：故事制作与作品详情 Chrome 6/6。
- npm run test:r22：生产监控及工作流抽屉等 4/4。
- npm run test:workflow：工作流在线/离线读端 2/2。
- npm run test:local-real：20 条主工作区只读状态和未知心跳来源一致。
- npm run test:responsive：四组适配 4/4。
- npm run lint 和 npm run build -- --base=./：类型/生产构建成功。

验收不能替代正式在线 Runtime 的容量、Writer 租约、幂等调度、同 Episode 单 Writer、跨 Episode 并行与全局最多 5 张图片许可测试。

## 四、未解的生产授权前置和 R34 建议

P0：正式 Environment 的 Agent Registry、Event/Trace 数据面，以及执行读端的 Writer Owner、当前 Generation Attempt、Job Queue、心跳来源、Lease Fence 尚未在本地验证。它们不能通过本地静态文件或测试夹具造假。接入须使用已授权、可审计的独立环境。

P0：真正的失败恢复须由生产 Runtime 复核 canonical Episode 阶段、预生产视觉/故事门禁、已消费 Attempt、共享图片容量上限和重试预算，完成纯只读 Canary 准备检查后才能单独申请生产演练权限。

P1：未来可加持授权凭据的只读 Task/Attempt/Worker 详情；R33 没有新增任何未经后端实现的“启动”“一键重试”按钮。

## 五、版本边界与保护

本轮限定 4 个组件/状态文件、3 个专项测试脚本、package scripts 与本验收文档；不改任何生产 Runtime、Provider Gateway、MySQL/Redis、正式作品文件、已有故事 Canvas、其它一级菜单布局。不同并发任务留下的 reports/account-pattern-registry.json 与未跟踪路径原样保留，Git 仅定向 staging 本轮文件。

验收结束需核对 git diff --cached --check、TS、Vite build、Chrome 截图与提交后工作区范围。
