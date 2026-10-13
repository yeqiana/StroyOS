# StoryOS 单机真实生产监控 R6 · 只读文件证据联动与验收

日期：2026-10-13
基线：`a7be4818`
隔离分支：`refactor/storyos-single-node-observability-20261013`

## 用户目标

控制台不负责发起、暂停、恢复或重试真正生产；现有 StoryOS Python Runtime 仍由原有入口执行。控制台持续观察**真实的既有生产证据**，覆盖作品当前阶段、20 帧账本、队列历史、Checkpoints、审核、历史 Runner 记录。绝不将离线文件当成在线 Worker 或 MySQL / Redis 最终授权证据。

## 已落地的唯一只读数据流

原工作区 `episodes/<series>/<episode>/meta/` → 固定文件白名单、8 MiB 单文件读取上限、路径/symlink 检查 → 现有 `LocalEpisodeFileStatuses.get_episode_status` → 原有 `GET /api/v1/runtime/status?episode=...` → Web Console「生产监控」→ 作品详情抽屉。

固定读取来源：
- `episode-state.json`：canonical 业务阶段。
- `production-queue.json`：队列条目状态及完整历史条目总数（包含 `superseded`）。
- `production-ledger.json`：每帧账本状态、已批准资产*记录*、历史尝试条目数（**不等于真实模型调用次数**）。
- `runtime-checkpoint.json`：最后 16 个步骤记录。
- `runtime-runner-state.json`：仅作为*保存时 Runner 状态*，永远 `verified_live=false`。
- `story-semantic-review.json`、`frame-semantic-review.json`、`release-semantic-review.json`、`visual-lock-baseline-review.json`：只输出保守状态和审核通过布尔值。

所有文件读取失败均明确记录 `source_errors`，不会清零当成零帧成功；不暴露原始日志、Prompt、模型输出、密钥、物理路径或文件内容。详情 `execution_status=UNKNOWN` 与 `heartbeat.health=unknown` 维持原有保守行为。除原有媒体 URL，新增详情只返回按白名单筛选的代码、计数、状态、时间。

**自动刷新**：阶段列表每 15 秒读取一次；仅打开的作品详情每 10 秒重新读取，页面隐藏时暂停，单在途请求且切换作品时废弃旧响应。页面宽度允许查看完整 20 帧明细和队列/审核/步骤。

## 本机真实证据和测试

- 原工作区扫描 20 部作品，其中 **7 部**有逐帧真实账本/队列证据。
- 测试用真实《婚礼前夜》数据：20 帧记录、91 条队列历史（包含 64 条 superseded、27 条 generated），仅展示已落盘信息。
- 隔离 pytest `test_local_workspace_readonly.py`、`test_local_episode_monitoring.py`、`test_storyos_local_approved_media.py`：**12 passed、8 subtests passed**；追加单机队列、五图容量、审核/恢复回归后 **33 passed、8 subtests passed，0 failed**。
- 隔离前端 `npm run lint` / `npm run build` 通过。
- 实际 Chrome 隔离端口 `3188/19918`：从真实 20 部作品中选取确有 20 帧记录的作品，点击「生产监控」→作品→详情，校验 20 帧表格和“不保证在线”的说明；写请求仍返回 HTTP 403，测试 **PASS**。
- 浏览器截图：`.storyos-tmp/ui-qa/real-production-monitor-r6-1440.png`（隔离 Worktree，真实 Chrome 1440px），浏览器退出后不保留测试 HTTP 服务。最终隔离截图 **152539 bytes**，Chrome 与 API 联动重测通过。

## 尚未覆盖——不可宣传“完整实时监测”

本次解决的是**已落盘的真实生产进度和历史**，并不是生产调度器、Worker、MySQL/Redis 的全量在线监控。

继续实现真正全量实时监测还需要在只读授权下接入：MySQL 的 Task/Generation Attempt/Trace 和 Activity 读取、Redis Worker 心跳和队列、Writer 围栏授权状态、Provider 回调/错误码，以及审核和最终资产一致性校验。必须保留准确的 Episode / Task / Attempt ID 关联，明确数据采集时间、来源和过期机制；无证据时显示 UNKNOWN，不自动推断执行成功。无需新建集群或自动生产流程。

本轮不触发付费模型，不改真实数据库/Redis，不运行 Writer，不改变正式生产门禁。