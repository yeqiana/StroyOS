# StoryOS Web Console R18｜四槽位滚动视觉收敛与验收

日期：2026-10-11

## 本轮基线和目标

本次以主分支 `story-platform-v3-rever` 的 `7ca7d63a` 为四槽统一基线。R17 三轮四槽改造此前已经经其他并发工作合并，**不重复合并旧 R17 集成树**。R18 面向明确存在的剩余问题：1024px 时侧栏过宽、首页重复入口及大面积指标空白、监控权威表占满首屏、工作流机器标识噪音、审计日志操作文案误导。

遵循根目录 `DESIGN.md`：开源 Ant Design 组件优先，数据主区优先，清晰一致的字阶与来源提示；不添加大型卡片或假在线指标。

## 四槽隔离交付

| 槽位 | 文件 | 改造 |
|---|---|---|
| Shell 与响应式 | `Sidebar.tsx`、`index.css` | 窄桌面（宽度不超过 1120px）将主导航从 224px 收至 64px，项目树入口通过作品与项目页继续可用；导航按钮保留 aria-label/title 与键盘访问。工作台保留顶部“新建故事”，不再重复显示侧栏创建按钮 |
| 首页与作品库 | `HomeOverviewView.tsx`、`SeriesLibraryView.tsx` | 三项统计收成紧凑数字摘要，腾出首屏内容；作品库使用 Ant Design 标题/更新时间真实字段排序，更新时间无法解析的记录按未提供处理，无写入 |
| 生产监控与工作流 | `RuntimeAuthorityPanel.tsx`、`WorkflowWorkspaceView.tsx` | 本机状态记录每页从 10 改为 6，历史 Run 列表提前进入首屏；工作流不再默认逐条展示长 `LOCAL_...` ID，保留详情入口及屏幕阅读器文案 |
| 日志与 Run 预览 | `RuntimeLogsView.tsx`、`StoryRunDetailView.tsx` | 审计日志真实操作从“导出”改“复制日志”，移除仅清空前端列表但可能被误认为清除服务端日志的按钮；Run 大图模态框遵循视口限制 |

## 数据真实性及代码安全

- 服务使用 `web-console/scripts/launch-local-real-console.mjs`，独立验证 `127.0.0.1:3112` / 只读媒体 API `127.0.0.1:19120`，**不启动生图/发布 Runtime**。
- 原本 R16 的媒体 API 对 3 部具有批准图的作品提供真实素材投影，本次保留，不重写审核/产物归因；未批准作品保持无原图。
- 页面展示的 `episode-state.json` 和历史 Run 都是本机磁盘证据，不代表在线 Worker、队列或实时调度。
- 此轮仅改 Web Console 展示代码，严禁提交或移动 `episodes/` 私有素材。主分支合并必须校验工作区已跟踪修改的内容不被覆盖及未跟踪文件清单不变化。

## 验收明细

- 四个独立槽位均 `npm run lint` 和 `npm run build -- --base=./` 成功；集成后的 TypeScript / 生产构建通过。
- 核心回归：`test:bundles`、`test:api`、`test:monitor`、`test:workflow`、`test:console`、`test:episodes`、`test:runs`、`test:readonly-probe`、`test:accessibility` 共 **9 组通过**。
- 真实 Chrome：`test:responsive` 1024px 首页/监控及 1280px 作品库/工作流 **4/4 通过**；R10 主要页面 4/4；R11 次要页面 4/4；R12 深层工作台与 Run 详情 2/2；R13 真实分页 4/4 + 深浅主题切换通过；R16 真实批准媒体加载与未批准反例 **4/4 通过**。
- 从截图确认：1024px 首页侧栏为图标式，工作区主内容更宽；1440px 监控首屏可同时看到阶段列表及历史 Run 入口。截图在各 Worktree 的 Git 忽略目录 `.storyos-tmp/ui-qa/`。

## 待继续推进

- 侧栏 64px 模式暂不显示项目树快捷入口，用户仍能经“作品与项目”访问；未来如需要可设计基于 Ant Design Drawer 的项目快捷面板，不建议继续手搓。
- 历史 Run 与具体批准帧生成 Attempt 的权威归因仍需正式 Runtime 产物合同。
- 日志大批量数据的可扩展性与真正服务端分页，需取得后端分页契约后再改，不能把客户端分页冒称为已完成的服务端虚拟列表。
