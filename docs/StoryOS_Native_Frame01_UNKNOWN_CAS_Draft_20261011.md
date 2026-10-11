# 原生首帧 UNKNOWN 专用 CAS：隔离实现与生产禁令（2026-10-11）

## 状态：未取得正式执行授权（DRAFT / NOT PRODUCTION READY）

本分支新增 `native_baseline_unknown_cas.py` 的**严格只读来源证明**和**原子更新 Generation Attempt 单行的低层 CAS 函数**，并非可直接执行的端到端生产恢复程序。它不含命令行入口、不会自动被 Image Scheduler/DAG 引入，也不调用生图、模型审核或重新分配图片 Attempt。

它只能在验证如下事实后完成已有 Attempt#1 的条件更新：Runner 原生请求与线程归属、原始生成文件和 Episode RAW 一致、PNG 可解码、NP01 规范化画布与 SHA、排队四帧依赖、当前 Stage、绑定 Frame Contract/Prompt Package、Generation Key/Fencing、MySQL 原状态仍为指定的 `OUTCOME_UNKNOWN` 及不可更改的失败类型。重复调用只有完全相同资产和已成功结果才可幂等返回。

### 尚未实现、因此**禁止在真实 MySQL3307 调用 reconcile_frame01_unknown**

1. **生产 Ledger 原子化**：`TB_PRODUCTION_LEDGER_AUTHORITY` 的完整权威及 `TB_PRODUCTION_FRAME` / `TB_PRODUCTION_ATTEMPT` 投影已经在 MySQL，仍需在**同一 MySQL 事务**内将原技术失败凭同一 Runtime Transaction / Provider Receipt 追认为已生成候选，不能让 Generation Attempt 标成 `SUCCEEDED` 而 Ledger 保持 `TECH_FAILED`。
2. **Queue 幂等补偿**：必须在 canonical Queue Writer/Owner 锁保护下更新原 `external_blocked` 队列项，保留 Generation Attempt 计数与原始异常历史；跨事务中断后须可安全 resume 和查重。禁止将全体帧重排或追加 Attempt#2。
3. **真实只读预检**：在原机 canonical Episode（不是隔离 Worktree 拷贝）读取 MySQL、Queue、Ledger、Runner 持久回执并校验实际 fencing token、保存的原图及 Prompt/Frame/SHA，没有漂移才可考虑正式事务。
4. **独立真实像素审核**：来源与 Ledger 修复仅代表候选出现，绝不代表 `VISUAL_CALIBRATED`、`authenticity`、`continuity` 等通过；必须由正式本机原生 Codex 视觉审核流程绑定像素及当次 Revision，先 Frame01 baseline PASS，再放行 16/08/17。
5. **完整验收**：补充事务回滚、崩溃恢复、旧分支并发、真实隔离 MySQL 并发测试，之后通过 Ubuntu/Windows Story Gates、Qodana、审核 PR，方可合并并选择启动。

### 回归与范围

独立 Windows 工作树只用纯 hermetic Mock MySQL 和合成 PNG 做测试，不调用真实数据库或原生图片工具。回归覆盖成功 CAS、幂等、错误状态、已消费 Attempt 数不变、SHA/画布/命名/队列/Stage/模型策略/Runner/fencing 漂移、CAS 竞争失败等。实际正式生产仍保持 `STORYBOARD_LOCKED`、Frame01 `OUTCOME_UNKNOWN_BLOCKED`、0/20 已正式采用图片，除非后续 MySQL 权威报告有明确变化。

**不得手工更新 `TB_GENERATION_ATTEMPT`、调用 `complete_external_generation` 偷渡 UNKNOWN、重置预算、将图片文件直接标记为 PASS、使用 OpenCodex/API/模拟图片或视频路径。**
