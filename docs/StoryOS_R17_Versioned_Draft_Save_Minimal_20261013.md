# StoryOS R17 · 草稿重复保存最小闭环

2026-10-13 · 范围严格收敛 · **TEST_ONLY**

## 解决的问题
以前 Web Console 可以新建本地项目与故事，也可以把 JSON 整份存到隔离 MySQL，但**同一作品改完再保存**会因来源 ID 冲突而失败。本轮补一个小的服务端持久化能力，而不是新建一套 Project/Driver 框架。

- 隔离 MySQL 8 新增一张 `r17_saved_workspaces` 表，保存浏览器自建项目和作品草稿的 R16 备份快照。
- POST 创建服务端工作区并返回 `TEST_WORKSPACE_...` 稳定 ID 和版本 v1；PUT 携 `expected_version` 做版本化更新；GET 查询/读取。
- 复用现有短期操作会话、CSRF、限流、`request_id` 幂等、完整草稿结构校验、InnoDB 事务与审计。
- Web Console 的本地草稿保险箱增加保存、服务端列表、人工选择与恢复按钮。已有本地数据不自动覆盖；默认不会连接正式 Runtime。
- 仅有**一个独立测试库新表**、4 条路由、少量按钮，没有任务调度、额外 Worker、Provider 接口或正式 Episode 迁移。

## 质量门禁
- `python scripts/storyos_r17_fast_test.py --slot all --stress`
- `npm run lint`、`npm run build`、新 `npm run test:r17:workspace-browser`（后者需要人为启用的 TEST_ONLY 数据库服务与 3197 隔离预览）
- MySQL 重复保存 v1→v2；旧版本冲突 409；跨会话读取与请求幂等；Chrome A 保存 → Chrome B 恢复，均须通过。
- 正式 GET-only API `19117` 仍拒绝 POST (403)，测试服务 `19118` 默认不启动，生产 MySQL 及 11 部正式 Episode 不动。

## 尚未包含
`TEST_WORKSPACE` 身份**不是**正式 canonical Episode；此能力也不会在新建项目时自动写入生产 MySQL。正式 Writer 准入、人工迁移映射及 Runtime Gate 必须另行授权/验收。不要把测试库持久化成功称为正式制作已启动。
