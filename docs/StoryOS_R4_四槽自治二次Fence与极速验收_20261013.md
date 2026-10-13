# StoryOS R4 四槽自治：付费派发二次 Fencing / Windows 载体验真 / Frame01 证据双检

2026-10-13 · 基于 `story-platform-v3-rever`

## 本轮落地

**槽位一：真实图片 Provider 派发前 Fencing。** 在官方 `image_generation_gateway.py` 的单帧与批量路径中，维持“共享图片 Permit → MySQL Generation Attempt commit → **read-only live fence recheck** → Paid Provider → mark_observed”的顺序。新增 `generation_attempt_authority.validate_committed_dispatch` 和 `validate_committed_dispatch_many`，均验证同一个 MySQL 资产的 Attempt Index、当前递增 Fencing Token、Lease Token 和 `DISPATCH_COMMITTED` 状态；批量在同一 DB 事务下验证全部帧。二次验证失败时拒绝 Provider 调用，**已经消耗的 Attempt 不退款、不改写 UNKNOWN、不视为成功**，失败按原 terminal/失败记录路径处理。验证发生在发图之前，无法消除“检查后至网络调用”的最后一个极短竞态，也不能代替完整 Writer 单调 Fencing。

**槽位二：Watchdog 与 Windows Carrier 核验。** 原 Windows Task Scheduler 只按可执行文件、参数、用户名判断已安装；R4 加入实际 trigger 类型、trigger 用户、WorkingDirectory、`IgnoreNew` 单实例设置与 Enabled 状态。缺字段和伪造/更换触发器的任务不得报告可信 `INSTALLED`，不得卸载非本任务。Watchdog 在两轮 MySQL/Attempt/Driver 预检之间额外比较 Codex 路由、MySQL 证据、创作/视觉锁权威，变化时返回 `AUTHORITY_CHANGED`，不保留新的重试预算。

**槽位三：原生 Codex Frame01 Canary 证据双检。** 现有 `storyos_autonomy_canary.py plan` 仍严格只读；现在在 Frame01 evidence 生成前后再次运行 canonical 原生 Codex/DB/Attempt `preflight`，两次报告不完全一致直接拒绝；如 Frame01 evidence 声称属于其他 Episode 亦拒绝。即使全部检查成功也只返回 `EVIDENCE_ONLY` 和 `can_dispatch_image=false`。账号图片工具调用权限、真实付费生图和像素审核**尚未执行**。

**槽位四：每步极速测试和故障联合验收。** R4 新增四项单槽测试（Provider Fencing、Carrier、Frame01、联合安全），覆盖 Fence 过期、批量帧原子核验、篡改计划任务、Codex 路由漂移、MySQL Attempt 活动、Frame01 身份串线。跨阶段集成故障注入验证 “伪造 Windows 载体 + Frame01 串线 + 付费调用前 Fence 失效” 全部 fail-closed。保留早期 R1-R3 所有极速测试与共享五图容量测试。

## 每次推进与完整交付的命令

```powershell
# 每个槽位修复后立刻极速测试
python scripts/storyos_autonomy_fast_test.py --slot dispatch-fence
python scripts/storyos_autonomy_fast_test.py --slot carrier-integrity
python scripts/storyos_autonomy_fast_test.py --slot frame01-fence
python scripts/storyos_autonomy_fast_test.py --slot r4-integration

# 四槽合并后的联合极速测试
python scripts/storyos_autonomy_fast_test.py --slot all

# 本轮改造结束时完整的离线压力回归
python scripts/storyos_autonomy_fast_test.py --slot all --stress
```

测试调用全部为 mock / 隔离 Fake Provider；**没有付费调用、没有触碰正式 MySQL 或生产工作区**。可单独运行 `python -m pytest -q tests/platform` 复核平台锁规则。所有测试必须真实执行、保留退出码，失败不得标记绿灯。

## 仍需补齐的真实生产验收

- 正式 Driver/Owner Writer Token 在所有业务数据写端的 monotonic fencing 原子拒绝（MySQL 与 Redis 的跨主机 Owner epoch），不能用仅有的 Redis Token 或每帧 Attempt Fence 冒充。
- Windows Task Scheduler 在正式交互用户权限下的实际注册、重启后启动、停机恢复。
- 另行明确付费授权后的原生 Codex 单帧 Provider/像素回执/审核 Canary，再逐帧至 `PUBLISH_READY`；目前这三项都没有真实生产验收。
