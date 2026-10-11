# StoryOS Web Console R28 · 全部一级菜单布局重构验收（2026-10-11）

基线分支：`story-platform-v3-rever`，R27 HEAD `6c7501bc`。
范围：**7 个可进入的一级业务与管理页面**。明确冻结 **故事制作 / workbench** 与 **作品详情 / SeriesLibraryView 内 Drawer**，不调整其代码、交互或数据来源。

## 1. 目标与设计约束

- 对所有尚未统一的一级页面做一次可操作的布局重排，而不是改换颜色或再叠加大卡片。
- 采用既有 `DESIGN.md` 中的深中性底色、224/64px 侧导航、52px 顶栏、4px 栅格、Ant Design 统一搜索/筛选/表格/分页/Tab。
- 优先显示有证据的内容；局部信息不足则用可追溯的只读说明和紧凑空状态替代模拟运行数据。
- 增加密度和真正可点击的筛选；保留已有原始 Runtime API 合同、只读门禁、历史 Run 详情。
- 保留已经完成的 R25–R27 创作画布、分镜翻页、双图对照、快捷定位与作品详情检视，避免重复改造。

## 2. 所有一级入口与交付状态

| 导航 | 页面文件 | 本轮新布局 | 首屏主数据 |
|---|---|---|---|
| 工作台 | `HomeOverviewView.tsx` | 上部统一概况/异常/快捷入口；下部全宽 `Table`；Native `Input.Search`、分页和可点击行 | 工作区作品目录，覆盖原双栏主列表空间 |
| 作品与项目 | `SeriesLibraryView.tsx` | 概况条、批准素材筛选、已批准作品真实封面画廊 + 未有批准图片作品紧凑列表；原列表 Tab 保留 | 本机真实批准素材与作品记录分别标注 |
| 生产监控 | `ProductionMonitorView.tsx` + `RuntimeAuthorityPanel.tsx` | 阶段证据/历史 Run 独立 Segmented；阶段分布直接作为可点击快捷筛选；全宽作品状态表 + 搜索、阶段筛选、分页 | Platform API 只读阶段快照（本机文件不代表在线 Runtime） |
| 工作流 | `WorkflowWorkspaceView.tsx` | 七阶段数量带支持快捷筛选；作品状态表优先；完整七阶段参考流程移到折叠区域 | 实际加载阶段记录，明确非 Worker 执行态 |
| Agents | `AgentWorkspaceView.tsx` | Registry 主表 + 独立 Memory 搜索双栏，窄屏堆叠；原生筛选、分页、注册详情抽屉 | Registry/Memory 的实际 API 返回；接口不可用不造注册列表 |
| 审计日志 | `RuntimeLogsView.tsx` | 已加载事件统计条、统一 AntD `Input.Search` + `Segmented` 级别 + `Select` 模块，完整表格填充页面 | 仅前 100 条已加载事件，403 不伪造日志 |
| 系统设置 | `SettingsView.tsx` | 原生 AntD Tabs 保留，主题设置和权限说明在宽屏双栏、1024px 纵向堆叠，取消原 860px 宽度上限 | 真实浏览器主题与不可写 Runtime 权限说明 |

### 严格冻结区域

- 未修改 `web-console/src/App.tsx` 和 `web-console/src/components/ActivityStream.tsx`。
- 未修改 `StoryRunDetailView.tsx`、历史 Run 数据、正式生产编排。
- `SeriesLibraryView.tsx` 中的 `Drawer` 从 `<Drawer open={selectedEpisode!==null} ...>` 起至 `</Drawer>` 整块内容保持原样，修改仅是一级作品库页面排版与筛选。
- 无数据库、Redis、Gateway、Agent 启停或生图计费状态修改。

## 3. 真实浏览器视觉与交互验收

新增 `web-console/scripts/test-r28-all-menu-browser.mjs`，执行 `npm run test:r28`：

- 1440px：`overview`、`library`、`monitor`、`workflow`、`agents`、`logs`、`settings` 七个一级页面逐一点击进入；
- 1024px：全部七个入口再分别检查。
- 每个页面验证页面标题、最重要主数据、真实源说明、主要过滤交互、可用宽度和**不发生全页面横向溢出**；
- 工作流需要等待真实已载入行，而非 `Spin` 占位后才保存截图；
- 素材画廊需确认至少两张已批准图片在 Chrome 中已解码；筛选切换可恢复完整目录；
- Agents/审计 API 在当前本机只读后端不可用时，验证清晰的说明而非假 Agent/日志；
- 系统设置保留原 Theme Segmented 与 Tab，同时验证生产配置显示只读无授权。

截图存放在本机忽略目录 `.storyos-tmp/ui-qa/r28/`，命名：
`storyos-r28-{overview,library,monitor,workflow,agents,logs,settings}-{1440,1024}.png`。
基于真实同页 Chrome CDP `Page.captureScreenshot`，并不把测试截图当成在线生产状态。

## 4. 回归矩阵与边界

- `npm run lint`：TypeScript / JSX 0 错误。
- `npm run build -- --base=./`：Vite 生产构建。
- `npm run test:r28`：七菜单 × 两宽度 = **14 场景**。
- `npm run test:r25`：作品详情/故事制作链路 6/6（冻结功能不变）。
- `npm run test:r24`：主导航、工作流表、生产监控历史 Run 5/5。
- `npm run test:r23`、`test:r22`、`test:responsive`：历史布局与交互合同。
- `npm run test:media`：真实批准图片解码、无批准素材绝不串到别的作品。
- `npm run test:episodes`、`test:runs`、`test:bundles`：11 个冻结作品/Run 的数据与懒加载兼容。
- `npm run test:local-real`：本机只读工作区记录确实来自磁盘（20 条状态），**不代表实时工作流**。
- 其他任务的 `reports/account-pattern-registry.json` 以及其他未跟踪数据没有纳入 R28 Git 变更。

## 5. 已知限制与后续

- 这个本机只读部署 `/api/v1/agents`、`/api/v1/events` 并非完整可写生产能力；Agents/审计日志可能只有清晰的“不可用”空态。不能虚构注册与日志记录来填空间。
- 本轮不改用户明确冻结的故事制作与作品详情，也不通过漂亮的模拟数据粉饰空状态；仅完善一级入口的展示与检视。
- 后续若接入正式 Registry、Event 和在线 Worker，应另作数据权限与可观测性工作，而不是在此混用本机历史快照。
