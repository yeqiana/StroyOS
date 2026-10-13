# StoryOS R7 · 四槽自治安全收敛与极速验收（2026-10-13）

本轮基于 StoryOS 正式主分支独立 Worktree 进行；真实 Codex CLI 已登录，但没有模型执行、付费生图、数据库修改或 Watchdog 计划任务安装。只使用官方原生 Codex/Runner 通道，不允许 OpenCodex。

## 槽位 1：已退役 Worktree / 本地分支的原子清理

旧版 `storyos_retired_worktree_gc.apply_branches()` 对同一分支读两次 SHA 之后执行 `git branch -d`，在最后一次比对与删除之间仍可能被另一个并行 Codex 任务改写。R7 增加最终 Worktree 占用复核，以 `git update-ref -d refs/heads/<branch> <expected_sha>` 实施 Git ref 服务器端原子 compare-and-delete，SHA 不一致自动拒绝。删除只发生于已合并本地+远端主线、超过 72 小时、已解除 Worktree 占用、非归档分支，且用户明确允许的范围；默认仍是只读 `branches-plan`。Git worktree 使用情况的查询与更新引用不是单一分布式原子事务，故仍不能声称没有任何其他机器/进程并发竞态。

本轮实际只读盘点：登记 Worktree 数量可被其他任务同步增加；未发现满足退役门禁的对象，故**不执行清理破坏性动作**。绝不为了减少数量而 force-remove 或 -D。

## 槽位 2：Provider 付费边界的显式权威确认

Gateway 的 `validate_committed_dispatch` / `validate_committed_dispatch_many` 必须**显式返回 Python True** 才可以进入 `call()`。返回 False、None 或不完整的批量 `commit_dispatch_many` 回执，均抛出 `AttemptDenied`，不调用任何付费图片 Provider，不归还已经消耗的 MySQL Generation Attempt。批量还校验已提交资产键集合与请求一一对应，杜绝半批次提交后调用完整图像批次。保留上一轮对超时 `OUTCOME_UNKNOWN` 及已确认批量回执保护。

## 槽位 3：原生 Codex CLI 与 Runner 相同执行文件证据

除原有只读 `codex --version`、`codex exec --help` 和交互用户 Runner 授权上下文，本轮对两者的**CLI 版本 + 规范化可执行文件路径指纹**进行核对。仅公开 SHA256 指纹，不输出账号路径、auth.json、令牌、环境变量。发现路径/版本矛盾则 `BLOCKED`，尚无完整路径证据时只能证明授权上下文存在，不能证明 Runner 和本地 CLI 是同一可执行文件。

`storyos_autonomy_canary.py plan` 要求上述一致性明确为 True，且仍需两次 canonical MySQL Stage/Attempt/Driver/原生路由预检。成功仅为 `EVIDENCE_ONLY`；继续 `may_start_paid_production=false`、`can_dispatch_image=false`、模型调用数 0。CLI 登录不等于可生成订阅图片的真实资格。

## 槽位 4：RED→GREEN、故障注入与完整压测

新用例覆盖 Git ref 在最终删除时被别的任务改写或签出、Provider 单帧/批量核验返回 False、批量提交回执不完整、Runner CLI 被 PATH 指向另一套版本或位置、以及跨三个边界的联合拒绝。

```powershell
# 每次推进完一个槽位立即运行独立极速测试
python scripts/storyos_autonomy_fast_test.py --slot gc-atomic
python scripts/storyos_autonomy_fast_test.py --slot gateway-proof
python scripts/storyos_autonomy_fast_test.py --slot native-route
python scripts/storyos_autonomy_fast_test.py --slot r7-closure

# 整轮四槽联合极速测试
python scripts/storyos_autonomy_fast_test.py --slot all

# 最后执行完整 R1-R7 + 原有 Runtime/5 图容量压力回归
python scripts/storyos_autonomy_fast_test.py --slot all --stress

# 不调用模型、不泄露凭证的真实用户 Runner/CLI 检查
python scripts/storyos_autonomy_native_ready.py

# 清理前先只读筛选：禁止清理在用 Worktree
python scripts/storyos_retired_worktree_gc.py plan
python scripts/storyos_retired_worktree_gc.py branches-plan
```

未完成生产级验收：Writer 在所有跨主机业务写端的单调 Epoch Fencing、Windows Watchdog 的实际重启，以及获得付费授权后的单帧真实生图和 M00 Pixel Review 至 `PUBLISH_READY`。任何离线 Mock 绿灯不得替代正式生产验收。
