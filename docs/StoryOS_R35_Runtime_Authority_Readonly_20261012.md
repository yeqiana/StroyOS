# StoryOS R35 · Task / Attempt / Worker 权威只读接入与四槽验收

日期：2026-10-12
分支：story-platform-v3-rever
基线：R34 提交 a97d6ce8
模式：四槽滚动；所有后端数据库读取均采用隔离 FakeConnection 验证；本机真实 HTTP 只读取工作区状态文件，不开启任何付费 Provider、Writer、发布与生产 MySQL/Redis 写入。

## 一、总体结论与真实性边界

R35 完成了**真实 HTTP/API → Episode 身份核对 → 权威只读来源判定 → Web Console 证据矩阵**的可运行工程链路。新增 GET /api/v1/runtime/authority?episode=...。

当前浏览器接入的是 127.0.0.1 本机只读服务。它确实访问了 API 并验证本机 20 条状态摘要、Episode 查询身份，但 **Task / Attempt / Worker / Writer 在线权威信息、共享 OS 槽占用在此服务中全部 UNAVAILABLE**。服务如实返回 scope=LOCAL_READ_ONLY_EVIDENCE、production_authorization=false、can_start=false、can_retry=false、can_publish=false、model_calls=0。绝不以本机历史阶段推断 Worker 在线、Attempt 可重试、Writer 已持租约或剩余五图许可。

正式 Platform API 的 authority controller 只有受信任的 Composition Root 显式注入 RuntimeAuthorityEvidenceService 才会注册；默认 503 CAPABILITY_NOT_CONFIGURED 而非伪造成功。本轮**未获取也未尝试获取线上生产数据库授权**，不能把 R35 说成线上执行数据已部署、生产 Canary 通过。

## 二、四槽落地

### 槽位 1：Platform 权威只读接口

- platform/api/routes.py：新增 GET /api/v1/runtime/authority。
- platform/api/controllers.py + service_ports.py：增加 RuntimeAuthorityApiController、服务 Port 和统一 API envelope；Episode 无效或跨作品返回错误，服务异常只暴露稳定错误码，不泄露 DSN、密钥或文件绝对路径。
- platform/operations/runtime_authority_evidence.py：五个域 task / attempt / worker / writer / capacity，统一 return read_only/provenance/observation 时间；受信任 reader 返回数据必须符合 Episode 身份、固定来源代码、UTC 时区、120 秒时效和显式 verified；不符合就 UNAVAILABLE。报告始终没有执行授权。
- platform/api/default_app.py：显式 opt-in 装配参数 runtime_authority_service；不配置时对应 Controller 保持缺失并由现有 Dispatcher 返回 503。

### 槽位 2：MySQL Episode 身份和安全读端适配

- platform/operations/runtime_authority_readers.py：MySqlAuthorityReadOnlyReaders 通过**调用方注入的已有连接**查询。代码不创建 MySQL 连接或使用开发环境默认连接。
- 每次读端请求都核验 SELECT DATABASE() = STORY_OS_RUNTIME 及 lower_case_table_names = 0，再用 MySqlEpisodeRepository.unique_owner_by_namespace 核对唯一 Episode namespace、ACTIVE disposition 和存储 UID。随后仅以该 UID 执行 WHERE EPISODE_ID=%s 参数化 SELECT。
- Task：返回仅 task_count；Generation Attempt：仅 attempt_count / unresolved 是否存在。未在 UI 暴露 JSON payload、lease token、原始 owner/worker id、SQL 连接字串或任意数据库列。
- 通过独立 FakeConnection 验证全部 SQL 是 SELECT，数据跨 Episode、库名大小写漂移、重复 namespace、不合法计数、异常凭据均不能转为 VERIFIED。
- 只有明确授权的后端部署方可传入 adapter + permit_authority_reads=true。LocalReadOnlyDispatcher 即使构造时意外传入 readers，也因本机状态源隔离直接 fail-closed，不会运行读库函数。

### 槽位 3：Worker / Writer / OS 容量和恢复门禁

- Worker 心跳、Writer fencing 仍需后续具备 TTL、owner 校验能力的正式授权读端，**本轮不拿 Redis 键或 Driver JSON 推断在线**。
- AdvisoryCapacityReadOnlyReader 可复用现有 global_image_capacity.snapshot 提供单机 Git Common Directory 内的真实 OS 锁瞬时忙闲数据，但必须是同一来源、标记 advisory_snapshot_only，且 busy+available=5。即便观察为 0/5，它仍不是 Permit，绝不授权派发、预留 Attempt 或发布。
- 保留 R34 永久契约：不同 Episode 可并行；同一 Episode 一个 Writer；全仓库所有图片入口合计最多 5 张；先有共享 Permits，再消费 MySQL Generation Attempt。真实并发、跨主机分布式锁以及付费双 Episode Canary 尚未授权。
- 后端 93 项 Runtime / Attempt / 共享容量安全回归独立运行，检查不破坏原有硬门禁。

