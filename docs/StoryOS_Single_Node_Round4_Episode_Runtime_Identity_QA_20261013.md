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

## 最终四槽隔离集成验收（2026-10-13）

- 四槽独立代码提交：A `06d5b26c`，B `316c59f5`，C `8d71a47c`，D `8d1c29ff`。
- 顺序无冲突 cherry-pick 到单机隔离集成分支：A `b4b99cec`，B `adc55ac4`，C `61686b0e`，D `6d649b1f`。
- 集成 TypeScript 检查 `npm run lint` **PASS**；Vite 构建 `npm run build` **PASS**。
- 集成新功能测试：项目删除草稿保护 **6/6**；分页身份合并 **6/6**；切换作品详情隔离 **5/5**。
- 完整单机现有安全/制作回归（39 个指定测试文件去重）：**241 passed、12 skipped、5 subtests passed**。12 个 skipped 为未开启隔离 TEST_ONLY MySQL 的现有 SQL 专项，未计入通过。
- 真正离线 Chromium 执行：四组 **4/4 PASS**；其中新建草稿 → 刷新 → 回到制作页 **1/1**；离线五菜单 **5/5**；恢复安全准则 **14/14**、Episode 身份规则 **5/5**；历史作品详情基线 **11/11**。
- 集成截图：`.storyos-tmp/ui-qa/r32/storyos-r32-draft-1440.png`，真实浏览器生成 **109,398 bytes**；该图显示当时的本地工作台，不代表 UI 视觉改版。
- 没有真实 Runtime API 写入，没有真实重试、付费生图、MySQL schema 修改、发布，未触碰原主分支未提交修改。

## 剩余限制

1. A/B/C 这轮完成了纯函数及 TypeScript 集成测试，**不是**每个边界都已单独通过 Chrome 点击测试（D 浏览器测试验证主要页面及草稿流程）；不能宣称生产全流程真实可操作。
2. 分页去重仅依赖后端声明的同一 Episode 身份别名，不按同名合并；服务端身份缺失或变化不可从标题猜测。
3. 阶段详情及恢复始终只读，切换作品时未知和过期状态显示为缺少可验证证据；不能据此自动触发 Provider 或重试。
4. 当前依然是未合并主分支、未部署的单机候选。下一轮优先在安全隔离的本地只读 API 下实测阶段列表与详情切换，再考虑用户授权后的真实业务接线。
