# StoryOS R16 写入边界审查：正式作品持久化与草稿迁移

日期：2026-10-13
审查范围：当前单机生产工作区、R9-R15 只读 API、前端 localStorage、正式 Episode/MySQL 持久化入口。**本轮未获授权修改生产 MySQL schema、真实 Episode 文件或 Redis。**

## 现场确认与关键判定

- Web 的正式作品目录使用 \`GET /api/v1/runtime/statuses\`；R15 可核验 11 部来自真实本地 Episode 的数据，但只是**只读投影**。R13 Provider 调用窗口也是观察而非新 Writer。
- 当前浏览器私有项目使用 \`storyos_projects\`；本地草稿使用 \`storyos_local_story_drafts_v1\`；最近故事使用 \`storyos_recent_story_ids\`。新建项目及故事操作没有经过正式 Runtime Writer，也不等于持久化生产任务。
- 前端启动的 \`scripts/storyos_local_readonly_api.py\` 以只读账户和显式 GET 目录监听；POST 写接口被拒绝，前端不能自行升级成生产持久化。
- 当前真实作品和历史静态剧集目录仅部分唯一匹配；**标题或近似标题不能作为权威外键**。现有 Run ID、Episode ID 与 Draft ID 也不能简单拼接。

## R16 本轮可安全交付

1. 浏览器草稿及项目可**人工触发导出版本化 JSON 备份**，并严格校验后有明确确认地恢复到本浏览器。导入只追加，遇到任何 ID 冲突完整拒绝，不覆盖原作品、项目或正式 Runtime。
2. 备份只包含浏览器本地项目和草稿，不把正式 Runtime Episode、历史 Frame/审核事实或 MySQL Token 当成草稿备份。明确提示下载/文件本身需由使用者自行保管。
3. 任何历史身份绑定仍维持 R15 的唯一业务编号 + 标题匹配合同；需要人工审查的重命名/拆分/合并留在待核对状态，不自动写入生产身份映射。
4. 保留 \`3100\` 和 \`19117\` 只读服务，禁止引入新的生产写请求、后台 Provider 调用、自动迁移或 MySQL 结构变更。

## 真正的下一阶段服务端持久化需要哪些条件

正式项目/草稿服务端写接口建议**独立于只读监控端口**，先完成：
- 单机唯一 Writer/操作权限认证；CSRF 防护，专用账户权限，不允许由本机只读 GET 服务升级成 INSERT。
- Episode/Project 正式主键分配，明确业务 code 与本地目录身份的主键关系；维护 \`draft_id -> canonical_episode_id\` 经人工确认的迁移映射及审计来源。
- \`request_id\` 幂等、创建草稿与提交为正式生产对象的不同状态机边界、乐观版本检查、只追加审计、失败无中间态。
- 首先在独立临时 TEST_ONLY MySQL/工作目录验证：新建、重试、冲突、不一致、跨浏览器加载、失败回滚、重复提交，且与现有 Generation Attempt/Writer 五图容量契约无冲突。
- 上述验证及明确授权后，才考虑正式打开受控写入口。绝不可把浏览器 JSON 恢复声称为正式项目入库。

## 安全验收

R16 后端静态防护测试：\`tests/platform/test_r16_readonly_persistence_boundary.py\`。保持本机只读 API 禁止 POST，前端草稿操作不使用未授权生产 URL。真实 POST 必须 HTTP 403。