### 槽位 4：Web Console 真正读取证据

- web-console/src/api/platformApi.ts：定义 RuntimeAuthorityReport / EvidenceItem / 五域状态和 GET 客户端；请求可被 AbortSignal 取消。
- web-console/src/api/runtimeAuthorityPresentation.ts：前端二次校验 episode_ref、scope、five-domain evidence、read_only、production_authorization=false、禁启动/重试/发布。伪造来源或本机来源报告 ONLINE 会被直接拒绝。
- web-console/src/components/views/RuntimeRecoveryInsight.tsx + WorkflowDetailPanel.tsx + RuntimeAuthorityPanel.tsx：原 Ant Design 440px Drawer 继续保留。点击时并行 GET 阶段详情 + authority；不发 POST。新“R35 · 身份绑定只读”行准确显示本机已验证 Episode，但五类在线权威尚未接入。真实授权读端未来报告才按域显示 count / 已校验的来源；Worker 与 Writer 缺完整核验时不能宣称在线或可重新执行。
- 禁止假封面、假 Worker、假进度与“一键恢复”按钮。权限失败时保留 R34 证据缺口说明。

## 三、实测与自动验收

| 测试 | 通过目标 / 实测 |
|---|---|
| tests/platform/test_runtime_authority_evidence.py | HTTP 契约、未授权 local、跨 Episode、伪造来源、时效、异常脱敏、默认 503 与 opt-in 接线 |
| tests/platform/test_runtime_authority_readers.py | SELECT-only Task/Attempt、schema identity、unique Episode、只读 OS 快照和 fail-closed |
| tests/platform/test_platform_http_server.py / test_webconsole_live_http_readonly.py | 真实 HTTP envelope、接口身份、权限、Status 路由兼容 |
| tests/platform/test_web_console_api_contract.py | 从历史 Vue-only 路径迁移为 React + Ant Design + 当前 Platform API 真实契约；不改变产品业务 |
| Platform 相关五组 pytest 合计 | **62/62 通过** |
| tests/system: Attempt/Owner/Permit/Retry/Recovery | **93/93 通过** |
| npm run test:r35:guards | **3/3 通过**，本机伪造和跨作品拒绝、未来授权只读展示 |
| npm run test:r32:boundary | **5/5 通过**，本机读端/媒体/权限 |
| npm run test:r35 | **4/4 真实 Chrome**，工作流与生产监控 × 1440/1024、实际 GET、身份一致、五域 UNAVAILABLE、无 POST |
| npm run lint / npm run build -- --base=./ | TypeScript、Vite 生产构建通过 |
| R28/R25/R34 历史浏览器 | 使用顺序执行，避免并发 Chrome CDP 切换 renderer |

真实截图存放于 .storyos-tmp/ui-qa/r35/：
- storyos-r35-workflow-1440.png
- storyos-r35-workflow-1024.png
- storyos-r35-monitor-1440.png
- storyos-r35-monitor-1024.png

本地服务直接 API 和同源代理都返回同一 Episode 的 5 个 UNAVAILABLE；不存在 Episode 明确 404；未授权事件流保持 403。展示的 20 条阶段和 60 张批准图片仍来自主工作区磁盘而非在线调度状态。

## 四、阻塞清单与 R36 建议

1. **P0 / 授权阻塞**：正式 Platform API 尚未配置 runtime_authority_service。R35 只提供安全可插拔的只读 Task/Attempt 源，Worker/Writer 没有高可信租约血缘与心跳 TTL 适配。需要部署方提供授权的只读 MySQL/Redis 账户及受控 Runtime Owner API，并明确各状态 Source of Truth。
2. **P0 / 真实生产动作**：启动/恢复/出图/发布仍未授权，必须先验证当前 Generation Attempt fencing、唯一 Writer、共享图片 Permit 和预生产门禁，之后再另行授权受控 Canary。
3. **P1 / 更广运维监控**：建立带鉴权的只读 Task/Attempt/Worker/Writer 丰富详情、审计关联 Trace；不将 Redis heartbeat 孤立缓存用作“在线”。
4. **P1 / 跨主机**：本机 OS 锁不代表跨克隆/跨主机分布式安全；仍需 MySQL/Redis Lease/Fencing 的跨主机专门验收。

## 五、提交保护

仅提交 R35 本次新增的 Platform 读端、服务 Port、HTTP Controller/Route、默认可选接入、局部本机只读服务支持、前端 client/证据展示、针对 React 的历史测试迁移、新浏览器脚本和本验收文档。

不改已有故事制作/作品详情布局；不改生产 Provider Gateway、Generation Attempt 写端、全局硬容量、MySQL/Redis 正式配置、业务素材，不处理其他任务的 reports/account-pattern-registry.json 和无关未跟踪文件。提交前检查 git diff --check，提交后检查指定路径干净。
