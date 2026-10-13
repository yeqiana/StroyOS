# StoryOS R8：四槽真实 Frame01 阻断定位与极速验收（2026-10-13）

## 核查事实

- 本地原生 Codex CLI `0.162.1`，交互用户 Runner 可执行文件和版本匹配，当前只读登录上下文可见；没有发起模型调用，也**没有证明图片模型实际可用**。
- `storyos_autonomy_canary.py` 之前的通用计划错误调用 `storyos_native_frame01_preflight.py`，而其 `native_baseline_readonly_preflight.py` / `native_baseline_unknown_cas.py` **只服务于《五十亩山地之后_全新重制》的历史 OUTCOME_UNKNOWN Attempt 回收**。普通新作品无法拥有其历史恢复证据，因此统一报 `FRAME01_EVIDENCE_UNVERIFIED` 是错误定位。
- `scripts/storyos_visual_lock_readonly.py` 过去把四个帧号全写死为 1/16/8/17，实际正式作品分别选择不同帧号；例如《天界普通女生的一天》是 **1/16/5/17**，《误入桃花源》是 **1/3/5/15**。统一用固定帧号会错报 `OFFICIAL_VISUAL_LOCK_FOUR_FRAME_PLAN_MISSING_OR_DRIFTED`。

## 四槽改造内容

**槽位 1 · Frame01 / M00**：单集正常生产和《五十亩山地之后》历史 UNKNOWN 恢复使用独立的只读门禁；全程保持 `can_dispatch_image=false`。正常生产必须核实 MySQL 的 Stage、Attempt 未占用 / 未知、原生 CLI 路由，以及正式 Visual Lock 诊断。M00 四帧角色顺序固定为 ordinary_baseline、worst_capture_condition、first_major_anomaly、high_impact_admission，固定首帧=1，其他三帧按各作品正式计划取 1–20 内互不重复的真实编号，不能强制 16/8/17。通过仅证明计划结构有效，仍需实际像素回执和权限。

**槽位 2 · Native Driver / Codex**：正式 `storyos_codex_managed.preflight` 保留已有兼容的 `READY_TO_START`（仅 DAG 启动条件），新增 `production_admission`：清晰分开 `dag_startable` 与 `image_ready`，明确 `image_ready=false`、`production_authorization=false`，汇报缺少的图片证据。不得把 CLI 登录或用户 Runner 的 AUTH 文件存在当作付费图片许可。尚未部署 Watchdog 任务，也未更改已安装 Driver 任务。

**槽位 3 · MySQL 权威 / 本地投影差异**：新增 `scripts/storyos_stage_drift_readonly.py` 比较 `meta/episode-state.json` 与正式 `storyos_episode_stage_readonly.py` 读取的 MySQL Stage。两个来源不一致报告 `STAGE_DRIFT`，只记录 `local_stage` 与 `canonical_mysql_stage`，未经 MySQL 权威证明则拒绝结论；零 SQL 写入，不私自更新本地文件或数据库。注意 `storyos_local_readonly_api` 的本地列表仍为文件投影，不能当成 MySQL 实时阶段。

**槽位 4 · Git 治理与回归**：隔离 Worktree，先只读 `storyos_retired_worktree_gc.py plan`、`branches-plan`，没有同时满足合并到本地与远端、超过 72h、目录完全干净、无活动任务等条件的候选则保留。不得删除归档、远端或运行中的分支；已合并的本轮临时工作树最终可安全退役。所有测试使用 Mock/Fake，不触发真实生产。

## 每一步独立极速 + 最终压力测试

```powershell
python scripts/storyos_autonomy_fast_test.py --slot frame01-real
python scripts/storyos_autonomy_fast_test.py --slot native-image-readiness
python scripts/storyos_autonomy_fast_test.py --slot stage-drift
python scripts/storyos_autonomy_fast_test.py --slot r8-integration

# 全槽极速回归，含前七轮
python scripts/storyos_autonomy_fast_test.py --slot all

# 最终还包含 Runtime、恢复、Host Loop、共享五图容量测试
python scripts/storyos_autonomy_fast_test.py --slot all --stress

# 下列命令只读；不会批准生图或变更 stage
python scripts/storyos_autonomy_native_ready.py
python scripts/storyos_stage_drift_readonly.py "episodes/07_误入/05_误入桃花源"
python scripts/storyos_autonomy_canary.py plan "episodes/15_天界生活日常/01_天界普通女生的一天"
```

**明确仍未完成**：真实 native Codex 图片工具的独立授权 Canary、首张图实际生成与 M00 Pixel Review、跨主机全 Writer 单调 Epoch Fencing、Watchdog 持久任务实际恢复、整部自动 `PUBLISH_READY`。不能由任何只读/模拟测试推断已实现完整无人值守。
