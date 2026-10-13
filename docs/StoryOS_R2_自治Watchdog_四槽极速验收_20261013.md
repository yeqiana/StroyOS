# StoryOS R2 四槽自治 Watchdog 与极速测试验收（2026-10-13）

## 目标与真实边界

本轮在上一轮原生 Codex 常驻 `runtime_driver` 基础上，新增 **仅限单机、同一 Git Common Directory** 的恢复 Watchdog：

- 不重新实现 Runtime DAG、图像 Scheduler、Review、Generation Attempt 或 Stage；
- 不使用 OpenCodex，不制作视频，只有原生 `CODEX_MANAGED + CODEX`；
- `plan` 只读，`once`/`watch` 必须显式 `--ack-real-production`，否则绝不启动；
- `NEVER_STARTED` 不由 Watchdog 首次启动，必须先有用户明确批准的正式 Driver；
- 只在 Driver 已退出（rc=0）或 PID **明确已死**、没有 Provider 非终态风险时尝试恢复；`RUNNING` 等待；`OUTCOME_UNKNOWN`、Active Attempt、MySQL Schema/Stage 不可信、人工门禁、非零退出或任何不确定性均禁止启动；
- 独立 Windows/Linux OS 文件锁跨进程/Worktree 排斥同 Episode 的两个 Watchdog，写入 **Git Common Directory** 下的本地预算 journal（不是第二阶段权威）；
- 两轮独立 `storyos_codex_managed.preflight` 后才预留预算，再调用已有 `runtime_driver start --resume`。Provider、Writer Owner 和全局 5 图 Permit 仍由原正式 Gateway/Driver 校验；
- 恢复默认每 24 小时 2 次、两次至少间隔 300 秒；预算在 Driver 派发**之前**原子持久化，Watchdog 崩溃时也视作已占用。Journal 损坏、时钟回拨、跨 Episode 身份不符时全部 fail-closed；
- 绝不擅自重置 UNKNOWN、Attempt、审核、Revision 或内容返修预算。

**注意**：这是受控单机恢复 Watchdog，不是已验证的跨主机 Writer Fencing。原 R37 的在线 Task/Attempt/Worker/Writer 五域可信读端与分布式 CAS 仍需独立落地。未运行付费生产 Canary，不得声称整部作品已能真实无人值守到 `PUBLISH_READY`。本轮也**没有为用户安装开机任务或常驻服务**，`watch` 的宿主必须由已授权的持久进程托管。

## 生产使用入口（本轮未执行）

```powershell
# 只读评估，无自动启动，无生产计费；失败原因可复核
python scripts/storyos_autonomy_watchdog.py plan "episodes/00_独立篇/<剧集>"

# 只在已有正式 Driver 且已经明确授权恢复的情况下，执行一次安全 Tick：
python scripts/storyos_autonomy_watchdog.py once "episodes/00_独立篇/<剧集>" --ack-real-production

# 授权并持续观察：每 300 秒触发一次 Tick，需要由用户态持久服务托管
python scripts/storyos_autonomy_watchdog.py watch "episodes/00_独立篇/<剧集>" --ack-real-production --interval-seconds 300
```

本地 journal 保存在 `<Git Common Directory>/storyos-autonomy-watchdog/`，跨本仓 Worktree 共享，未写入生产 MySQL。这个 journal 仅表示“本 Watchdog 自动尝试启动 Driver 的次数”，绝不等于真正生图 Generation Attempt 配额。

## 四槽 TDD 极速测试：每次推进必须运行

| 槽位 | 极速入口 | 极端用例 |
|---|---|---|
| ① Watchdog 策略 | `python scripts/storyos_autonomy_fast_test.py --slot watchdog` | 已运行、未启动、异常退出、未知 PID、错误 Executor 和 Stage |
| ② 持久预算 | `python scripts/storyos_autonomy_fast_test.py --slot budget` | 冷却、滚动24h、崩溃预留、损坏/跨身份 Journal、NaN/时钟回拨 |
| ③ 生产执行权 | `python scripts/storyos_autonomy_fast_test.py --slot authority` | 无授权零副作用、真实跨进程 OS 锁、二次权威漂移、数据库临时断线 |
| ④ 故障注入闭环 | `python scripts/storyos_autonomy_fast_test.py --slot e2e` | 崩溃→恢复→运行→二次崩溃→预算耗尽；启动回执不可信不假成功 |

改动某槽位，先用对应测试产生 **RED → 修改 → GREEN** 记录。改动四槽交界面必须追加：

```powershell
python scripts/storyos_autonomy_fast_test.py --slot all
```

整轮改造结束执行：

```powershell
python scripts/storyos_autonomy_fast_test.py --slot all --stress
```

`--stress` 保留前轮 Canonical Full-Auto、失败恢复、Host Loop、全局图片容量和原生 Codex 路由回归。全部 pytest 通过隔离依赖注入实现，不启动真实 Driver、不消耗图片配额或生产 MySQL 状态。

## 下一轮验收缺口

1. 通过明确授权的用户态常驻 Carrier/Task Scheduler 实现 Watchdog 自启动，且具备不会二次安装/双开/重启风暴的极速测试；
2. 真实可信 Writer Lease/Fencing、在线 Authority 接线，并进行单机双进程/异常断电恢复验证；
3. 经明确付费授权的原生 Codex 单帧 Canary → 多帧/审核/字幕完整图文产物 → `PUBLISH_READY`，实际持久运行验收后才能宣称生产无人值守已完成。
