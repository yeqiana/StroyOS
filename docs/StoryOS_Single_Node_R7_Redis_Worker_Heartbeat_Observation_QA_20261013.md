# StoryOS 单机 R7 · 真实 Redis Worker 心跳只读监控验收

日期：2026-10-13
基线：\`936b5943\`
范围：不启用付费生图/任务启动/审核写入/生产 MySQL 写入，不新增集群，保留 R6 的真实 20 帧账本只读监控。

## 目标与证据语义

原控制台已能从 20 部本机作品读取已落盘生产证据，其中 7 部具有逐帧账本/队列记录。R7 新增**全局 Redis Worker 心跳的只读观测**，不是 Writer 围栏证据，也不代表任何特定 Episode 正在生产。

单机原生启动器 \`web-console/scripts/launch-local-real-console.mjs\` 只对它启动的本机 API 子进程设置显式开关 \`STORYOS_LOCAL_MONITOR_REDIS=1\`。读取源固定 \`127.0.0.1:6379\`、Redis 所选 DB 和 \`storyos:worker:*:heartbeat\`；只调用 \`SCAN\`、\`GET\`、\`TTL\`，不使用写指令，不输出 Worker ID、Redis key、密码、模型参数、任务内容和异常详情。只读扫描最多 16 轮、256 条；不完整时标记缺口，绝不把缺席等同于没有任务。

- \`fresh_heartbeats\`：Worker ID 与 key 一致、status=ONLINE、TTL 为正、心跳时间含明确时区、时间年龄在 -5～120 秒之间。
- \`stale_heartbeats\`：身份和时间可解析，但 TTL/在线标志/时间窗口不满足条件。
- \`unverified_heartbeats\`：JSON 格式、身份、时区、字段类型不可核验。
- 即使 \`fresh_heartbeats>0\`，\`worker_execution_verified=false\`、\`writer_owner_verified=false\`、\`task_attempt_verified=false\`，不升级为真正在运行的作品任务。

## 本机 Redis 真实观测

只读探测时 Redis 接口可访问，发现 **1 条**带正 TTL 的 worker 心跳记录。该记录 \`heartbeat_time\` **没有时区信息**；因此无权判定心跳年龄与活跃状态，严格归类 **无法核验**。采用系统本地时区计算得到的约八小时偏差仅是未经证实的解释，不作为监控判据。

## Web Console

新增 \`GET /api/v1/local-monitor/workers\`，仅允许本地 Host、同源、无查询字符串、GET；其他请求 403。界面「生产监控」的阶段证据视图新增 Redis 心跳观测条，展示新鲜、过期、无法核验数和样本覆盖度；随页面只读刷新间隔更新，失联时立即清空旧数据而非继续显示旧“在线”。

## 安全验收

- 后端独立 Fake Redis：TTL 仍有效但时间过期、无时区、未来时间、ID 不匹配、无 TTL、错误 JSON、连接异常和扫描上限。
- HTTP：GET 仅聚合证据，POST 返回 403，外部 Origin / 跨站 / 查询字符串拒绝，未接通时不触发 Redis。
- TypeScript/Vite 构建通过。
- 隔离 Chrome：临时 \`3189/19919\` 真实读取本机 Redis 与 20 部作品、点击生产监控和逐帧详情，验证两条数据通道各自来源清晰、Worker 当前执行权仍 UNKNOWN，HTTP POST 403。
- 实际截图：\`.storyos-tmp/ui-qa/real-worker-heartbeat-r7-1440.png\`。
- 单机综合安全回归：**44 passed、11 subtests passed、0 failed**；实际 Chrome HTTP/页面：**PASS**，截图大小 **153623 字节**。本机真实 Worker 样本 **1 条（fresh=0 / stale=0 / unverified=1）**。没有用跳过项冒充通过。

## 尚未实现的“完整实时生产监控”

生产 MySQL Task/Generation Attempt、Writer 锁执行权、Redis 中有可靠 Episode/Task 身份关联的运行态队列和支付/生图 Provider 调用状态，均**没有**可信只读数据源与明确授权，不能推断或虚构。下阶段优先：

1. 由真正生产心跳写入端统一输出带时区的 UTC \`heartbeat_time\`，并使用 TTL，须另行测试并在授权后变更 Writer，而不是监控端自行补时区。
2. 用只读 MySQL 账号单独接入 Generation Attempt/Task，不通过可写生产账号；保证 Episode / Task / Attempt 多重身份。
3. 明确 Writer OS 锁/围栏的实际有效执行权证据，不能从文件存在或 PID 推断；保持单机不新增分布式架构。
