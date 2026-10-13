# StoryOS R13｜Concept Selection 与 R12 原生 Codex Critic 九处冲突无损合流

2026-10-13｜使用隔离 Worktree 合流、四槽 TDD。**主 checkout 中 9 个用户未提交文件完全未修改／重置／暂存。**

## 核心突破

R12 PR #73 的 `story_review.py` 新审核纪元与主工作区未提交的 Concept Selection 审核更改有 **9 处**真正的 diff3 冲突（上轮早期审计为 6；以 R13 完整三方重演为准）。R13 明确以 `8b42b027:episodes/_system/story_review.py` 为共同基线，结合 R12 commit `4f7730bc` 和主工作区精确快照，无强制覆盖地解决全部 9 处；在独立树测试无冲突标记、Python 语法通过、R12 和 Concept Selection 原有测试通过。

保留了两组彼此独立的审核通道：
- Concept Selection 源修复审查：attempt 3／4／5，对应特定已冻结 Concept Ambition／Story Review 来源哈希和修订版本；
- 迁移目录／制作规范变化的真正新 Codex Story Critic：attempt 9，独立一次性 SHA 绑定审核纪元。**不得**把 attempt 3/4/5 的回执借给 9，也不能将 R12 的新纪元回执用作 Concept Selection PASS。

集成快照另外精确保留主工作区的 `concept_ambition.py`、`review_record_persistence.py`、`runtime_request.py` 三份跟审核源修复相关且尚未提交的源文件。主 checkout 的四份系统源文件在复制时的 Git blob ID：

```text
episodes/_system/story_review.py          acdc50ff1eceb05a61a2735f9a3bf057120c650a
episodes/_system/concept_ambition.py      c2a36a037d45ed475a18bc535e3f0ee5678fb124
episodes/_system/review_record_persistence.py ddc3e5b64f8a4632e9febd9ba8ee34b435f09dd6
episodes/_system/runtime_request.py       61dbf95de4b414fa71691d24afec16cf9c20cdbd
```

## 四槽独立极速

1. **审核命名空间与来源**：Concept A3/A4/A5 + 原生 Codex A9 各自持独立 flag、SHA，混用失败且不得调用付费 Provider。
2. **历史数据库 Review**：`review_record_persistence.load_attempt` 精确指定 attempt，不把第 4 次/最新 PASS 冒充第 3 次失败历史；SQL 查询只读，连接必须关闭。
3. **Frame01／Gateway**：新文本 Critic 可准入绝不意味着获得图片 Permit；有 UNKNOWN Generation Attempt 永远不自动付费重试，M00 Pixel Gate 保持独立。
4. **完整回归和 Git 治理**：R1–R13 `--slot all --stress`（含 189 个 Runtime/多作品容量压力用例）；Worktree 清理仍需干净、合并、72h 等所有证明条件，否则只有 dry-run。

```powershell
python scripts/storyos_autonomy_fast_test.py --slot r13-critic-merge
python scripts/storyos_autonomy_fast_test.py --slot r13-attempt-history
python scripts/storyos_autonomy_fast_test.py --slot r13-frame01
python scripts/storyos_autonomy_fast_test.py --slot r13-integrated
python scripts/storyos_autonomy_fast_test.py --slot all --stress

python scripts/storyos_retired_worktree_gc.py plan
python scripts/storyos_retired_worktree_gc.py branches-plan
```

## 主线集成的保护边界

本集成分支保存了主工作区的尚未提交 Concept Selection WIP，而不是假装这些工作已经获得原作者提交或代码审查。**合流测试成功不授权覆盖主 checkout 已修改的文件。** 要合并 `story-platform-v3-rever`，需要先独立验收本地 Concept Selection 四文件的归属与期望行为，并制定不会覆盖或遗失当前 9 个 dirty 文件的原子合流方案；推送远端待合并 PR 是安全的过渡措施。

当前项目只能声称生成了**合并可验证的代码**，不能声称已经完成真实新 Codex 独立审核、MySQL 正式 PASS、Frame01 或整集 PUBLISH_READY。不要运行一份尚未正式集成的 R13 工作树做付费生产。
