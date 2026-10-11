# 原生首帧 UNKNOWN 同事务对账 · Draft

## 本轮隔离实现

已有严格 Runner/线程 PNG 原图证明、Frame Contract 与 Prompt SHA 绑定、PNG 解码与画布校验。新增在同一个 MySQL transaction 中对 TB_GENERATION_ATTEMPT、TB_PRODUCTION_LEDGER_AUTHORITY、TB_PRODUCTION_FRAME 与 TB_PRODUCTION_ATTEMPT 做条件性追认。旧 Ledger 失败、旧 NOT_INVOKED 回执、旧异常与 Attempt 消耗次数保留在审计历史中。模型身份不作虚假认证，真实图像工具日志仍记录零事件，视觉审核仍 pending。

原有 Frame01 的 Generation Key、fencing、queue_item、runtime_transaction_id、Raw 与规范化像素 SHA 必须全部一致，否则 fail closed。更新顺序为 MySQL 原子 Ledger/Attempt → canonical Queue Owner 锁下更新原 Frame01；Queue 属外部文件或 Redis，因此不能假称跨库原子性，必须用幂等重入弥补 MySQL 已提交但 Queue 尚未保存的崩溃窗口。原 Frame16/08/17 继续 queued。

## 尚不可在正式 MySQL 3307 执行

本分支仍为草稿；不自动导入正式 DAG，不生图，不执行独立像素审核，不重试图片，不重置 Attempt，也不把现有图片直接标为 PASS。正式启用前必须完成：
1. canonical 主工作树真实只读 preflight，对 Ledger、Queue、Model/Prompt、Runner、原始 PNG 与 MySQL fencing 重新验 SHA；
2. TEST_ONLY MySQL 的事务/回滚/竞争联调。必须严格遵守 tests/system/_isolated_mysql_authority.py 的独立端口、带标签容器、非 root 专用账号及显式授权，绝不拿 MySQL3307 代替测试；
3. 增补真实 MySQL 与队列中断恢复的系统验收、PR 新提交 Windows/Ubuntu Story Gates、Qodana，并完成代码审查和安全合并；
4. 完成真实 Attempt#1 对账后，独立由本机原生 Codex 审核 Frame01 像素。只有 baseline 审核正式 PASS 后，才能按既定依赖解锁其他 Visual Lock 帧。全篇仍为图文系统，没有图片转视频环节。

## TEST_ONLY MySQL 可重复验收入口（只允许独立环境）

新增 tests/system/test_native_baseline_isolated_mysql_contract.py，使用 synthetic Episode ID、独立测试数据和真实 MySqlConnection / Repository SQL，覆盖：

- 原 Ledger Authority + Typed Frame / Typed Attempt 的真实 InnoDB 同事务写入与重入检查；
- Typed 投影 SQL 故障注入和跨三表事务回滚；
- Generation Attempt 原 OUTCOME_UNKNOWN → SUCCEEDED 与 Ledger/Typed 同事务提交；
- 最末 Generation Attempt CAS 失败时，Ledger 与 Typed 投影全部回滚；
- 两个并发 MySQL 追认者争夺同一原 Attempt：仅一方首次提交，另一方幂等读取，Attempt 消耗次数与 fencing 不变（仅限 TEST_ONLY 环境）。
- TEST_ONLY 生成权威使用独立的 Logical Episode ID，Ledger 使用独立的 EPU_ Storage ID，防止测试中的假相同 ID 隐藏生产跨命名空间问题。
- Frame01 成为 generated 后，真实 image_scheduler.ready_items 仍须确认 baseline 像素批准；审核未批准时后续 Visual Lock 16/08/17 仍被依赖门禁阻断。

**默认 pytest 运行得到 5 skipped，不是 5 passed。** 只有项目 tests/system/_isolated_mysql_authority.py 明确准入的用户授权环境才可以执行：

`python -m pytest -q tests/system/test_native_baseline_isolated_mysql_contract.py --storyos-isolated-mysql`

