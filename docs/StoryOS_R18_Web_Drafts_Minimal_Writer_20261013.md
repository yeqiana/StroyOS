# StoryOS R18 — 最小正式服务端草稿存储

本功能是 Web 项目和故事**草稿**保存，不是正式 Production Episode 创建。

## 设计
- 使用 mysql8.0 的独立 STORYOS_WEB_DRAFTS schema，不修改 STORY_OS_RUNTIME。
- WEB_DRAFT_WORKSPACE 保存本机自建项目/故事草稿、版本与稳定服务端身份映射。
- WEB_DRAFT_REQUEST 保证 request_id 幂等；只有两张表、创建/列表/读取/更新四条 API。
- 服务端草稿身份 WDP_ / WDE_ 与正式 TB_EPISODE 主键不同，不会启动生产。
- 复用单机 loopback、授权口令、15 分钟会话、Origin 和 CSRF 防护；冲突更新返回 409。

## 运行
- 本机准备独立受限数据库账号；账号只对 STORYOS_WEB_DRAFTS 有 SELECT/INSERT/UPDATE。
- 将配置放在主工作区 Git 忽略目录 .storyos-tmp/web-drafts：web-draft-auth.json、web-draft-operator-token.txt、python-exe.txt。
- 从仓库根执行 node scripts/launch-web-drafts.mjs，启动独立服务 127.0.0.1:19119。
- Web Console 在 3100 把 /api/v1/web-drafts 代理至 19119；原 Runtime 19117 继续只读。
- 端口只监听 loopback，禁止开放公网。

## 已有测试
- pytest tests/platform/test_web_draft_writer_mysql.py：真实测试 MySQL 限权、版本、同请求并发。
- node web-console/scripts/test-web-draft-writer-http.mjs：授权、CSRF、幂等、冲突、跨会话。
- node web-console/scripts/test-web-draft-writer-browser.mjs：独立 Chrome 用户保存/恢复。

## 不做
- 不直接插入 TB_EPISODE；不领取 BUSINESS_EPISODE_ID；不创建 Runtime Request；不启动 Driver、图片或视频。
- 草稿进入生产需单独经正式 Episode Bootstrap 和权限门禁。

## R19：最小生产交接预检（只读）

- 新增 GET `/api/v1/web-drafts/{workspace_id}/handoff-plan`，只读取当前已保存的草稿版本与 WDE_ 身份映射，生成候选清单和既有 `story_os.py create --dry-run --json` 命令数组。
- Web Console「生产交接预检（只读）」仅显示建议命令，不执行 Python、Codex 或 Driver；没有新数据表、调度器或任务队列。
- 结果包含工作区版本与快照 SHA，用于识别后续编辑；`admission_granted=false`，`canonical_episode_created=false`，`production_started=false`。
- 真实 Episode 创建、编号领取与付费生产仍须后续独立人工确认并通过已有 canonical Bootstrap 和 Gate。不要把预检计划当作生产准入批准。

## R20：受权执行真实 canonical dry-run

- 浏览器在 R19 只读交接清单中，为单条候选草稿点击“执行真实只读预检”，人工确认后才调用 `POST /api/v1/web-drafts/{workspace_id}/preflight`。
- 服务端**重新读取当前持久化版本**，同时比较 `workspace_version`、`source_sha256`、`WDE_` 身份；旧版本 409，缺失身份 404/422，CSRF 不合法 403。
- 严格通过 argv 调用已存在的 `episodes/_system/story_os.py create <synopsis> --title <title> --dry-run --json`，没有 shell、没有 `--full-auto`，24 秒内必须返回 `dry_run=true,written=false,created=false,workflow.invoked=false`，否则一律拒绝出具通过回执。
- Canonical CLI 查询独立 SELECT-only 账号：Git 忽略目录 `.storyos-tmp/web-drafts/preflight-mysql-readonly.json`，环境变量由 `scripts/launch-web-drafts.mjs` 在本机显式提供。只授权 `STORY_OS_RUNTIME.*` 的 SELECT，无写权限。
- R20 只新增一个路由和极少按钮，**没有新表、Writer、调度器、编号、生产任务、Codex 或图片视频生成**。
- 全部单元/HTTP/浏览器测试依然使用 TEST_ONLY MySQL；正式 CLI 读取预检若发生数据库/脚本错误，直接显示阻断，不可冒充已创建。
- 必须提醒：单独调用 `story_os.py create`（没有 dry-run）可能进入 Runtime workflow，不能将其当成纯 Episode Bootstrap 暴露给 Web Console。正式创建仍未开放。
