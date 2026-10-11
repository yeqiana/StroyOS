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

## 验收范围

Windows hermetic 回归含同事务回滚模拟、完整 Ledger 追认/投影模拟、SHA 与模型门禁、Queue 保存中断后幂等恢复，未触碰正式 Episode DB；此类测试不是实际生产通过证明。

严禁通过旧 complete_external_generation 对 UNKNOWN 偷渡成功，严禁手动改 MySQL、忽略 Runner provenance、绕过视觉门禁。
