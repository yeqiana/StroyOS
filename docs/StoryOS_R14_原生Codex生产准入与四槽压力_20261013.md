# StoryOS R14｜一次性原生 Codex 审核正式准入护栏与四槽压力

2026-10-13｜本轮继续用户授权的四槽实际改造。代码依托 R13 PR #74 (含 R12)，先在独立 Git Worktree 无冲突合流近期 M00 变更；生产主工作区现存 9 个未提交文件，绝不覆盖／强制提交。

## 核心事实：双环境读证明边界

目标 Episode：`episodes/15_天界生活日常/01_天界普通女生的一天`。

- 真实主工作区只读 MySQL Stage = `STORYBOARD_LOCKED`，`ACTIVE`；图片 Attempt 0、UNKNOWN 0；Driver = `NEVER_STARTED`；正式 Story Review 缺权威；原生 Codex `NATIVE_AUTH_CONTEXT_READY`，与交互式 Runner 的二进制身份可一致。
- 用正式主工作区的运行时环境和数据，**只读加载** R14 独立审核方案，得到 `ONE_SHOT_NEW_CRITIC_EPOCH_READY`（第 9 次审核，不复用历史 PASS）。再联合 MySQL、Attempt、Driver 与原生 CLI 只读检查得到 `READY_FOR_ONE_SHOT_NATIVE_TEXT_REVIEW`。这些读侧结果 `model_calls=0`、`sql_writes=0`、`can_dispatch_image=false`。
- **读侧组合验证不是正式生产部署，也不是模型可用额度的证明**。旧正式审核仍需一次真实原生 Codex 重新评分、权威 MySQL 回执与当前来源哈希校验，才能开展 PREIMAGE、M00 与首帧图像。

## 四槽代码改造

1. **生产主工作区判定**：`storyos_autonomy_r12_critic_preflight.inspect` 必须在有真实 Git `.git/` 目录的主 checkout 中执行；隔离 Worktree 的 `.git` 文件不能取代生产身份。写一次性纪元票据的 `story_review_rubric_migration.authorize` 同样要求主 checkout，且目标 Episode 必须位于同一项目根内。错误则直接阻断，绝不读密钥或接触模型。
2. **Codex 身份证据**：只有 `NATIVE_AUTH_CONTEXT_READY`、`opencodex_used=false`、交互式登录上下文存在，且 `cli_runner_same_binary_verified=true` 才能授予仅此一次的文本审核**候选**准入；不会据此授予图像 Permit 或跳过付费回执。
3. **冻结来源防篡改**：审核第 2 次请求的所有 `source_files[].sha256` 必须是标准 64 位十六进制；请求 ID 不得为空。故事／分镜与旧 Review 全量校验、当前制作规范的 SHA 变化必须真实，任何数据不符合即 fail-close。不得把旧 `WORK_DEVSPACE_BOUNDED` 的 `FINALIZED` 或 PASS 复制成新正式审核。
4. **每槽极速/全体 stress + Git 退役**：`--slot r14-primary-worktree`、`--slot r14-native-identity`、`--slot r14-critic-history`、`--slot r14-closure`，最终 `--slot all --stress` 包括 189 条 Runner/MySQL/多作品共享五图容量压力测试。老 Worktree 和分支仅按 `storyos_retired_worktree_gc.py` 严格的已合并、干净、无人使用与安全路径判定退役。已安全删除一个满足全部条件的旧本地分支 `fix/storyos-episode-atomic-claim-20261010`。

```powershell
python scripts/storyos_autonomy_fast_test.py --slot r14-primary-worktree
python scripts/storyos_autonomy_fast_test.py --slot r14-native-identity
python scripts/storyos_autonomy_fast_test.py --slot r14-critic-history
python scripts/storyos_autonomy_fast_test.py --slot r14-closure
python scripts/storyos_autonomy_fast_test.py --slot all --stress

# 只能在正常 main checkout + 本地受信任 runtime.env 下执行；依旧是纯只读
python scripts/storyos_autonomy_r12_critic_preflight.py "episodes/15_天界生活日常/01_天界普通女生的一天"
```

## 发布判断

发布所需的**代码审查和主工作区文件无损整合**独立于模型调用许可。不能直接在 PR Worktree 运行真实付费 Critic；它缺少正式 Episode 运行时来源且会被新的 `PRIMARY_CHECKOUT_REQUIRED` 阻断。尚未部署时即便只读组合预检 READY，正式 Stage/Review 也不会凭测试转化为 PASS。

主工作区原 9 个未提交文件和所有真实 MySQL/图片 Attempt 一律保留。上线必须先让 PR #74 与本轮加固无损合并到 `story-platform-v3-rever`；无需再人为重置第 2 次审核或付费 Attempt。若合并本地 dirty 文件存在覆盖风险，不能强行快进，只能保留已测试的 PR 并清晰给出阻断。
