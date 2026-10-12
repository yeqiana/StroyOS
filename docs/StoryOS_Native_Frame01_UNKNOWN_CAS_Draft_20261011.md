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

## 2026-10-11 真实 TEST_ONLY MySQL 验收回执

经用户明确授权，仅在本机独立 Docker `storyos-test-only-mysql-frame01-pr72-20261011` 中执行。容器镜像 `mysql:8.0`，标签 `storyos.test-only=true`，映射 `127.0.0.1:13306 → 3306`，数据库 `storyos_isolated_test_native_pr72`，非 root 用户 `storyos_test_pr72`。专用随机凭据保存在仓库外；没有复用本机正式 `mysql8.0` / 端口 `3307`，没有写入正式 Episode。

- **真实 InnoDB 测试：`5 passed in 4.27s`**，执行命令为 `pytest -q tests/system/test_native_baseline_isolated_mysql_contract.py --storyos-isolated-mysql`，没有 5 个 SKIP。
- **同库核心恢复安全回归：`181 passed in 7.30s`**，含实际 MySQL 的 5 项测试。
- **完整 15 个关联文件回归：首次 `259 passed in 18.38s`，修复 Queue 崩溃重入后的 Ledger 操作缓存失效后复验 `260 passed in 14.08s`，均 `0 skipped`**，所有真实 MySQL 用例均运行；输出中不包括任何模型调用或正式 DB 写入。
- Docker admission 使用真实仓库常量 `STORYOS_TEST_MYSQL_APPROVAL=I_AUTHORIZE_ISOLATED_TEST_DB_WRITES`，且容器命名符合 `storyos-test-only-mysql-*`。此前文案中 `I_ACKNOWLEDGE_TEST_ONLY_MYSQL` 及 `storyos-mysql-testonly` 均**不符合**代码准入，应废弃。

已完成的是真实测试库验收，不是正式生产授权。受控正式追认仍需独立 PR 代码审查、合并和生产 Owner/fencing 二次核验。后续像素审核严格走本机原生 Codex `REVIEW_ORDINARY_BASELINE`；本轮 WebCodex Runner 中 `codex login status` 为 `Not logged in`，此事实不等同于用户桌面独立会话的登录状态，不能据此声称模型 entitlement 已验证。

**崩溃重入加固**：当 MySQL Attempt 已是 `SUCCEEDED` 时，同一 `operation_scope` 中的 Ledger 旧缓存可能仍为 `TECH_FAILED`，导致 Queue 异步恢复错误拒绝。已在幂等原路径核验 Ledger 后同步 `ledger_store.invalidate(ep)`，且通过新增 1 项负向/重入回归和全部 260 项真实 TEST_ONLY MySQL 关联验收；这不涉及任何新生图或生产 DB 写入。

## Queue 恢复幂等证明与 Review Backfill（新增）

首帧成功追认后，Queue 原始 `generated` 项的 `unknown_reconciliation` 必须完整等于 Runner SHA 构造的审计回执（kind、Evidence SHA、Runner Request ID、Generation Key、Attempt#1、Frame Contract SHA、Prompt Package SHA、`pixel_review_pass=false`）。重入还需验证原 Runtime Transaction ID、执行 phase 为 COMMITTED、已完成时间、无残留外部阻断或技术失败。任何伪造的像素 PASS、模型认证、附加回执字段或缺失必须 fail closed。

测试通过真正的 `review_queue.reconcile_generated` 对中断时漏入队的 generated 图片补挂 FAST_SCOUT：要求绑定同一 Generation Key、候选 SHA、双契约 SHA，Review 仍 queued 且 receipt=None；第二次重入不得重复入队。此测试只使用合成临时 PNG 和内存 Queue，不触发视觉模型，也不会将 baseline 变成已审核。

**正式 Episode 已核实 `fast_frame_scout.required=false`：FAST_SCOUT 当前未启用，不应误认为通用 Review Queue 补挂等于本剧集 baseline 审核已派发。** 对这条剧集，正确路径是 `visual_lock_baseline_gate.awaiting_review` 在原生首帧恢复为 generated、独立 baseline 审核尚未 PASS、且三帧仍依赖 baseline 时返回 true；随后 `next_action` 选择 `REVIEW_ORDINARY_BASELINE`，由 `vision_review_executor` 经本机原生 Codex 执行（不得由 WebCodex 执行）。已新增只读/合成回归验证：即使 FAST_SCOUT 关闭仍欠 baseline 视觉审核；若已有 SHA-bound FAIL 或修复待生图则不能无界重复审核，若正式批准则无需再审。

## 严格零写入 Frame01 Preflight

新增 `episodes/_system/native_baseline_readonly_preflight.py`，只读检查官方 Episode 原 Runner 图片证明、RAW/规范化 PNG SHA、Prompt/Frame Contract、MySQL Generation Attempt 原行（含 Fencing、原 Context、原 Payload 模型/Provider）、完整 Ledger BLOB 及 Typed Frame/Attempt 投影。纯内存尝试 `TECH_FAILED → ORIGINAL_READY` 并核对来源。生产数据库只使用非锁定 SELECT；**不执行 SELECT FOR UPDATE、CAS、事务更新、Queue 改动或模型调用**。任何证据漂移退出 2。

