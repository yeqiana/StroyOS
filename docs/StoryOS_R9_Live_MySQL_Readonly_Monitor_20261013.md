# StoryOS R9 · MySQL 3307 真实只读监控接通与验收

日期：2026-10-13
基础分支：story-platform-v3-rever
范围：**监测真实的既有生产**，不启动生产、不生图、不改 Task/Attempt/故事，不增加分布式架构。

## 已取得的用户授权与数据库范围

用户确认 Docker 容器 mysql8.0（本机映射 127.0.0.1:3307）为 StoryOS MySQL，并明确授权创建专用只读监控账号。

已在该容器中配置唯一专用账号 storyos_monitor_ro，仅授予 STORY_OS_RUNTIME 下四张表的 SELECT 权限：TB_EPISODE、TB_TASK、TB_PRODUCTION_ATTEMPT、TB_GENERATION_ATTEMPT。SHOW GRANTS 实际验证包含一条 USAGE 和四条表级 SELECT，没有 INSERT/UPDATE/DELETE/ALTER/GRANT OPTION。应用侧用 START TRANSACTION READ ONLY、严格 Episode 业务 ID + 仓库 namespace 身份关联、单表最多 60 条、最后 ROLLBACK/CLOSE。此轮实际数据库数据只读，唯一数据库写入是**用户明确授权的 CREATE USER / GRANT**。

真实 MySQL 基线计数：Episode 22、Task 400、Production Attempt 548、Generation Attempt 5（按数据库完整表行数，与 GUI 某一 Episode 的最近记录数不同）。

## Secret 与启动器

配置存储在当前 Windows 用户专属目录：

\`%LOCALAPPDATA%/StoryOS/monitoring/mysql-monitor-ro.json\`

- 由本机安全随机数生成账户密码，未写入 Git、终端历史、聊天或页面。
- 保存目录和文件应用 Windows ACL，关闭继承，只给当前用户和系统必要的访问权。
- 控制台已有 \`launch-local-real-console.mjs\` 启动器新增仅限 Windows 的严格定址读取；检验用户名、密码长度、数据库、端口，非法或无凭据均 fail-closed。
- 环境凭据只注入**本机 Python 只读 API 子进程**，不注入 Vite 子进程和任何客户端 JS bundle。正常从原有 Node 启动器启动时会自动复用，不要求永久注册系统环境变量。
- 仓库不含真实凭据、密钥、模型输出、原始任务 payload；只返回状态、数量、时间等白名单字段。

## 真实数据联动测试

真实 Chrome 隔离端口 3191/19921 打开工作台「生产监控」→《婚礼前夜》→ 详情。保留 R6 真实磁盘 20 帧和 91 条队列记录、R7 Redis 心跳未知态。R9 正式从 MySQL 3307 查询该作品：Task 最近 1 条、Production Attempt 最近 60 条、Generation Attempt 0 条。**零 Generation Attempt 是该作品在该表的身份匹配结果，不代表 StoryOS 从未发起过任何真实模型调用。**

- 严格核验 \`mysql_monitor.available=true\`、数据库身份核实、SELECT-only GRANTS 通过。
- Worker 执行权/Writer 执行权仍 UNVERIFIED；MySQL RUNNING 是落库状态，不被当成有效心跳或 OS 锁授权。
- 整体服务 POST 操作返回 HTTP 403；不发起任何生产请求，不接 Provider。
- 保存真实 Chrome 截图 \`.storyos-tmp/ui-qa/real-mysql-monitor-r9-1440.png\`（隔离 Worktree）。
- R9 独立 Python 只读权限及 R6/R7 回归 28 passed、7 subtests passed；TypeScript/Vite 均 PASS。最新主分支集成验收及完整覆盖范围以随后测试记录为准。

**全量本机 Episode 关联审计：**20 部本机作品中，11 部已通过 MySQL 双身份校验并可读取真实记录；3 部返回 EPISODE_IDENTITY_MISMATCH；6 部返回 EPISODE_IDENTITY_UNVERIFIED。对未能可信匹配的 9 部拒绝查询，不做标题或路径模糊推测，仍保留本地历史文件监测。

## 仍未覆盖与安全结论

- Writer OS 文件锁的持有者和有效围栏不可通过存在的锁文件、PID 或 MySQL RUNNING 证明，R9 不尝试抢锁。
- Redis 之前发现的 1 条心跳记录未带时区，因此只能为 UNVERIFIED；未在生产端改写心跳记录。
- 未经过授权的数据库/Schema 不访问；名为 storyos-test-only-* 的测试容器不使用。
- 每类 API 只展示 60 条，必要时将来提供经授权的分页与真正 canonical ID 查询，而不无限制扫描或泄漏敏感字段。

回退方法：安全保留合入前 Git tag、仅停止并重新启动本机控制台即可切换读取代码；如需禁用数据库监控，在本机安全配置文件中取消启用或让启动器不加载，**不要删除生产数据**。
