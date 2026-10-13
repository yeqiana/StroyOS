# StoryOS R17-P0 隔离草稿库

2026-10-13

本轮是持久化的 TEST_ONLY 第一切片，不是正式生产 MySQL Project/Episode Writer。
新增本机隔离认证服务（127.0.0.1:19118，默认不启动），显式手工授权和草稿存档。
SQLite 的 TEST_ONLY 数据库只能落在 r17-test-only/draft-vault.sqlite，产生 TEST_BUNDLE/TEST_PROJECT/TEST_DRAFT 身份，不会生产正式 Episode、覆盖真实 Runtime 或出图。

安全基线：强操作口令、Host/Origin/Fetch-Site 校验、写入确认头、无跨域 CORS、request_id 幂等、原子事务、来源 ID 冲突、乐观版本及只追加审计。
浏览器只在人工确认后写入隔离库，从隔离库导入前仍按 R16 全量校验并确认；口令仅存 React 组件内存。

正式 R17 仍需要：TEST_ONLY MySQL 8 真库验收；正式 Project/Episode 主键与 Runtime Request/Gate 绑定；人工 draft_id -> canonical_episode_id 审计和 Writer Admission；安全会话及 CSRF token 生命周期；Chrome 多浏览器 E2E；生产权限审查。通过前不得开放正式写入。

## 本机隔离执行

在仓库根目录使用 Node.js 22（node:sqlite 仍为实验模块）。用仅供此次测试的强随机口令启动独立服务：

1. 设置环境变量 STORYOS_R17_TEST_ONLY=1 和 STORYOS_R17_OPERATOR_TOKEN（至少 32 字符，禁止提交 Git）。
2. 执行 node web-console/server/start-test-only.mjs；服务只监听 127.0.0.1:19118。
3. 在 3100 的作品库手动输入同一口令并确认保存；正式只读 API 19117 仍应拒绝 POST。
4. 测试完成后停掉测试服务；数据库位于 .storyos-tmp/r17-test-only/draft-vault.sqlite，不属于正式数据库。
5. 快速验收：在 web-console 目录执行 npm run test:r17:persistence，另跑 npm run lint 和 npm run build。

## 本轮隔离回归记录

- TEST_ONLY 服务认证、CSRF、Host 防护、幂等、冲突、回滚、持久化重开：Node 测试 3/3。
- R16 备份保护：16/16；TypeScript：通过；Vite build：通过。
- Chrome 八页面验收：尚未通过。2026-10-13 隔离 preview 3197 可打开，但依赖的现网只读 API 19117 与主控制台 3100 均停止监听，导致 Runtime 正式目录无法加载。禁止将其记录为前端失败修复完毕或 8/8 PASS；正式交付前必须复测。
- 主线已被其它任务推进，本轮测试分支与主线合入必须先重新核对远端祖先，不能覆盖脏工作区。

- R17 独立 Chrome E2E：隔离 TEST_ONLY API + 3197 预览，使用两个完全独立 Chrome 用户资料，A 保存测试库 → B 从测试库恢复草稿，2/2 PASS。截图 .storyos-tmp/ui-qa/r17/storyos-r17-{save,restore}.png。
- Chrome 测试可通过 npm run test:r17:browser 复跑；需要隔离数据库服务、授权口令和浏览器预览端口，不能直接对生产 3100 启动该写入测试。
- 隔离 QA 如使用非 3100 浏览器端口，可以通过 STORYOS_R17_BROWSER_ORIGIN 明确授权额外 loopback 来源；非 loopback Origin 始终拒绝。
