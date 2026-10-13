# StoryOS R17 — 隔离 MySQL8 与 Web Console 草稿保险箱联通

2026-10-13 · TEST_ONLY · 严禁当作正式 Project/Episode Writer

## 四槽位交付
A: scripts/storyos_r17_vault_cli.py 与 web-console/server/testMysqlBridge.mjs；固定隔离 MySQL TEST_ONLY schema、端口 13306，HTTP 不接受 DSN、SQL 或生产 Runtime ID。
B: web-console/server/draftMutationServer.mjs；临时随机会话 15 分钟、CSRF、Origin/Host/Fetch-Site、显式人工写入意图与撤销。
C: 作品与项目页面中保存/查询/选择恢复测试存档，密码仅存 React 内存；R16 恢复 ID 冲突与人工确认保持。
D: MySQL HTTP 实际保存与跨会话读取、旧版只读回归、真实 Chrome 双独立用户资料保存恢复。

## 受限运行方式
必须从仓库根目录显式启动 Node.js: node web-console/server/start-test-only.mjs。
环境变量 STORYOS_R17_TEST_ONLY=1；STORYOS_R17_BACKEND=mysql8-test-only；STORYOS_R17_OPERATOR_TOKEN 为随机高熵至少 32 字符的本机操作口令（绝不提交）。
STORYOS_R17_MYSQL_TEST_AUTH 是主工作区忽略文件 .storyos-tmp/r17-test-only/mysql-auth.json 的绝对路径；STORYOS_R17_PYTHON 是有 pymysql 的 Python 可执行文件绝对路径。
服务监听 127.0.0.1:19118，Vite 3100 的 /api/v1/draft-vault 路径才转发；其它 Runtime 仍走 19117 GET 只读。关闭测试服务不会影响 R16 本地 JSON 备份。
若要单独验收旧 SQLite，可显式设置 STORYOS_R17_BACKEND=sqlite-test-only，两种数据存档不会自动互迁。

## 验收入口
统一极速测试：python scripts/storyos_r17_fast_test.py --slot all --stress；其中新增 --slot http 测试真正的 HTTP → MySQL 读写和会话权限。
另外复测 TypeScript、Vite build、R16 浏览器恢复和双 Chrome 用户资料保存/恢复。

## 尚未取得生产写入许可
TEST_BUNDLE / TEST_PROJECT / TEST_DRAFT 是隔离测试身份，不是正式 Episode 主键。
正式写入必须先完成 Operator Session/Owner Writer、独立权限与审计、人工 draft_id → canonical_episode_id 映射、Runtime Request/Gate 原子接入、安全 MySQL canary。
禁止借由隔离草稿服务触发 Codex、生图、视频流程或修改正式 MySQL。

## 本轮真实验证结果
- 原 R17 SQLite 单元/边界：3/3 PASS；R16 JSON 保护：16/16 PASS。
- 新 Test MySQL HTTP 会话/操作测试：4/4 PASS；真实 API 到隔离 MySQL、同一 request_id 幂等、撤销后拒绝均通过。
- 统一脚本 --slot all --stress：MySQL 库合同 5 轮，HTTP 请求链路 3 轮，旧 R16 防护同时通过。
- 独立 Chrome A 保存 → 独立 Chrome B 恢复（真实隔离 MySQL 8）：2/2 PASS。
- TypeScript 及 Vite production build：PASS。
- 正式 3100 / 19117 仍运行，19118 不常驻；没有生产 MySQL、正式 Episode 或付费生图写入。
