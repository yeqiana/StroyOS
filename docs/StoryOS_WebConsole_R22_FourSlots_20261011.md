# StoryOS Web Console R22 · 四槽位滚动优化与截图验收

日期：2026-10-11 · 分支：`story-platform-v3-rever`

模式：本机真实工作区状态文件 · 只读（不是在线生产 Runtime）

## 一、四槽位落地

### 槽位 1 · 修复过期浏览器入口

- R19 浏览器验收脚本默认端口 `3113`，而目前本地真实只读控制台工作在 `127.0.0.1:3100`，造成 `collapsed-projects missing` 假性回归失败。
- 更新 R19 测试默认地址为 `3100`，保留 `STORYOS_LOCAL_CONSOLE_URL` 显式覆盖能力。R19 导航快捷面板与首页阶段展开 / 分页 **2/2 通过**。
- 同类问题：R17 响应式测试仍指向旧的 `3111`，同步修正为 `3100`；R17 响应式 **4/4 通过**。未修改业务导航逻辑。

### 槽位 2 · 生产监控 Inspector

- `RuntimeAuthorityPanel.tsx` 阶段详情由压缩工作台的表格底部展开区改为 Ant Design 右侧 Drawer，最大 `440px`、窄屏不超过视口。
- 阶段摘要（正式阶段、状态来源、更新时间）总是保留；详情接口不可用时不制造虚假心跳、执行态或帧计数。
- 关闭抽屉不丢失列表、页码和刷新选项。

### 槽位 3 · 工作流搜索与详情

- `WorkflowWorkspaceView.tsx` 新增 Ant Design 原生作品名 / 标识搜索，直接过滤已加载的只读记录；匹配数与未加载完毕提示清晰展示。
- 搜索改变时重置页码，刷新不再强制关闭正在查看的详情 Drawer。
- `WorkflowDetailPanel.tsx` 详情摘要始终可见；扩展详情失败时仍显示有依据的阶段、来源和更新时间。
- Drawer 使用 `min(440px, 100vw)` 适应小屏。

### 槽位 4 · 真实 Chrome 页面验收

- 新增 `scripts/test-r22-four-slots-browser.mjs`，`npm run test:r22`。
- 验证生产监控阶段 Drawer、工作流搜索及恢复列表后的 Drawer、生产监控原生搜索与复选框、Run 缺少原图时的紧凑 20 帧布局。
- 1366 / 1280 / 1024px 真浏览器，逐页验证无视口水平溢出，且不以虚拟示例状态替代后端响应。
- 截图由浏览器实时生成：

| 截图 | 分辨率 | 内容 |
|---|---|---|
| `.storyos-tmp/ui-qa/r22/storyos-r22-monitor-inspector.png` | 1366×900 | 生产监控阶段证据右侧抽屉 |
| `.storyos-tmp/ui-qa/r22/storyos-r22-workflow-inspector.png` | 1280×900 | 20 条工作流列表及右侧抽屉 |
| `.storyos-tmp/ui-qa/r22/storyos-r22-monitor-filters.png` | 1024×900 | 生产监控 Ant Design 工具栏 |
| `.storyos-tmp/ui-qa/r22/storyos-r22-run-compact-frames.png` | 1024×900 | 真实历史 Run 无原图紧凑分镜 |

> 截图在用户本机 `.storyos-tmp` 目录（临时验收证据），不会错误提交到业务资产库。

## 二、验证矩阵

| 检查项 | 结果 |
|---|---|
| `npm run lint` / TypeScript | PASS |
| `npm run build -- --base=./` | PASS |
| `npm run test:r22` | PASS 4/4 |
| `npm run test:r19` | PASS 2/2 |
| `npm run test:responsive` (R17) | PASS 4/4 |
| `npm run test:r20` | PASS 3/3 |
| `npm run test:console` | PASS 5/5 |
| `npm run test:workflow` | PASS 2/2 |
| `npm run test:local-real` | PASS（本机真实阶段记录20条） |
| `npm run test:runtime-coverage` | PASS（5类覆盖率边界） |
| `npm run test:monitor-pages` | PASS（服务端101条分页/并发防重） |
| `npm run test:episodes` | PASS 11/11 |
| `npm run test:runs` | PASS 11/11 |
| `npm run test:bundles` | PASS（按需分包11/11） |
| `git diff --check` | PASS |

## 三、证据边界、已知问题与后续方向

- 该环境 `3100` 页面联动 `19117` 只读文件 API；页面标注的 `UNKNOWN` / 未提供来自真实读取结果，不等于已确认在线状态。
- 审计事件 API 在本机只读证据模式下不可读，继续清晰显示不可用状态，不注入伪造审计记录。
- 当前 Run 概览缺乏真实缩略图时只展示验证过的历史帧数据，不捏造原图；空白区域不为装饰而塞卡片。后续可以增加有事实依据的事件摘要以提升浏览价值。
- 不改变生产 API、工作区权威状态机与后台任务，不改动其他开发任务的 `reports/account-pattern-registry.json` 或任何无关未跟踪文件。
