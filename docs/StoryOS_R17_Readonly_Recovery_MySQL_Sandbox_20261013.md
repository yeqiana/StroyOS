# StoryOS R17 · 真实只读 Console 恢复与四槽验收

日期：2026-10-13；复核基线：`story-platform-v3-rever` / `551ddd99`。

## 槽位 A · 原只读服务恢复
- WebCodex 启动现有 `web-console/scripts/launch-local-real-console.mjs`，明确保留生产内容；没有新增正式 Writer。
- 本机 `http://127.0.0.1:3100/` HTTP 200，`http://127.0.0.1:19117/healthz` HTTP 200。
- 正式 Runtime 摘要 `GET /api/v1/runtime/statuses?limit=100` HTTP 200、11 部真实 Episode。启动日志明确 `LOCAL_STORYOS_READY`。
- 不触碰图片 Provider、不启动新 Episode，R17 测试写入服务默认不开。

## 槽位 B · Chrome 真实数据验收
- 使用原仓库 `web-console/scripts/test-r16-local-draft-browser.mjs` 真正启动隔离 Chrome；不访问模拟正式作品列表。
- 1440px：工作台、故事制作、作品与项目、生产监控、工作流、Agents、审计日志、系统设置，8/8 PASS。
- 1024px：同一组 8/8 PASS。
- 官方 Runtime 正式目录 11/11；R16 本地恢复与重复 ID 阻断按原浏览器流程复测。
- 截图仍位于已忽略的 `.storyos-tmp/ui-qa/r16/`，不可作为正式生图资产。

## 槽位 C · 独立 MySQL8 验证
- 仅在专用 TEST_ONLY 容器创建隔离 schema `STORYOS_R17_DRAFT_TEST_20261013`，未触碰 `mysql8.0` / `STORY_OS_RUNTIME`。
- 使用专用受限账号，通过 `platform/repository/mysql/r17_isolated_draft_repo.py` 验证 R16 草稿存档、幂等、乐观版本、来源身份冲突、失败回滚和并行双写阻断。
- 测试凭据保存在主工作区 Git 忽略路径 `.storyos-tmp/r17-test-only/mysql-auth.json`；不写入代码、文档或浏览器。
- `python scripts/storyos_r17_fast_test.py --slot mysql` 用于 4 个 MySQL 真实测试，`--slot all --stress` 用于多轮回归。

## 槽位 D · 集成和权限边界
- SQLite TEST_ONLY 试验端口与 MySQL TEST_ONLY 验证当前是两个相互独立的实验后端；本轮不宣称浏览器已连接 MySQL。
- 新增代码必须维持原 19117 GET 白名单及写入 403，不绕开 Driver/Owner/Global 5 Permits。
- 主线合入须 ff-only、本地远端对齐、主工作区脏文件清单不改变。

## 生产级别尚缺
- 真实 Operator 会话 + CSRF 生命周期、正式 Project/Episode identity allocation 和人工迁移映射审计。
- 独立、受权生产账户与写操作 API 的 MySQL 路由，以及 Runtime Request / Gate / Writer admission。
- 禁止把 TEST_ONLY 存档视为正式 Episode，也不代表已具备 Web 正式创建/生产资格。

## 本次实测结果
- 隔离 MySQL 8 的四类测试连续 5 轮均通过：20/20（含双连接并发同请求）。
- R16 只读接口和 Browser backup 防护：2/2、16/16；R17 独立服务安全测试：3/3。
- 真实 Chrome 1440px 8/8、1024px 8/8，均使用主工作区 11 部实际 Runtime 文件证据。
- 此处是测试断言和只读验收的结果，不是正式 MySQL Writer 或付费生图授权。
