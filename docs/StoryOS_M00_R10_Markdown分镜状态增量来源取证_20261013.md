# StoryOS M00 R10：Markdown 分镜自动取证草案与正式状态增量来源收敛（2026-10-13）

## 问题

R9 已实现“锁定 JSON 分镜某帧 → 相邻状态增量 SHA → Frame Contract → Prompt Package → Image Controller → 原生 Codex 最终生图 Prompt”，但现有 StoryOS 正式分镜常用三列表格 Markdown。直接将这些已审核原件改成 JSON 会改变 Storyboard SHA、故事审核身份和历史生产资料，不允许静默迁移。

## 本轮四槽

**① 来源识别、自动建草案。** `scripts/storyos_m00_storyboard_delta_drafts_r10.py` 读取 Release Manifest 当前锁定故事/分镜，识别 Markdown 三列逐帧表格或 JSON 帧，不改变故事文件。默认仅 dry-run，显式 `--apply` 才在 `meta/runtime/m00-adjacent-state-deltas/NN.json` 逐帧创建不存在的草案，包含前一帧/当前帧原文、原文件 SHA、两段原文 SHA、源格式和空白待审核字段。绝不写 `SOURCE_ATTESTED` 或预填虚假内容；其它风格不作操作。现有文件永不覆盖。

**② 不凭空发明内容。** 正式 `SOURCE_ATTESTED` 衍生合同必须经过来源审核元数据（审核人/决策/说明/原 Storyboard SHA 和**真实 canonical Story Review Authority SHA**），还必须调用既有 `story_review.verify` 成功且 `review_required` 为真，任何伪造 Story Review SHA 直接拒绝。六类 `locked` 约束的文本**逐字出现**在锁定故事、前帧或当前帧中；每项行动变化的 `before` 必须能在**严格前一帧**找到，`after` 和 `pixel_evidence` 必须能在**严格当前帧**找到，不能从故事里其它时间点借用事实。任何空缺、重复帧、源 SHA 不一致、引入原文没有的主角/道具/动作均拒绝进入正式合同。这个证据检查不等于语义审核，更不能替代 Story Review Authority；如果分镜原文不含足够状态证据，必须先在正规故事/分镜审查流程补充并重新审核，不可让模型猜测。

**③ 正式生产兼容。** `m00_episode_state_delta.source_transition` 现在增加 `episode` 来源上下文，优先核实该 Episode 明确接纳的来源合同。对 Markdown 而言，`SOURCE_ATTESTED` 的文本内容、审核证据、story SHA、board SHA、上一帧/当前帧 SHA 和 sidecar 完整 SHA 都进入该帧 `Frame Contract.hash_material`，自然沿用 R9 的 `Prompt Package → Image Controller → Provider` 拦截。原 JSON 分镜显式含 `m00_adjacent_state_delta` 时保留旧接口；同时存在原文内合同和 sidecar 则拒绝双权威冲突。没有 sidecar 的旧 Markdown、没有显式增量的 JSON、M01 和合法静态镜头合同 SHA 行为保持不变。

**④ 测试、安全与治理。** 新增真正三列表格的来源回归：自动草案不生图、不假审核，编辑者接受前需 SHA 取证；伪造新动作/车辆/背景、源 SHA 漂移、重复帧、旧版不变、M01 不受影响和静止帧豁免都有专项测试。原生 Codex 保留为正式 Image Controller/Provider 路线，本轮只测代码不重复付费真实像素。压测按每槽极速、`all` 和 `all --stress`，全部在独立 Worktree；合并后遵循 `storyos_retired_worktree_gc.py plan` 的 72 小时安全清理条件。

## 运维

预览草案清单（完全只读）：

```powershell
python scripts/storyos_m00_storyboard_delta_drafts_r10.py "episodes/作品路径"
```

真正建立待审草案（**不会修改任何锁定 Storyboard**，不能直接解锁生图）：

```powershell
python scripts/storyos_m00_storyboard_delta_drafts_r10.py "episodes/作品路径" --apply
```

之后由既有故事/分镜审核流程核实每个状态断言；合同缺失时必须继续显示 `DRAFT_ONLY`，而不是自动赋权。复审通过且源文足够时，才将同一 sidecar 明确标注为 `SOURCE_ATTESTED`、写入可追溯 `editorial_attestation`。这只是一个受来源约束的技术准入信号，正式生产必须继续满足全部 Story Gates、生产 Attempt、预算和 Review Authority。

特别注意：R8 实测 `C02-T01` 的画质审核仍为 `UNCERTAIN_NEEDS_FULL_REVIEW`；R10 不会回填新的 PASS，也不会调用图像生成或 MySQL。
