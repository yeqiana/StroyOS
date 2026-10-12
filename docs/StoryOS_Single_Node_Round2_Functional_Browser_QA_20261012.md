# StoryOS 单机精简 · 第二轮四槽功能验收（浏览器证据）

日期：2026-10-12
原始单机候选基线：`f81b9a87`
范围：**非付费、未发布、独立 Worktree**。不修改正式 MySQL、Redis、生产 Driver、历史 Episode 或真实 Provider。

## D 槽：真正离线 Chromium 验收

使用隔离 Worktree 的现有 `web-console` Vite 代码构建：`npm run build` **PASS**，3215 模块处理，未修改任何前端源码。通过仅在 Worktree 中的本地 Junction 复用根目录已安装的 `node_modules`，没有修改根工作区依赖、没有网络安装。

运行 `npm run test:console`：**5/5 PASS**。离线 Chrome 真正渲染工作台、生产监控、工作流、Agents、故事制作导航及预期离线降级提示。

运行 `npm run test:accessibility`：**3/3 PASS**。检查工作台、生产监控、工作流的标题、侧栏导航、可访问按钮名称以及 1366px 下无水平溢出。

运行 `npm run test:episodes`：**11 个历史作品详情与已有基线一致**。首屏只载入轻量目录，详细证据需在相应故事页面读取。

**边界**：浏览器用的是构建后静态页面 + 离线/测试模式，并不是连接真正业务 MySQL 的全链路页面验收；本轮未修改 UI 样式，所以没有新的 UI 改造前后对比截图。没有实际触发正式创建、图片生成或发布。

## A/B/C：真实单机业务回归

- A：此前存在实质问题：`storyboard_density_gate.validate()` 在 release 帧数为 0/缺失，且分镜密度数据为空但状态为 LOCKED 时可能返回空错误列表。此次增加 `body_frame_count` 正数门禁；真实非付费测试覆盖缺失、零、20 帧无明细、允许 draft 等边界。故事规划及 Visual Lock 测试合计 **55 passed + 5 subtests passed**。
- B：直接使用已有 `production_queue_canary.run_isolated_canary()`，连续执行三次完整生产队列激活 → Workspace 新任务写入 → 回滚，检查队列资源全部保留、临时目录清空、Runtime Workspace 全局覆盖恢复。专项 **12 passed**。
- C：针对 Product Review 生命周期，已取消和来源 SHA 变化（SUPERSEDED）的旧 Review 不能被旧候选假冒 PASS，禁止写入 `final_path`。专项 **11 passed**。真正的作品发布和出图不在本次验收范围。

## 当前决定

保留原来 StoryOS 单机 Driver + 本机文件锁、MySQL Attempt、五图 OS Permit、现有 Gateway，不添加 Redis Cluster、跨主机容量、额外 Worker Grant 或 Provider Consumer 服务。

**最终去重集成回归：241 passed、12 skipped、5 subtests passed，0 failed（23.11 秒）。** 此测试只涵盖经过显式选择的单机 Owner/Attempt、真实本机五图锁、故事分镜/Visual Lock、生产队列、审核/Release 门禁等用例，不代表全仓库完整功能验收。12 skipped 为本轮未启动独立 TEST_ONLY MySQL 写入准入的旧测试；上一轮隔离 MySQL 专项 26/26 成功，不应被当成本轮重新执行。

四槽原始提交：A `7f7c4675`、B `66b75f54`、C `6b0b0440`、D `acb37193`；单机集成提交：A `c2768f56`、B `eef823ee`、C `3157f2d3`、D `bafaa94a`。隔离工作树与正式主分支未混用。

## 必须保持的阻塞

1. 真正正式故事创建 → 可付费图片生成 → 审核 → 作品详情尚未执行实付费全链路，本轮 **不能声称已上线**。
2. 交互式 Windows Task Scheduler Carrier 启动仍需要桌面身份准入专项，不通过伪造身份绕过。
3. 浏览器离线测试不等于已验证真实业务后台；在获得适当测试后端、脱敏账号和非付费凭据后才能开展端到端功能验收。