在代码完成安全合并后，可由本机 Python 运行：

`python scripts/storyos_native_frame01_preflight.py episodes/00_独立篇/06_五十亩山地之后_全新重制`（包装入口强制读取 canonical ignored runtime.env，避免使用终端残留 DB 配置）

若完全匹配，输出 `READ_ONLY_EVIDENCE_READY_TEST_DB_STILL_REQUIRED`、`authorized_to_mutate_production=false`、`real_mysql_integration_tests_passed=false`、`pixel_review_pass=false`。**这个状态绝不是正式追认授权**。经本轮运行时动态加载此隔离分支的新模块对真实 canonical Episode 的只读预演已通过，未写任何正式 SQL。负向测试覆盖 fencing/Context/model 与 typed 投影漂移。

## 2026-10-12 提交前来源复验（局部加固，仍禁止正式 CAS）

在原子 Ledger/Attempt 事务内、最终 COMMIT 前再次运行完整 Runner 线程来源、原始/规范化 PNG、证据 SHA、Queue/Prompt 绑定校验，并与首次验证的关键身份字段比较。新增“Ledger 更新后替换原图”和“Attempt CAS 后、COMMIT 前替换候选图”两项回滚注入测试，必须保证 Attempt 仍为 OUTCOME_UNKNOWN、Ledger 恢复原状态。关联 5 个 hermetic 测试文件本地回归 198 passed。

**此修复只缩短 TOCTOU 时间窗口，不提供跨进程源文件冻结。** 二次校验与数据库实际 COMMIT 之间仍可能存在外部文件替换；Windows 生产环境需要先实现并独立验证覆盖证据 JSON、Runner 原图、候选图、Codex JSONL 和持久回执的写入排斥/只读快照机制，且锁定须持续到事务 COMMIT 完成。未完成前不授权正式生产对账、不清除 UNKNOWN、不重派图片、不签发像素审核 PASS。

## 验收范围

Windows hermetic 回归含同事务回滚模拟、完整 Ledger 追认/投影模拟、SHA 与模型门禁、防止伪造成功与像素审核、未批准基线时三帧继续阻断、Queue 保存中断后幂等恢复，未触碰正式 Episode DB；此类测试不是实际生产通过证明。

严禁通过旧 complete_external_generation 对 UNKNOWN 偷渡成功，严禁手动改 MySQL、忽略 Runner provenance、绕过视觉门禁。

## 2026-10-12 Windows 文件来源冻结（隔离工作树新增，未授权正式追认）

在现有提交前二次来源复验基础上，增加 `native_baseline_source_freeze.py`：对已核验的六类独立源文件（证据 JSON、Episode Raw PNG、规范化候选 PNG、Codex JSONL、持久 Runner 回执、用户原生生成线程 PNG）使用 Windows `CreateFileW` 打开只读句柄，并仅允许 `FILE_SHARE_READ`。任何一个句柄获取失败立即拒绝，已取得的句柄在退出时释放；非 Windows 生产调用 fail closed。成功取得全部句柄后，在同一冻结范围内再次核对 Runner 证据，再执行原有 MySQL 同事务 Ledger/Attempt CAS；冻结句柄一直保留到事务 `COMMIT/ROLLBACK` 返回之后。

新增真实 Windows 跨进程测试：独立 Python 子进程在冻结期间尝试覆盖和原子替换合成源文件均失败，退出冻结后覆盖恢复正常；另验证第三个句柄获取失败时前两个句柄均释放。SQL hermetic 测试额外覆盖“锁持有直至事务退出”“冻结不可用时零 CAS”“持久回执缺失时拒绝”“冻结入口期间证据变化拒绝”。本轮 Windows 本地相关 6 文件回归 **205 passed、1 skipped**（唯一跳过的是专门针对非 Windows 的拒绝测试）；PR #71 原 2 文件回归 **52 passed**。这些结果不包含真实生产 MySQL 写入、正式像素审核或图片生成。

**未解除生产门禁**：本次仍属于隔离实现；Windows 文件句柄测试不能替代真实 Episode 六源路径/身份、重解析点、目录置换、崩溃/COMMIT 不确定性、正式 Queue Writer 锁、MySQL TEST_ONLY 端到端联调和独立代码审查。原生 Codex 登录成功且只读设计建议返回，但本次原生 Codex 的仓库文件读取被环境策略拦截，**没有代码级独立审核 PASS**。PR #72 的远端 CI 仍属于旧 head `2321139e`，不得把旧 CI 绿灯冒充本地新增代码的 CI 结果。正式 Attempt#1 保持 `OUTCOME_UNKNOWN`，不得清除、重派或以来源 SHA 冒充视觉审核 PASS。
