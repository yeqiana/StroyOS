# StoryOS 单机 R8 · MySQL Task / Attempt 严格只读监测

日期：2026-10-13
开发基线：\`8ce6f548\`
隔离分支：\`refactor/storyos-single-node-r8-mysql-readonly-20261013\`

## 用户目标

继续使用现有 StoryOS CLI、Driver 和原有 AIGC 生产入口，不在控制台发起生产。控制台只观察真正的 Task、Production Attempt 和 Generation Attempt，且绝不能把旧 RUNNING 数据当作 Worker 在线。保留 R6 文件证据与 R7 Redis 心跳的新鲜度检查。

## 已接线功能

- 原有 \`GET /api/v1/runtime/status?episode=LOCAL_...\` 只读详情新增 \`mysql_monitor\`（未接通时准确返回 UNAVAILABLE）与 \`writer_owner_observation\`（始终 UNVERIFIED）。
- 只在 **\`STORYOS_LOCAL_MONITOR_MYSQL=1\` 显式开启，且指定专用账号** 后尝试访问固定 \`127.0.0.1\` 数据库。不使用 StoryOS 正式业务账号、root、默认凭据或生产连接池。
- 专用变量：\`STORYOS_MONITOR_MYSQL_RO_USER\`、\`STORYOS_MONITOR_MYSQL_RO_PASSWORD\`、\`STORYOS_MONITOR_MYSQL_RO_DB=STORY_OS_RUNTIME\`，可选 \`STORYOS_MONITOR_MYSQL_RO_PORT\`。**不应将实际凭据写入 Git、测试脚本或前端环境变量**。
- 服务先 \`SHOW GRANTS\`，验证账号的授权文字仅包括 SELECT、SHOW VIEW 或 USAGE，且没有 GRANT OPTION / ADMIN OPTION；否则拒绝进一步查询。然后 \`START TRANSACTION READ ONLY\`，所有数据读取均是参数化 SELECT，不插入、不更新、不加锁、不调用 Stored Procedure。结束必做 rollback/close，异常时只返回无敏感信息的失败代码。
- Episode 必须从当前本机已验证的 \`episode-state.json\` 解析稳定仓库 namespace 和业务编号，并在 \`TB_EPISODE\` 中匹配**唯一**、两者全部相同的数据库记录；多条/不匹配都拒绝。Task 和 Production Attempt 用受信任的 DB 主键；Generation Attempt 用实际 Runtime 的稳定**仓库 namespace**，不可混用业务编号、标题或哈希 \`LOCAL_...\`。
- 三类最近记录各限制 60 条，只展示状态、帧号、序号、错误码/分类与耗时等白名单字段；不读取/回传 Prompt、Provider 密钥、模型原始响应、Owner ID、Lease、Token、逻辑资产原始路径。
- Web Console 只读抽屉新增三类记录与来源/权限提示。未配置时明确显示“未授权开启”，没有证据不能解释为“当前无任务”。

## 实际环境检查与安全边界

当前 Windows 电脑常见 MySQL 端口 \`3306\` 没有监听，未发现 \`STORYOS_MONITOR_MYSQL_RO_*\` 的专用只读配置；因此 **没有访问真实 MySQL，也没有验证当前生产表确实含哪些行**。此时运行控制台仅能准确显示“未接通”，不能显示真实数据库行。

**Writer OS 文件锁**：当前主 Driver 以 OS 文件锁进行单 Episode Writer 准入。锁文件的存在、磁盘 Runner 状态以及 PID 都不能证明持有者当前持锁；仅靠测试 \`LK_NBLCK\` 抢占锁也会改变竞态，因此这轮**不探测或短暂持有实际生产锁**。界面明确标记“未验证”。

MySQL \`RUNNING\` 等状态代表查询时数据库保存的状态，不是有效 Worker 心跳、当前 Writer 围栏，也不是付费生图成功证明；不开放生产按钮。

## 独立验收

- 专用 SELECT-only 账号权限拒绝、MySQL 不可用、不合身份、名称路径边界、三种不同 ID 映射、真实 Generation Attempt 的 \`OUTCOME_UNKNOWN\` 保守展示、未知错误不泄漏信息，均使用**模拟数据库连接**执行，未访问生产 MySQL。
- R8 + R6/R7 + 单机 Writer 锁与全局五图容量集成回归：**47 passed，7 subtests passed**。
- TypeScript 检查及 Vite build 均通过。
- 实际 Chrome 隔离端口 \`3190/19920\`：打开真实 20 部作品中的《婚礼前夜》20 帧与队列历史，验证“专用 MySQL 只读连接未授权开启”和“Writer 执行权未验证”，Redis 心跳来源保守，POST 返回 HTTP 403，测试 PASS。
- 真实截图：\`.storyos-tmp/ui-qa/real-mysql-monitor-r8-1440.png\`，浏览器实际生成 **225623 bytes**。

## 下一步真正接通的前置

1. 经用户/管理员明确批准，在实际目标 MySQL 上创建一套专用 **SELECT-only** 监控账号，仅授予 \`STORY_OS_RUNTIME\` 中 \`TB_EPISODE\`、\`TB_TASK\`、\`TB_PRODUCTION_ATTEMPT\`、\`TB_GENERATION_ATTEMPT\` 的 SELECT 权限（或等效最小权限）。不让本轮工具创建用户或更改授权。
2. 从安全的本机运行环境注入上述单独监控凭据与显式开关（不得混用生产读写账号），验证目标数据库可连、Schema 对齐、身份和权限证明无误。连接失败仍保持 UNAVAILABLE。
3. 针对 Writer 实时执行权，优先由现有 Driver 提供只读且可证明时效、Owner 和围栏的观测接口，而不是抢锁、猜 PID 或仅查文件。
4. 延续单机部署，不新增分布式服务，也不因为监控出现 UNKNOWN 自动重试真实 Provider。

## 不包含

未部署到外部生产；不启动图片生成或支付 Provider；不写 Redis、MySQL 或 StoryOS 作品文件；不改变 Writer 门禁；不进行网络暴露或外部端口访问。
