# StoryOS R10｜真实 Story Critic 权威封闭、Driver/Attempt 诚实观测与四槽极速

2026-10-13｜用户明确授权原生 Codex 正式生产。此轮不跳过 Story/Visual Gate，不调用 OpenCodex。

## 真机阻断复盘（主工作区，不是模拟测试）

- 作品：`episodes/15_天界生活日常/01_天界普通女生的一天`，MySQL Stage = `STORYBOARD_LOCKED`，图片 Attempt = 0，Watchdog 任务为 `INSTALLED`，当前无活跃 Driver。
- 2026-10-13 13:57–14:18 多次真实 Driver 循环的 `CREATIVE_STORY` 失败代码为 **3**，不是成功生成的回执；上一轮修复了旧 WORK shadow 挡住 native 路由，但这不是全链路关闭。
- 从真实 MySQL Runtime Checkpoint 读取：`CREATIVE_STORY` 旧 DAG `REUSED` 记录的 `attempt=161`，旧 `_run_targeted_review` 在当前周期错误使用 `162` 调用 Story Critic。该 Critic 正常尝试只有 1–2 次，继续自动重试既无效也有重复付费风险。
- 单独查询真实正式 Story Review：**权威记录缺失**；第 1 次 `story-semantic` 请求是 `AWAITING_PRODUCT_REVIEW`；第 2 次 `FINALIZED`，但引用的最终审核文件不存在。必须修复/核验实际审核证据，不能将请求的状态字段当成审核 PASS，也不能生成第 162 次。审计结论：`FINALIZED_REVIEW_WITHOUT_CANONICAL_PROOF`。
- Driver 临时状态输出 `NEVER_STARTED` 可能只是存储的易失记录丢失；Win Task Scheduler 历史曾确证 Driver 运行。R10 将它表述为 `DRIVER_HISTORY_UNVERIFIED`，不是断言从未启动。

## 槽位 ①：Creative Story 原生 Codex 持有的正式审核尝试

新增 `episodes/_system/story_review_attempt_admission.py`（纯函数）将**DAG 调度次数**与**真实 Critic 尝试**分离。对真实审核请求 1/2、官方 `story-semantic` Review 权威作出只读状态选择：

- 无历史且无正式 Review 才可能给出首次审核尝试 1，不能因 DAG 循环编号 162 而发起 162 次。
- 有等待中的正式请求先走原审核完成路径，不假装新请求。已终结但无官方 Review 直接返回 `22/HUMAN_REQUIRED`（不自动无限重试）。
- 仅有真实第 1 次失败审核权威才可能选择正常第 2 次；任何第三次以上必须具备专用授权及来源 SHA，**普通生产授权不是可绕过这个条件的凭证**。
- `runtime_dag._run_targeted_review` 在任何 subprocess/model 调用前执行选择和验证；若生命周期冲突明确报 `STORY_REVIEW_ATTEMPT_AUTHORITY_BLOCKED:...`，不给无意义的 `rc=3` 连续技术重试机会。

新增 `scripts/storyos_story_review_readonly.py`：在原生 runtime.env 环境下读取 MySQL Stage、真实 Story Review 和 request lifecycle，再次复验 MySQL Stage；不给付费准入，不写库不改文件。模型执行仍必须由正规 Story Critic Runner 控制。

## 槽位 ②：Driver 与 Watchdog 生命周期

`storyos_autonomy_production_probe.py` 不再把无 volatile Driver 记录的 `NEVER_STARTED` 误判为“用户从未启动”，明确 `DRIVER_HISTORY_UNVERIFIED`。不宣称可自动重启，也不改变已有严格 watchdog policy：失败 rc=3 或未知持锁 owner 不自动派发，仍要求独立权威恢复证明。

## 槽位 ③：MySQL / Provider 防重复

只读联合探针额外检查 `unverified_status_assets`（与 `outcome_unknown_assets` 同样需 reconcile），并区分 `attempt_rows > 0` 的历史付费尝试与从未创建 Attempt 的状态。无合法表结构/负数 Attempt 行数不输出可靠结果。不给 `may_retry_paid_attempt`，不提交任何图片 Provider，仍保留原全局五图许可和 Attempt CAS。

## 槽位 ④：四段极速 + 全量压力 + Git 安全治理

```powershell
python scripts/storyos_autonomy_fast_test.py --slot story-critic-authority
python scripts/storyos_autonomy_fast_test.py --slot driver-lifecycle
python scripts/storyos_autonomy_fast_test.py --slot paid-attempt-proof
python scripts/storyos_autonomy_fast_test.py --slot r10-integrated
python scripts/storyos_autonomy_fast_test.py --slot all --stress

# 实机只读，从当前主工作区执行
python scripts/storyos_story_review_readonly.py "episodes/15_天界生活日常/01_天界普通女生的一天"
python scripts/storyos_autonomy_production_probe.py "episodes/15_天界生活日常/01_天界普通女生的一天"
python scripts/storyos_retired_worktree_gc.py plan
python scripts/storyos_retired_worktree_gc.py branches-plan
```

所有测试为离线 Mock/Fixture + Runtime 压力回归。R10 不能声称首张真实图片或无人值守 `PUBLISH_READY` 已完成；修复的是此前使生产反复故障的正式 Story Review 尝试权威链。保留主工作区全部用户修改和既有 runtime 证据，不强删任何在用 Worktree。
