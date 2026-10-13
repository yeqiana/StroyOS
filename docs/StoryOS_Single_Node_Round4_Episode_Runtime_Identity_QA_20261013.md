# StoryOS 单机精简第四轮 · 四槽真实验收记录

日期：2026-10-13
基线：`640a9da5`
集成分支：`refactor/storyos-single-node-integrated-20261012`

边界：单机 MySQL、Redis、本机 Worker、整机五图；没有增加分布式服务、真实生图、发布或生产数据修改。原主分支的未提交修改不参与本轮。

| 槽位 | 范围 | 验收 |
|---|---|---|
| A | 删除本地项目时保留其本地草稿，解除悬空 `projectId`；历史作品不动 | 6/6 |
| B | 生产监控分页依据 `episode_id` / `episode_ref` 等身份别名去重；同名不同作品不合并 | 6/6 |
| C | 阶段证据详情切换 Episode 时渲染期再核验身份，不将旧详情或恢复诊断混入新作品 | 5/5，旧恢复安全 14/14 |
| D | 复用离线 Chrome 真实新建/刷新/编辑、五菜单可见性、只读恢复与历史作品详情测试 | 真正离线 Chromium 4/4 组 |

## 测试边界

本轮分支与既有 `R38` 的 Redis Cluster / Worker Grant / Provider Consumer 实验隔离；不需要额外 MySQL 表或 Worker 进程服务。本轮只读 Browser 使用静态本地网页，截图来自隔离 Chrome Profile，不表示正式 Runtime 已连接。

## 独立工作槽验收事实

- A 仅删除项目的归属关系，不删除本地草稿或更改历史作品；六种边界通过。
- B 同一 Episode 有时只返回 `episode_id`、有时同时返回 `episode_ref`，分页合并现改为所有声明的身份别名去重；不同 Episode 同标题仍分开。六项通过。
- C 后端请求响应仍由原 `runtimeDetailMatchesEpisode` 验证；额外在**渲染时**按当前选中作品过滤旧详情，防止旧响应瞬间出现在新作品抽屉。五项通过，另原只读恢复安全 14 项通过。
- D 真正离线 Chrome 执行 `create-reload-workbench`、五个一级菜单、只读恢复合同、11 部历史作品详情，四组均通过。原始 1440px Chrome 截图位于该隔离 Worktree 的 `.storyos-tmp/ui-qa/r32/storyos-r32-draft-1440.png`。本地浏览器 screenshot 不证明后端实时可用。

**进一步的集成构建、真实 Browser、Git SHA 以最终单机集成分支补充记录为准。**
