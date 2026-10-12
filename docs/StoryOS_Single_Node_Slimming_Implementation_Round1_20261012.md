# StoryOS 单机瘦身实施 · 首轮四槽范围

日期：2026-10-12
实施分支：`refactor/storyos-single-node-integrated-20261012`
干净基线：`f03c0d4b`。
对照评审：R38 隔离分支 `66a58688`，`docs/StoryOS_R38_Single_Node_Architecture_Slimming_Review_20261012.md`（仅历史分支保存）。

## 用户确认的唯一目标

一台电脑、单实例 MySQL、单实例 Redis；不同 Episode 可以并行，同一 Episode 同时只能有一个可写 Runner；本机所有图片派发共同最多五张；正式出图经 Generation Attempt 事务与统一 Gateway；不加 Redis Cluster、Sentinel、跨主机共享容量、远端 Provider Consumer、临时 Worker Grant。

## 四个开发槽位：尽量少改、优先复用

| 槽 | 范围 | 预期 |
|---|---|---|
| A · Owner | 修复既有 `runner_state_store.acquire_lock` 的空文件预写竞态，验证真实进程抢锁、进程退出释放、不同 Episode 并行 | 一套现成 OS Owner Lock，不加 Redis Writer 层 |
| B · Attempt | 从 R38 仅移植超预算后不再查询缺失旧历史记录的精确 bugfix | 保留预算消耗、UNKNOWN、MySQL 最终权威 |
| C · 五图 | 把过去 R38 真正跨 Git Worktree 文件锁竞争测试移到单机回归 | 不改现有 `global_image_capacity` |
| D · 审计 | 明确排除 R38 分布式实验模块，验证正式运行入口不引用它们 | 不移植 R38 全量，不动 Web Console |

## 真实运行入口结论

`persistent_runner_daemon.run` 已调用 `runner_state_store.acquire_lock(episode)`；忙时退出码为 `25`，`finally` 释放 OS 锁。不要误用 `EpisodeLockManager` 作为已接入的正式 Driver 锁。文件锁从同一 Episode 的本机进程共享，不同 Episode 相互独立。

`global_image_capacity.image_permits` 本来就是本机跨 Git Worktree 五图门禁，Gateway、Batch、Worker 和 CLI 保留原有执行链。没有必要再创建 Redis ZSET 五图租约。

## 不在本次变更内

正式 MySQL/Redis 数据修改、真实付费 Provider、自动重试 `OUTCOME_UNKNOWN`、删除 R38 历史实验分支、调整 Web UI、合并脏主分支，都不在本次范围内。本分支实施的是「可回滚的小修复 + 测试证据」，不是完整产品上线。

## 验收和回退

四槽在各自 Worktree 跑目标测试后定向 cherry-pick 到单机集成分支，执行单机 Owner / 五图 / Attempt / Gateway / 多 Episode / Runtime 回归；真实 MySQL 的旧测试只能在严格隔离准入后实写。不可把 skip 算通过。

异常时只回退单机集成分支本轮提交，不删除生产文件锁、生产数据或历史 R38 实验代码。

综合测试：见下方正式回归结果。


## 首轮实施最终验收记录

- 单机集成分支去重回归：**117 passed、12 skipped**。跳过的为未打开 TEST_ONLY MySQL 准入的既有真实写库用例，不能计作通过。
- 已经单独在**全新 TEST_ONLY MySQL 容器**执行 `test_generation_attempt_authority.py`、`test_authority_refresh_budget.py`、`test_candidate_budget_lifecycle.py`、`test_phase5a_fake_subpath_e2e.py`：**26 passed、0 skipped**；容器按 `finally` 自动销毁。
- 四个独立槽位专项首轮：A（Owner 文件锁与 Runtime 桥）**6 passed**；B（Attempt 预算/SQL 准入保护）**5 passed**；C（真实 OS 跨 Worktree 五图回归）**16 passed**；D（单机模块边界/运行时归属）**14 passed**。各槽后来在集成分支扩展回归、按文件去重为 117 项。
- 曾尝试额外执行 `test_detached_driver_contract.py`，因当前 WebCodex Runner 为**非交互 Windows 环境**，无法提供该用例必须的交互式用户身份，导致其 Setup 报 `TASK_CARRIER_INTERACTIVE_USER_UNAVAILABLE`。没有为了测试变绿而伪造生产身份。**交互桌面下的 Task Scheduler Carrier 启动专项仍未验收**，与本轮真实双进程 OS Owner 抢锁验收分开。
- 真正改动的 Runtime 文件**仅两份**：`runner_state_store.py` 修复锁文件创建时先写后锁的竞态；`generation_attempt_authority.py` 修复超预算后不应依赖历史明细存在。其他新增仅测试及本说明。
- 原始开发分支和 R38 实验隔离分支均不受影响，本轮未调用付费 Provider、正式 DB/Redis、实际发布或运行正式生产故事。

## 下一轮单机瘦身重点（不拓展分布式）

1. 在允许的**交互式 Windows 测试桌面**独立验证 Task Scheduler Carrier 重启与抢锁（不可在非交互测试环境绕过）。
2. 验证完整的真实故事功能链：新建 → 分镜 → Visual Lock → 排队生图 → Review → 作品详情（不真实生图或发布，使用非付费模拟）。
3. 在确认现有 canonical Driver Owner Lock 已覆盖正式入口后，单独清理已证实无调用的旧锁适配器，始终先补安全回归再删文件。**不必为了代码行数减少而移植任何 R38 分布式模块**。