准入要求包括 STORYOS_TEST_MYSQL_APPROVAL 显式值、独立 Docker 容器标签 storyos.test-only=true、非 3306/3307 的 127.0.0.1 映射、专用非 root 凭据及 storyos_isolated_test_ 前缀数据库。无准入时不得运行任何真实测试写入或拿生产数据库替代。测试结束按 TEST_ 命名空间删除合成数据，不修改正式 Episode、生产 MySQL、模型生成或像素审核。

## Queue 恢复幂等证明与 Review Backfill（新增）

首帧成功追认后，Queue 原始 `generated` 项的 `unknown_reconciliation` 必须完整等于 Runner SHA 构造的审计回执（kind、Evidence SHA、Runner Request ID、Generation Key、Attempt#1、Frame Contract SHA、Prompt Package SHA、`pixel_review_pass=false`）。重入还需验证原 Runtime Transaction ID、执行 phase 为 COMMITTED、已完成时间、无残留外部阻断或技术失败。任何伪造的像素 PASS、模型认证、附加回执字段或缺失必须 fail closed。

测试通过真正的 `review_queue.reconcile_generated` 对中断时漏入队的 generated 图片补挂 FAST_SCOUT：要求绑定同一 Generation Key、候选 SHA、双契约 SHA，Review 仍 queued 且 receipt=None；第二次重入不得重复入队。此测试只使用合成临时 PNG 和内存 Queue，不触发视觉模型，也不会将 baseline 变成已审核。

**正式 Episode 已核实 `fast_frame_scout.required=false`：FAST_SCOUT 当前未启用，不应误认为通用 Review Queue 补挂等于本剧集 baseline 审核已派发。** 对这条剧集，正确路径是 `visual_lock_baseline_gate.awaiting_review` 在原生首帧恢复为 generated、独立 baseline 审核尚未 PASS、且三帧仍依赖 baseline 时返回 true；随后 `next_action` 选择 `REVIEW_ORDINARY_BASELINE`，由 `vision_review_executor` 经本机原生 Codex 执行（不得由 WebCodex 执行）。已新增只读/合成回归验证：即使 FAST_SCOUT 关闭仍欠 baseline 视觉审核；若已有 SHA-bound FAIL 或修复待生图则不能无界重复审核，若正式批准则无需再审。

## 严格零写入 Frame01 Preflight

新增 `episodes/_system/native_baseline_readonly_preflight.py`，只读检查官方 Episode 原 Runner 图片证明、RAW/规范化 PNG SHA、Prompt/Frame Contract、MySQL Generation Attempt 原行（含 Fencing、原 Context、原 Payload 模型/Provider）、完整 Ledger BLOB 及 Typed Frame/Attempt 投影。纯内存尝试 `TECH_FAILED → ORIGINAL_READY` 并核对来源。生产数据库只使用非锁定 SELECT；**不执行 SELECT FOR UPDATE、CAS、事务更新、Queue 改动或模型调用**。任何证据漂移退出 2。

在代码完成安全合并后，可由本机 Python 运行：

`python scripts/storyos_native_frame01_preflight.py episodes/00_独立篇/06_五十亩山地之后_全新重制`（包装入口强制读取 canonical ignored runtime.env，避免使用终端残留 DB 配置）

若完全匹配，输出 `READ_ONLY_EVIDENCE_READY_TEST_DB_STILL_REQUIRED`、`authorized_to_mutate_production=false`、`real_mysql_integration_tests_passed=false`、`pixel_review_pass=false`。**这个状态绝不是正式追认授权**。经本轮运行时动态加载此隔离分支的新模块对真实 canonical Episode 的只读预演已通过，未写任何正式 SQL。负向测试覆盖 fencing/Context/model 与 typed 投影漂移。

## 验收范围

Windows hermetic 回归含同事务回滚模拟、完整 Ledger 追认/投影模拟、SHA 与模型门禁、防止伪造成功与像素审核、未批准基线时三帧继续阻断、Queue 保存中断后幂等恢复，未触碰正式 Episode DB；此类测试不是实际生产通过证明。

严禁通过旧 complete_external_generation 对 UNKNOWN 偷渡成功，严禁手动改 MySQL、忽略 Runner provenance、绕过视觉门禁。
