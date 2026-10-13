# StoryOS R5 四槽推进：历史分支治理、Provider 结果不确定、原生 Codex 登录与极速回归

2026-10-13 · 基于 `story-platform-v3-rever`；全程隔离 Worktree、只读能力检验与离线测试，无付费生产调用。

## ① 退役 Worktree / 分支治理

- `python scripts/storyos_retired_worktree_gc.py plan`：默认只读。必须同时证明目录为受控 `.worktrees/` 或 `.storyos/worktrees/` **直接子目录**、Git 已登记、Branch 已合并本地和远端主分支、无未提交与未跟踪内容、最近使用和提交均超过 72 小时、无进程指向该目录，才是可退役的候选。
- `python scripts/storyos_retired_worktree_gc.py apply --ack-retired-cleanup --max-count 5`：明确批准后逐个**再次核验**，仅使用 `git worktree remove`（不用 `--force`）及 `git branch -d`（不用 `-D`）。
- `branches-plan`：只读列出已合并到本地+远端主线、超过 72h、没有被任何登记 Worktree 签出的本地临时功能分支；不包含 `archive/`、`release/`、主分支、远端分支。
- `branches-apply --ack-retired-cleanup --max-count 8`：严格二次核验之后，只删符合规则的本地已合并分支。操作本轮实际删除 8 个安全候选；**未删除任何 Worktree**（当时 70 个登记对象中 0 个完全达标）。
- 即使用户允许清理，也不自动清理活动任务、共享生产资产或不确定证据。

## ② Provider 回执丢失 → OUTCOME_UNKNOWN

正式 `episodes/_system/image_generation_gateway.py` 现在明确区分：
- Provider **尚未返回**而出现错误：保留原来的 `FAILED_AFTER_DISPATCH` 分类流程；
- Provider **已成功返回**，但之后 `mark_observed` 未能持久化：尝试写入 `OUTCOME_UNKNOWN`，而不是错写 `FAILED_AFTER_DISPATCH`；批量路径对已提交帧同样处理。
- 任何持久化失败都**不会返还已消耗的 Attempt**；禁止“没看到回执→自动重试付费生成”。Provider 实际网络超时可能产生不确定输出，仍需由相应的 Host/Attempt Authority 按既有规则处理。
- 不改变共享五图 Permit、MySQL Fence 或原生 Codex 生图入口。

## ③ 原生 Codex 真实登录上下文只读验收

`python scripts/storyos_autonomy_native_ready.py` 联合检查：
- CLI 真实可执行文件版本与 `codex exec --help` 必要参数；Windows 优先 `codex.cmd`，不是不可被 `subprocess` 直接执行的 PowerShell `codex.ps1`；
- StoryOS 交互用户 Runner `codex_auth_present` 等健康指标；将已安装、Runner 授权上下文和模型授权严格分开；
- 即使返回 `NATIVE_AUTH_CONTEXT_READY`，也固定 `model_entitlement_verified=false`、`may_start_paid_production=false`、`model_calls=0`。真实订阅模型调用/图片工具资格需要独立受控 Canary。
- 不使用 OpenCodex；不暴露 token、登录账号、DSN 或 CLI 的身份文本。

## ④ 每槽极速测试 + 终局压力回归

```powershell
# 每次推进对应槽位立即跑独立极速测试（RED→GREEN）
python scripts/storyos_autonomy_fast_test.py --slot retirement
python scripts/storyos_autonomy_fast_test.py --slot provider-receipt
python scripts/storyos_autonomy_fast_test.py --slot native-login
python scripts/storyos_autonomy_fast_test.py --slot r5-integrated

# 每四槽融合后先跑联合极快套件
python scripts/storyos_autonomy_fast_test.py --slot all

# 整轮改造完成后，包含 R1~R5 全部快测和历史 Runtime/
# Canonical Full Auto/共享五图容量压力回归
python scripts/storyos_autonomy_fast_test.py --slot all --stress
```

全部测试使用离线 mock / Fake Provider，任何真实付费生产、生图或正式数据库写入另需明确授权。单机登录 Runner 通过不等于真正无人值守达到 `PUBLISH_READY`。

## 尚需真实验收

1. 正式 User Task Scheduler 持久载体重新登录 / Windows 重启后的授权自动恢复验证；
2. Writer/Driver/Provider Gateway 全写端**单调 Epoch Fencing**，不能用独立的 Redis Owner Token 或逐帧 Attempt Fencing 代替；
3. 明确许可后运行原生 Codex 单帧实际图像生成功能、回执、真实 M00 Pixel Review，进而验证正式整部图文 `PUBLISH_READY`。
