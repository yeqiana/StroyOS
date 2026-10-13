# StoryOS R10：真实生产作品范围收敛与 MySQL 关联验收

日期：2026-10-13
实施分支：refactor/storyos-single-node-r10-real-episode-scope-20261013
基线：ae85eba5 (R9)
目标：让控制台只监测真正制作的 Episode，不修改任务或业务数据。

## 根因

R9 的 20 条本机 \`episode-state.json\` 并非 20 部在产/可监测作品：

- 11 条位于标准 \`episodes/<系列>/<作品>/meta/episode-state.json\`。
- 1 条位于 \`episodes/_archive\`，是废弃 Episode 的归档。
- 8 条位于 \`episodes/_tests\`，其中 6 条是没有正常业务 ID 的 Driver 测试，2 条为 world identity 测试。

R9 将它们全部列入生产监控，才出现 11 条 MySQL 身份通过、3 条不匹配、6 条不具备身份。这不是 9 部真实制作丢失 MySQL ID。不能用标题猜测绑定；不需要改表、修改 Episode 状态文件、人工补写 DB。

## 代码修复

将 \`LocalEpisodeFileStatuses\` 的列表及详情查询统一到保守的 \`_production_state_files\`：只接纳正好两级 \`系列/作品\` 的本地作品路径；排除 \`_tests\`、\`_archive\`、点开头隐藏目录以及其它内部目录；排除文件与父级符号链接，必须解析于 workspace episodes 之内。

原有不透明 \`LOCAL_<sha256>\` Episode ref 算法、合法 Episode 状态、分页、审计证据、R9 专用 MySQL 只读监控均不变。尝试使用被排除的旧 ref 访问单作品详情时返回不存在，也不触发 MySQL 查询。实际历史文件/测试目录没有删除，过去真实 Episode 的 ref 不变。与 \`LocalApprovedMedia\` 的既有排除规则对齐。

## 真实验收

- 原始目录扫描：11 正式、1 归档、8 内部测试。
- R10 筛选的真实控制台：阶段证据总数 **11**，未包括归档和内部测试。
- 使用已经授权的 \`storyos_monitor_ro\` MySQL 表级 SELECT 账号，经 \`127.0.0.1:3307\` 真实查询 **11/11** 部正式作品的稳定 namespace 和业务 ID，\`unavailable=0\`。
- 《婚礼前夜》回归：20 帧生产证据、91 条队列记录、MySQL Task 1 条、最近 Production Attempt 60 条、Generation Attempt 0 条匹配；这些是已记录事实，不代表 Worker 当前在线。
- Redis 心跳仍保守，生产 Writer 未被探测或抢锁，\`writer_verified=false\`；所有生产写请求 HTTP 403。
- R10 Chrome 隔离端口 3192/19922 验收 PASS；真实截图 \`.storyos-tmp/ui-qa/real-production-only-r10-1440.png\`（189023 字节）。
- Python 目录隔离 + 审核媒体合同针对回归：**15 passed, 13 subtests passed**。其它组合回归与提交结果以随附测试日志为准。

## 尚未提供的可信 Writer 状态

单机 OS lock file 是否存在不等于内核锁仍由 Driver 持有。不能在监控中使用锁竞争/抢锁、PID 文件或历史 Runner=RUNNING 来冒充在线。要可靠显示真正持锁的 Owner，需要由真正 Driver 的执行权边界提供与 OS lock 在同一进程/执行周期内产生、含标识与 TTL 的主动可核验证据。该功能需要明确的独立变更与真实 Runtime 验收，不是这次“作品范围修复”的前置。

## 风险与回退

仅代码读端变动：不创建 MySQL 用户、不更改 MySQL/Redis/Provider、不开生产按钮、不运行 Worker、不修改被排除目录。安全合入前必须保护 dirty main、检查候选变更与本地文件不冲突，保留 rollback tag 和 SHA256 备份。
