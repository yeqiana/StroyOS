# StoryOS R3 四槽自治续推：Windows Carrier / Writer Token / 原生单帧证据 / 极速验收

2026-10-13，基于 `story-platform-v3-rever`。本轮只修改代码与隔离测试，不安装真实计划任务、不给任何 Episode 生成图片、不写入生产 MySQL、也不宣称真实 Writer 分布式 fencing 已投产。

## 四槽执行边界

**槽位一：可信 Windows Watchdog Carrier。** 新增 `scripts/storyos_autonomy_carrier.py`，只读 `plan/status`；只有用户明确 `--ack-real-production`、已核验交互账号和主工作区路径才允许 `install/uninstall`。任务在该账号登录时自动启动原有 `storyos_autonomy_watchdog.py watch`，Task Scheduler 的恢复设置仅针对 Watchdog 载体进程；Driver 恢复始终受上一轮 24h 两次预算与 300 秒冷却、MySQL/Attempt/Driver 双重只读审查保护。不覆盖已存在的计划任务，不从临时 Worktree 安装，不修改别人的任务。**尚未实际安装此任务，Windows 无交互登录时也不保证运行。**

**槽位二：原子 Writer/Owner 令牌。** `platform/state/episode_lock_manager.py` 的 `acquire_lease` 返回唯一随机 Token、NX+TTL、`renew` 比较 Token+EXPIRE、`release` 比较 Token+DEL，`RedisRuntimeStateStore` 通过 Lua EVAL 完成不可分割操作。旧版没有原子存储能力的 get-then-set 降级路径现拒绝取得锁；没有 Token 的旧 `release(episode)` 返回 False 而不是删除当前 Owner。**这是锁基础设施加固，尚未证明生产 Driver/Gateway 每次写入均带单调 Fencing Token，也不允许因此开放跨主机并发。**

**槽位三：原生 Codex Frame01 Canary 门禁。** 新增 `scripts/storyos_autonomy_canary.py plan`，调用已有 `storyos_codex_managed.preflight` 与 `storyos_native_frame01_preflight`，判断 Storyboard/MySQL/Attempt/模型客户端路由与单帧证据；成功只返回 `EVIDENCE_ONLY`，明确 `can_dispatch_image=false`。无独立图片下发，不能绕过共享五图容量、Generation Attempt、实际像素审核及现有正式 Runtime。**真实原生图像工具、账号模型权限和付费单帧 Canary 未验收。**

**槽位四：每步极速 TDD + 终局回归。** 每槽先记录 RED、修复、GREEN。新增并行/旧 Owner 覆盖、多次抢锁、外部任务不误删、Worktree 安装拒绝、单帧证据不得变更数据库等测试。原有测试继续包含共享图片容量、Runtime Recovery、原生全链路。完整回归只进行依赖注入和模拟。

## 单槽极速与整轮验收

```powershell
# 每次槽位改动立刻运行（离线零模型调用）
python scripts/storyos_autonomy_fast_test.py --slot carrier
python scripts/storyos_autonomy_fast_test.py --slot writer
python scripts/storyos_autonomy_fast_test.py --slot canary
python scripts/storyos_autonomy_fast_test.py --slot autonomy-integration

# 所有槽位改动合并后
python scripts/storyos_autonomy_fast_test.py --slot all

# 整轮改造完成时
python scripts/storyos_autonomy_fast_test.py --slot all --stress
```

测试绿灯仅证明离线代码合约；不能冒充真实带数据库与 Provider 的验收。

## 正式操作者命令（本轮未执行）

```powershell
# 原生单帧 Readonly Preflight
python scripts/storyos_autonomy_canary.py plan "episodes/00_独立篇/<剧集>"

# Windows 交互用户的只读 Task Scheduler 计划与状态
python scripts/storyos_autonomy_carrier.py plan "episodes/00_独立篇/<剧集>"
python scripts/storyos_autonomy_carrier.py status "episodes/00_独立篇/<剧集>"

# 必须从正式主工作区、在明确批准后安装；下次该用户登录后生效
python scripts/storyos_autonomy_carrier.py install "episodes/00_独立篇/<剧集>" --ack-real-production

# 拆除仅限本脚本安装的同名、同账号、同命令 Task
python scripts/storyos_autonomy_carrier.py uninstall "episodes/00_独立篇/<剧集>" --ack-real-production
```

下一步仍需 Writer 单调 Token 在 MySQL/Redis/Provider Gateway 写端的真正联动和可重放压力验收、Windows 交互用户载体实际安装/重启 Canary，以及**另行明确批准付费**的单帧图像→像素审核→图文成品 `PUBLISH_READY` 正式生产实验。
