# StoryOS R11 · 单机 Driver 持锁心跳只读观测

日期：2026-10-13
基线：c202a237
范围：现有 OS 文件锁 Writer 内部可选观察点 + 控制台只读观测，不新增 Writer 选举/分布式锁/调度系统。

## 目的和边界

从 R10 的 11/11 部真实作品、R9 MySQL SELECT-only Task/Attempt、R7 Redis Worker 心跳、R6 文件账本，推进到真正由持锁 Driver 本身产生的进程级心跳。此监测用于提示生产 Driver 报告的持锁状态；**不能声称只靠文件证据已验证某个时刻内核锁必然仍由该进程持有**，不等于 Provider 正在工作，也不批准新生产任务。

唯一 canonical Writer 入场依旧是 \`runner_state_store.acquire_lock\` 的原 OS 非阻塞文件锁；冲突返回 25，生产调用不变。监控端绝不尝试获取/释放/探测该锁。

## Producer

- \`episodes/_system/writer_owner_observation.py\`：增加独立、可选的小型本地观测文件 \`meta/runtime/writer-owner-observation.json\`。
- 真正的 \`persistent_runner_daemon.run()\` **获得 OS lock 成功后**才产生进程启动时间+随机执行 epoch+Episode 路径指纹，保存 \`HELD\`。
- 现有后台心跳刷新该文件，只有该 Driver 的原有 OS 锁生命周期才允许发布；退出时先停止心跳、写 \`RELEASED\`，再释放原 OS 文件锁。
- 观测文件使用已有 \`runtime_atomic_store.atomic_write_json\` 原子写入。观测失败是 fail-soft：**不能使正常制作失败、不能吞掉正常生产事件，也不介入 Provider/Redis/MySQL**。
- 该新增文件本身是 Runtime 自己的遥测记录；除它以外本轮不会改写已有作品任务、已批准媒体、账本、MySQL、Redis 或原有执行权。

## Reader / Web Console

- 只读 \`local_writer_owner_readonly.observe_writer_owner\` 使用固定相对路径、2 KiB 文件上限、symlink/path 检查；数据不可信时仅返回 UNKNOWN，不会读取其他文件。
- 正向判定必须同时满足：schema/source、原锁相对路径、随机 epoch 格式、规范 Episode 目录路径 SHA256 指纹、\`HELD\`、合法 PID、**OS 进程启动时间吻合**（避免 PID 重用）、明确时区的心跳年龄 -5～45 秒、二次读取确认文件未变。
- 前端/HTTP **不返回 PID、随机 epoch、物理路径或命令行**。列表显示“持锁心跳新鲜（自报）/未核验”，详情显示上次心跳年龄与数据来源限制。
- 状态 \`FRESH_PRODUCER_LOCK_CLAIM\` 只表示由 canonical Driver 在获取锁之后发布、进程身份仍匹配的**新鲜持锁报告**，不等于瞬间查询了 Windows 内核字节锁、不能替代 Writer admission、不能断言模型推理发生。\`kernel_lock_verified=false\` 与 \`provider_inflight_verified=false\` 永远保持保守，原 \`execution_status=UNKNOWN\` 不变。
- **已在运行的旧版 Driver**尚无新的观测 sidecar 时必须 UNKNOWN；不为测试这一监控而重启真实制作任务。下次使用原有 Driver 入口自然生效。

## 测试证据

- 真实 OS 两进程同 Episode 排他：锁持有期间新鲜报告，竞争者拿不到锁；正常 release 报告结束，系统锁可重获。
- 强制 kill Writer：即使旧 sidecar 时间仍新鲜，进程不存在就 UNKNOWN，系统自动释放 OS lock。
- 伪造旧 PID 启动时间、跨 Episode sidecar、未来/陈旧/无时区时间、symlink、超大文件、缺失文件，不产生错误在线声明。
- 在真正 \`persistent_runner_daemon.run\` 上以惰性 mock 替代 \`episode_runner.run_episode\`，验证锁获取后发布、拒绝锁时绝不发布、观察文件失败时生产完成仍返回 0；从未调用 Provider。
- Python R11/R10/R9/单机容量与权限回归：**87 passed, 12 subtests passed**；TypeScript/Lint/Vite PASS。
- Chrome 隔离端口 \`3193/19923\`：真实本机 11 部作品及 11/11 MySQL 身份；《婚礼前夜》20 帧、Task=1、最近 Production Attempt=60，当前 Driver 心跳 UNKNOWN，writer kernel lock verified=false，POST 403；实际截图 \`.storyos-tmp/ui-qa/real-driver-owner-r11-1440.png\`，187598 bytes。

## 风险、未做事项

不声称“完全在线执行可视化”：当前旧版 Worker/Driver 仍可能正在任务运行，但未生成新的 sidecar 时本观测显示 UNKNOWN。若 Producer 在发布后崩溃/重启，读端检查 OS 进程创建时间会拒绝旧快照；如观察文件发生 I/O 错误也 fail-closed。不可使用此状态触发自动重试、支付、发布、任务派发。

未来如需更强的当前锁授权证明，只能使用经过正式设计/验收的单机进程内只读服务/权威进程协作证明，不可用监控端抢锁或将 PID 作为唯一凭据。不新增集群架构。

## 运维

原控制台仍从 \`http://127.0.0.1:3100/\` 查看。R11 安全合入后仅重载只读 Console/API。新增 Driver 心跳需要**未来对应 Episode 通过原入口运行新版 persistent_runner_daemon**；绝不为 UI 验收调用真实付费模型。
