# StoryOS 原生 Codex 持久生产与四槽极速验收（2026-10-13）

## 改造目的与当前交付

本改造不增加第二套调度器、不调用 OpenCodex、不引入视频生产，不改变 MySQL Stage / Generation Attempt / Review Authority，也不在测试中付费生图。主线仍是 `story_os.py` + `runtime_dag.py` + `runtime_driver.py`。

原 `scripts/storyos_codex_managed.py run` 为前台同步入口，调用会话结束就不能证明工作继续。新增 `start` 把已授权的原生 Codex 全自动任务交给仓库现有常驻 `runtime_driver.py start --resume`。只有只读 `preflight` 对正式数据库、模型客户端、用户态 Runner、Attempt、Episode Stage、Driver 状态返回 READY_TO_START，且显式携带 `--ack-real-production` 时才启动。此授权仍可能产生真实模型 / 图片费用。

Windows 直接 Breakaway 和交互用户 Task Scheduler carrier 都会把 `CODEX_MANAGED + CODEX` 作为枚举化命令行参数带进 Driver 子进程，并在加载本地正式 `runtime.env` 后恢复模式、移除 OpenAI 代理覆盖，避免任务重启后退回 WORK/OpenCodex。

只读复核新增安全恢复界限：

- `NEVER_STARTED`：可以首次启动；
- `EXITED` 且退出码 0：在全部 MySQL/Attempt/Stage 门禁仍为绿时，可以续跑；
- `ABNORMAL_DISAPPEARANCE`、PID 已证明 `DEAD`、没有退出码：先重新检查全部权威后可以恢复；仍由唯一 Owner Lock、在途结果认领和共享五图 Permit 保护；
- `RUNNING`、`UNKNOWN`、`ALIVE_NOT_BEATING`：绝不盲目双开；
- 已记录非零退出码，包括 HOST_WAIT 20、技术重试耗尽 21、人工门禁 22、硬停 23、能力等待 24、Owner 冲突 25 和异常 900/901：不进入自动重启循环；只读 `recover` 返回 `REMEDIATION_REQUIRED`；
- `OUTCOME_UNKNOWN`、活动 Attempt、MySQL Authority 未验证、模型 CLI 不兼容、身份串线：始终拒绝自动启动，不消耗新的 Generation Attempt。

这里的 `READY_TO_START` 不等于“原生图像能力实测通过”，也不等于 Review / Release 门禁已通过。**没有进行真实付费 Canary，也没有验证整部作品到 PUBLISH_READY。**

## 常驻生产入口（仅在正式本机用户态使用）

```powershell
cd D:/workspace/YeQianWorkSpace/yeqian/storyOS
python scripts/storyos_codex_managed.py plan "episodes/00_独立篇/<剧集>"
# 只有只读计划 READY_TO_START，并且用户已明确批准真实生产，才运行：
python scripts/storyos_codex_managed.py start "episodes/00_独立篇/<剧集>" --ack-real-production
```

旧 `run` 仍保留前台同步语义，`create` 仍是前台创建故事的入口。新作品的长驻启动需要先创建 Episode 并经过只读准入；不能把 `create` 冒充有持久 Driver 的完整无人值守。

## 每次推进必须执行的极速验收

按每槽 TDD：**先写会失败的测试 → 记录红灯 → 修复 → 当槽绿灯 → 四槽合并快测**。本地修改任何生产路径后按下列测试执行，不允许“只有 lint 成功”。

| 槽位 | 入口 | 必须覆盖的极端边界 |
|---|---|---|
| ① 原生入口与门禁 | `python scripts/storyos_autonomy_fast_test.py --slot entry` | 无 Ack、不兼容、UNKNOWN、已完成剧集、错误 Owner 不派发 |
| ② Driver 模式穿透 | `python scripts/storyos_autonomy_fast_test.py --slot driver` | Windows 任务 carrier 丢环境、代理污染、非零退出阻断 |
| ③ 故障与恢复 | `python scripts/storyos_autonomy_fast_test.py --slot recovery` | 40 组 Driver × Attempt × Schema，真 Host 等待不自旋 |
| ④ 创作审核与收尾 | `python scripts/storyos_autonomy_fast_test.py --slot closure` | 选择冲突、返修预算 0、未到 PUBLISH_READY 不能假成功 |

四槽极速统一命令：

```powershell
python scripts/storyos_autonomy_fast_test.py --slot all
```

改造合并前执行完整离线压力回归：

```powershell
python scripts/storyos_autonomy_fast_test.py --slot all --stress
```

`--stress` 额外包含全部 Canonical Full-Auto cases、Runtime Recovery、Host Loop、跨 Episode 共享五图硬容量实测。都是隔离测试，**不会连生产数据库或调用付费模型**。失败必须保留真实断言和退出码，不允许伪造成功回执。

## 未完成的“真正无人值守”条件

1. 当前 `start` 提供会话外常驻 Driver；**不包含无人值守自动创建新 Episode 后自动切到持久 Driver，也没有独立定时 Watchdog 在 Driver 崩溃后自动触发 `plan → start`**。自动 Watchdog 需要持久化且有上限的恢复预算、冷却时间、单 Writer Lease/Fencing 以及重启风暴测试。
2. R37 所述在线 Task / Worker / Writer 权威读端和真实 Fencing 仍需接线；不能用只读报告 0/5 作为 Writer Permit。
3. 需要在明确付费授权的环境里验收原生图片工具、视觉审核、MySQL Attempt、完整图文成品和崩溃续跑 Canary 后，才可以声明真实无人值守 PUBLISH_READY。
