# StoryOS R16 · 浏览器草稿迁移安全准备与正式持久化边界

日期：2026-10-13
基线：b3d013d7（包含并行 M00 迁移路径修复）
候选分支：refactor/storyos-r16-integrated-20261013

## 本轮实际交付（四槽）

A / **权限和持久化审查**：新增 \`docs/StoryOS_R16_Controlled_Persistence_Boundary_20261013.md\`、\`tests/platform/test_r16_readonly_persistence_boundary.py\`。后端仍是只读 \`GET\` Dispatcher，所有正式生产端口不接收本轮新写操作；没有新增 MySQL 表、迁移映射写入、Redis Writer 或 Provider 调用。真实服务写入经 3100 拒绝 HTTP 403。

B / **备份与迁移数据合同**：新增 \`web-console/src/api/localDraftBackup.ts\`。带版本标志 \`storyos-local-draft-backup\`、源 \`browser_local_only\` 的 JSON 仅包含本地草稿和用户自建项目；4 个已内置默认项目不重复导出，避免新浏览器预置项目 ID 冲突。恢复拒绝无效 JSON、过大文件、错误版本、伪造来源、非草稿 Episode ID、重复 ID、已有项目/草稿覆盖、项目引用丢失；整个备份先验证后一次性追加到浏览器 React/localStorage。

C / **实际页面**：作品库新增「本地草稿保险箱」，提供点击导出与选择 JSON 文件恢复；恢复前弹出清楚的用户确认，取消不会发生变更。异常/冲突不影响已存在的草稿和正式 Runtime。正式作品目录与历史分镜仍沿用 R15 可信身份映射；这不是一键将草稿变成正式项目。

D / **真实验收**：前端 \`test-r16-local-draft-backup-contract.mjs\` 16 个防护断言；隔离 Windows Chrome 在只读预览 \`3198/19928\` 中实际选择 JSON 文件，点击确认，观察 localStorage 新增测试草稿，并再次上传同样 ID 验证拒绝覆盖、不再出现第二个确认窗口。8/8 一级菜单及真实 11 部 Runtime 作品继续通过，生产监控和历史素材保持原有合同，截图在 \`.storyos-tmp/ui-qa/r16/storyos-r16-{overview,creator,library,monitor,workflow,agents,logs,settings}-1440.png\`。

## 验收与边界

- TypeScript lint + Vite build PASS。
- Python 只读边界 / MySQL / Provider / Driver/OS 锁相关 **38 passed**。
- 真实 Chrome 1440px **8/8** 页面通过；真实文件恢复成功后，**隔离测试浏览器**历史工作区数量会从 11 变 12，但正式 Runtime 仍 11 部，二者来源各自独立；此数据不进入实际用户浏览器资料。
- 服务端正式 Episode/Project 的 CREATE/UPDATE、跨浏览器云端同步、正式历史身份手工绑定、Task–Generation–Trace 写入关联**尚未实现**；不能把 localStorage 还原说成生产持久化。
- 不会从还原内容调用模型、不重试未决 Attempt、不打开 Writer；不重启正在生产的 Driver。
- **真正 R17/P0**：独立受权写入端口 / 专用数据库账户 / 单机 Writer admission / request_id 幂等 / 正式主键分配 / 乐观并发 / 人工迁移映射审计 / TEST_ONLY MySQL 端到端恢复验证。完成权限与风险审查后才开放正式持久化。

## 部署安全要求

四槽位独立工作树提交、集成分支 Chrome 实测；先核实主分支最新 M00 并行修复与脏文件，保留所有用户文件 SHA256 备份和回退标签，只安全 FF 合入并重启原只读 3100/19117，不碰其他现网进程。
