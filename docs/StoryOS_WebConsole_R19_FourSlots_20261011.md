# StoryOS Web Console R19｜四槽滚动优化与真实数据验收

日期：2026-10-11；基线分支：`story-platform-v3-rever`，R18 完成提交 `cf18df5b`。

## 本轮目的

在既有 R17（三轮各四槽）和 R18（四槽）基础上继续收敛可见问题：1024px 图标侧栏缺失项目快速访问，首页展开的 20 条阶段文件记录重复占用作品列表纵向空间，生产监控筛选同时采用手写 select / Ant Design 导致高度与键盘交互不一致，Run 详情指标行固定高度在窄屏下挤压。

## 四个并发隔离槽位

| 槽位 | 独立分支 | 用户可见变化 |
|---|---|---|
| 作品工作台 | `feature/storyos-r19-home-20261011` | 后置的本机阶段记录进一步改为原生 details 默认收起，按需展开完整 20 条及分页，保留来源提示和只读数据 |
| 生产监控 | `feature/storyos-r19-monitor-20261011` | 自动刷新间隔、状态和阶段筛选统一到官方 Ant Design Select，输入高度统一为 36px，保留现有业务筛选语义与只读 Runtime API |
| 窄屏导航 | `feature/storyos-r19-navigation-20261011` | 1120px 及以下的 64px 图标侧栏增加项目快捷按钮，打开 Ant Design Drawer 后可选择项目对应作品，或进入作品与项目完整页面；Drawer 使用 React.lazy 按需加载，避免增大首页主 JS |
| 历史 Run | `feature/storyos-r19-run-20261011` | 指标行取消 44px 固定高度，允许字段自然换行；主内容充分占宽，阶段网格在 1024px 及以下自适应，避免遮挡历史图片 |

## 真实性与安全约束

- 所有状态信息来自已有本机 `episode-state.json` 及只读 API，不将历史 Run/心跳解释为在线任务或平台实时健康。
- 真实批准图片延续 R16 本地媒体只读索引；不读取 `candidates`、归档、私有任意路径，不将某张批准图伪称某次 Run 的独占生成证据。
- 本轮不启动正式 Runtime、不触发生图、发布、审核写入；不重写 `episodes/` 文件，不提交未跟踪的图片和其他任务的本地变动。
- 避免自研 Drawer / Table / Select，采用开源 Ant Design + 原生 details。

## 验收记录

- 四个隔离槽位分别通过 TypeScript `npm run lint` 与生产 `npm run build -- --base=./`。
- 导航抽屉早期实现造成首页入口 JS 包约 508KB（未压缩）；改成 `React.lazy` 后首页入口包恢复约 315KB，抽屉仅首次点击时加载。
- 集成通过 `test:bundles`、`test:api`、`test:monitor`、`test:workflow`、`test:console`、`test:episodes`、`test:runs`、`test:readonly-probe`、`test:accessibility` 共 9 组核心回归。
- `npm run test:r19` 两项真实 Chrome 交互通过：1024px 窄侧栏 → 项目抽屉 → 《婚礼前夜》制作页面；1366px 首页真实阶段明细先收起、展开、切第 2 页、收起，均无整页水平溢出。
- 原有响应式、R10/R11/R12/R13 浏览器工作流和批准媒体回归继续执行；截图保存在忽略目录 `.storyos-tmp/ui-qa/r19`。
- 集成合并前需重新比较当前主分支 SHA，保护全部未跟踪文件以及其它已跟踪文件在工作树中的脏改动；仅允许满足祖先关系的快进合并。

## 下一步重点

如需更进一步的全站布局重构，建议先为故事制作与 Run 审核建立跨页面统一的页面密度/筛选/详情抽屉 UI 合同，以免后续继续出现模块级样式不一致。对大数据量的日志/运行记录，应先有真正的后端分页能力，不能通过仅前端分页伪称已实现服务端翻页。
