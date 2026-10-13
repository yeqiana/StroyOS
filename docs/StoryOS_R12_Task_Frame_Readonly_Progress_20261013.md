# StoryOS R12 · 真实 Task / 逐帧生产 Attempt 关联只读监控

日期：2026-10-13
开发基线：ef5cfad4
分支：refactor/storyos-single-node-r12-real-progress-20261013
范围：继续沿用 R9 的专用 SELECT-only MySQL 3307、R10 的 11 部正式 Episode 目录身份、R11 的 Driver 进程持锁心跳观察。**不启动制作，不发图片 Provider、不改 MySQL/Redis/Writer 锁。**

## 真实数据契约与发现

已对正在使用的 **11 部真实作品**执行本机 \`3100\` 已授权只读 API 汇总：
- 当前数据库的 Task 主要为 \`RUNTIME_CHECKPOINT_STEP\` / \`RUNTIME_CHECKPOINT_META\`，其 \`FRAME_NO\` 基本为 NULL，不可凭 Task 行伪造“正在生图第几帧”。
- Task 当前持久化状态含 HOST_WAIT、PASS、CURRENT、BLOCKED、REUSED、FAILED，\`CURRENT\` 是保存的旧状态，不等于执行中。
- 单帧历史来自 \`TB_PRODUCTION_ATTEMPT\` 的 FRAME_NO、ATTEMPT_NO、STATUS、CREATE_TIME、ELAPSED_MS；\`ELAPSED_MS\` 是历史 Attempt 耗时，不是当前任务已运行时间。
- \`TB_GENERATION_ATTEMPT\` 使用**仓库 namespace**而非 \`TB_EPISODE.EPISODE_ID\`，当前 11 部作品的该表匹配样本为 0，不得推断从未调用模型。若未来有 \`OUTCOME_UNKNOWN\` 行，只作为**人工待核对提示**，绝不自动重试。

## 实施

- 新增 \`platform/operations/local_production_progress_readonly.py\`，仅对 \`available=true\`、数据库 Episode 身份核验和 SELECT-only 授权核验的 R9 投影计算记录，不引入新的 SQL 语句或凭据渠道。
- \`GET /api/v1/runtime/status?episode=LOCAL_...\` 加入 \`recorded_production_progress\`：最近保存 Task、最近记录的制作帧、样本各帧最近一次 Attempt、已记录耗时、数据年龄和 Generation \`OUTCOME_UNKNOWN\` 样本数量。
- 对时间仅接受含时区的 ISO 8601，禁止无时区、未来超过 5 秒或超长年龄作为有效时间；真实数据库 \`DATETIME\` 已按原有 MySQL schema 的 UTC 语义转换。
- MySQL 每类最多读 60 条；对逐帧历史只显示这 60 条样本涉及的帧，**不是**整个 Episode 所有制作 Attempt 的完整历史，也不按最大帧号推断最新任务。
- 无论 R11 的进程自报心跳是否新鲜，只要缺少与 Task/Generation Attempt 同一个真实执行 epoch 和 Provider 派发边界的可信关联，\`verified_current_task=null\`、\`verified_current_frame=null\`、\`provider_call_verified=false\`、\`stalled_verified=false\`、\`execution_in_progress_verified=false\`。
- 控制台在 Driver 心跳和原 MySQL 明细之间增加「制作进度 · Task / 逐帧记录关联」，显示保存的 Task 类型/状态、距上次更新、最近保存的生图帧、距帧记录时间、每帧样本最新结果和历史时长。强调“卡住尚不能核验”。

## 实际验收

- 合成 SQL 记录 7 个专项测试：CURRENT 不冒充在线、历史时长与距今时间分离、最新一帧来自生产事件顺序而非最大帧号、重复帧只取最近尝试、OUTCOME_UNKNOWN 不触发生产、数据库身份/权限失效不回传行、未来/无时区时间保守拒绝、最多 60 条采样。
- R12 + R9/R10/R11 + Writer OS 锁 + 全局五图容量的 Python 综合回归：**54 passed，9 subtests passed**；TS lint 和 Vite build 通过。
- 真实隔离 Chrome 端口 \`3194/19924\`：11/11 MySQL 双身份匹配，R11 Writer 当前 UNKNOWN，所有写操作 HTTP 403。
- 《婚礼前夜》最新 Production Attempt 样本内：最近记录的是第 **20** 帧，最近 60 条 Attempt 涉及 **14** 个不同帧；还有原 R6 文件账本 20 帧、91 条历史队列、MySQL Task 1 条、Generation Attempt 0 条匹配。这里的 14 帧是截断样本覆盖，不是只做了 14 帧。
- 截图：\`.storyos-tmp/ui-qa/real-task-frame-r12-1440.png\`，**185676 bytes**，由真实 Chrome 生成。

## 剩余不可声称的“完全实时制作”

没有真正 Task/Generation Attempt 关联到 R11 Driver 的同一可信运行周期时，**无法正确回答当前调用的模型、当前在生成哪个帧、实时调用已持续多少秒或到底是否卡死**。数据更新时间很旧可能是历史完结或等待人工，不能自动判为故障。下一阶段优先通过现有生产调度/Provider 边界增加小型、可信、带执行 epoch 与逻辑资产身份的*原生产进程内遥测*，再以只读方式观察；绝不能由监控自己生成状态或重试。

## 安全

未触及真实生产表写入、Redis、已有帧图片、模型调用、支付、正常 Writer admission，也未重启实际 Driver；只在独立工作树修改只读投影、API、前端以及测试/文档。安全合入主分支前，应先逐项备份和校验所有未提交文件；只在测试通过时重启 3100/19117 两个只读控制台服务。
