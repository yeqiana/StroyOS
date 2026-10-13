# StoryOS 原生 Codex 全流程自动生产（2026-10-10）

## 执行入口

只在本机已登录的**原生 Codex CLI** 和 StoryOS 正式主工作区运行，不依赖 WebCodex Host、不允许 OpenCodex 代理。

```powershell
cd D:/workspace/YeQianWorkSpace/yeqian/storyOS

# 只读检查真实 MySQL、CODEX_MANAGED 全链路、Attempt 和 Driver
python scripts/storyos_codex_managed.py plan "episodes/00_独立篇/06_五十亩山地之后"

# 只有 plan = READY_TO_START 才能正式自动运行这个 Episode
python scripts/storyos_codex_managed.py run "episodes/00_独立篇/06_五十亩山地之后" --ack-real-production
# 2026-10-13 增补：已存在 Episode 的会话外常驻 Driver（需要相同准入）
python scripts/storyos_codex_managed.py start "episodes/00_独立篇/<剧集>" --ack-real-production

# 从一句话创作一个全新作品并自动推进到图文 PUBLISH_READY
python scripts/storyos_codex_managed.py create "新作品的故事题材和创作要求" --title "新作品" --ack-real-production
```

`plan` 是只读查询，模型调用数、数据库写入数均为零。只有显式 `--ack-real-production` 才调用 canonical StoryOS 工作流；这会产生真实模型调用/生图费用。`run` 是本机 Codex 会话中的前台同步工作流，需要保持该会话存活。不要用短命 shell 进程伪装持久 Driver。

## 执行路径与信任边界

- 子进程的完整生产模式：`STORY_OS_PRODUCTION_MODE=CODEX_MANAGED`。
- 仅原生 Codex 图片通道：`STORY_OS_IMAGE_EXECUTOR=CODEX`。
- 模式显式生效时，Story/PREIMAGE 和文本、治理、视觉审核与图片执行全部归 Codex；原 COLLABORATIVE 的 WORK 审核路由保持原样。
- **不是另一套编排器**：统一调用 `story_os.py run --full-auto --resume` 或 `story_os.py create --full-auto`，Runtime DAG、Scheduler、MySQL Review/Attempt Authority、Producer Gateway 和单 Episode 生产锁依然拥有唯一执行权。
- 防止数据库串线：剔除用户会话继承的 `STORYOS_MYSQL_*` 覆盖，重新读取 ignored `.storyos/runtime-launcher/runtime.env`。同时去掉继承的 OpenAI 兼容端点/API Key 覆盖，避免绕到 OpenCodex。
- 任何 `OUTCOME_UNKNOWN` / 活动 Attempt / 无法证实的正式 schema / 非原生执行路由 / 非空闲 Driver：禁止启动。历史成功图不得绕过 Provider 终态、Revision 输入绑定、真实像素审图、Visual Lock/Review 或 2 次共享 Attempt 硬上限。
- 对既有 Episode，额外通过 MySQL `episode_state_persistence` 做只读阶段准入：`PUBLISH_READY` / `PUBLISHED` / `DATA_REVIEWED` 表示作品已到发布准备或后续阶段，不再提示可新开一次付费生产；终止 disposition、未知状态或 MySQL 阶段权威无法读取一律阻断。生产入口不会用 `episode-state.json` 替代 MySQL 权威。
- 成功后的生命周期是故事→分镜→PREIMAGE→人物/环境/帧合同→四层 Visual Lock→批量出图→逐帧审核→字幕图文渲染→发布资产冻结→`PUBLISH_READY`，**不执行视频生产**。

## 历史 00-05 阻断留档（不得套用至全新 00-06）

以下是已经废弃的旧 `00-05` 生产历史，仅为故障追溯，不是新 `00-06` 的正式状态。`00-06` 必须重新以本机 MySQL 和只读 `plan` 验证，不允许复用旧 `00-05` 的 Attempt、Revision 或媒体。\n\nRevision `PR_abbda13531e89cf2_0001_b955598a317fad91` 在 `VISUAL_LOCK_PENDING`；Frame 01 已完成当前版实际像素审图，但 Frame 05/06/24 未形成正式四层 Visual Admission。Frame 06/24 旧 OpenCodex Attempt 1 是 `OUTCOME_UNKNOWN`，Provider 成功/失败均没有足够的终态证据。因而目前 `plan` 应返回 BLOCKED，不能为了追求全自动删除历史记录或强制消耗 Attempt 2。需要先完成合法的运营裁决/对账闭环，再让同一个全自动入口继续。

## 测试

```powershell
python -m pytest -q tests/system/test_storyos_native_codex_full_auto_entry.py tests/system/test_storyos_native_codex_whole_chain_routes.py
python -m pytest -q tests/system
```
