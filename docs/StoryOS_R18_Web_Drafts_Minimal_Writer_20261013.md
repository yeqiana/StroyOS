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
