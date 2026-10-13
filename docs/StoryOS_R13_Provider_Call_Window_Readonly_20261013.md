# StoryOS R13 · Provider 调用窗口与 Generation Attempt 只读交叉核验

日期：2026-10-13
基线：539e9131
分支：refactor/storyos-single-node-r13-provider-inflight-20261013

## 目的

R12 可以可信展示 **最近保存的** Task、逐帧 Attempt 和历史耗时，但没有真实执行中的帧。R13 要在原有单机生产入口内提供受约束的活跃生图证据，避免仅凭历史 MySQL RUNNING / DISPATCH_COMMITTED / PID 或文件时间戳错误报在线。

## 最小接入链

1. 原入口 \`persistent_runner_daemon.run\` 在成功获取现有 OS 文件锁并且 R11 Writer Owner HELD 遥测落盘后，调用 \`provider_inflight_observation.attach(episode, epoch)\` 注册**当前 Python 进程内**的 Episode + Driver 运行 epoch（不创建或修改权限/锁/选举）。
2. 原有 Driver 心跳仅顺便刷新同一个 Episode 的 Provider 在调用窗快照；任何失败均不阻断 Producer。退出时先清除 Provider 快照/本进程会话，再写 Driver RELEASED，最后释放原有 Writer OS 文件锁。
3. 已有 \`image_generation_gateway\` 仍保留 Generation Attempt durable commit、Fence 校验、全局最大五图容量。**只有在校验通过且即将进入原 \`call()\` 之前**才 \`with provider_inflight_observation.provider_span(...)\`。单图/批量多图共用；正常完成、异常、Provider 超时均在 finally 结束该窗口。监控不生成任何 Provider 请求，不改变报错、预算或重试。
4. Provider 快照 \`meta/runtime/provider-inflight-observation.json\` 使用同一原子文件写入工具：每次快照最多 5 条，只记录帧号、Attempt 序号、随机调用 span、UTC 时间、Owner epoch / PID / 启动时间与 Episode 指纹。不写 Prompt、图片数据、模型响应、Provider 密钥/Token、原始资产路径。
5. **监控是只读的**：R11 原 Driver HELD 心跳必须新鲜、进程 PID+启动时间在 OS 中吻合，Provider 快照必须来自同一 epoch/进程/作品，且 45 秒内更新、Provider span 仍在窗口中。同时 MySQL R9 已通过 SELECT-only 身份与授权，\`TB_GENERATION_ATTEMPT\` 对同一帧和尝试存在 **DISPATCH_COMMITTED、尚无 TERMINAL_AT、已记录派发时间** 的行。两份文件双读校验未变化后，才允许返回 \`FRESH_PROVIDER_CALL_EVIDENCE\`，展示多帧序号和进入调用以来的秒数。
6. 任何条件不符：\`UNKNOWN\`。不声称 kernel lock 已瞬时证明，不声称 MySQL Task ID 已与 Generation Attempt 一一关联，更不依长调用时间擅自判定“卡死”。监控发现 UNKNOWN 不自动重试。

## 实际验证

- 使用真正的单机 OS 文件锁（非假锁）和真正 \`persistent_runner_daemon.run\` 启动边界，替换有费用的 \`call()\` 为**无网络 mock**。模拟运行中第 7 帧产生经过三重核验的当前调用；call 返回后立刻撤销。没有启动真实图片模型，没有在真实生产库写入。
- 单图 Gateway / 并发双帧窗口 / Fence 校验拒绝 / Episode epoch 不一致 / MySQL 未提交或无权限 / stale 和无时区数据 / Provider 抛异常后窗口撤销 / 独立调度器无 Driver 会话不能冒充在线。
- 回归集合（R13 + R11 Owner + 单图 Gateway + Generation Context + 全局五图容量 + R9/R10/R12）：**63 passed, 5 subtests passed**。
- TypeScript lint 和 Vite build PASS。
- 真实 Chrome 隔离端口 \`3195/19925\`、MySQL \`127.0.0.1:3307\` 专用 SELECT 账号：11/11 部正式作品身份正常，当前没有新版 Driver 的 Provider 活跃会话，显示 \`UNKNOWN\`；R12《婚礼前夜》最近历史记录为第 20 帧、样本 14 个不同帧；POST 403；真实浏览器截图 \`.storyos-tmp/ui-qa/real-provider-call-r13-1440.png\`（202639 bytes）。

## 运维与未覆盖

- 原入口后续启动 **R13 版本 Driver** 才会自然生成调用窗；**不为了监控重启正在制作的 Driver**。旧版 Driver 与离线作品继续 UNKNOWN。
- 本地 Gateway 由同一 Driver Python 进程或其线程执行时可跨 R11 执行周期关联；若某种 Provider 路径改成完全独立进程且不经此 Gateway，R13 会 UNKNOWN（不得用路径猜测补齐）。
- 时间采样不是不可撤销瞬时事实：Provider 可能在观察后已经返回；UI 明示“近期执行窗口采样”，不把结果用于下一次调度、发放执行权、恢复故障、结算或预算更新。
- MySQL Generation Attempt 查询每部最多 60 条，新鲜调用恰好不在这 60 条样本中会 UNKNOWN；不猜测绑定。
- 真正 Task ID、是否卡死仍未核验，不伪造。这需要后续受审计的调度与 Task 关联，但不应阻断本轮可靠的调用帧展示。
- 安全合入前备份所有用户未提交文件并逐项比较 SHA256。只部署 3100 Web Console + 19117 只读 API；不得关闭/重启正在生产的 Driver、Provider、Redis 或 MySQL。
