# StoryOS Web Console R23 · 四槽滚动优化与真实页面验收

日期：2026-10-11 · 分支：`story-platform-v3-rever`

## 总目标与事实边界

R23 在 R22 `38009e8b` 基础上继续优化操作台。沿用既有 DESIGN.md 的高密度、表格优先、薄分割线与 Ant Design 原生控件，不新建营销式大卡片，不冒用工作区状态作为实时 Runtime。

本次保持所有 API、状态机、只读本机状态文件及冻结的历史 Run / Episode 快照事实不变。运行方式为本机 `http://127.0.0.1:3100/` + `19117` 文件证据 API。

## 四槽交付

### ① 故事制作 · 审核关注过滤

文件：`web-console/src/components/ActivityStream.tsx`

- 逐帧审核支持 `NEEDS_ATTENTION` 仅聚合真实 `WARN` / `FAIL` 记录；不会把 `PASS` 当作待处理。
- 有待查记录时，显示一键 `只看待查 (N)`，自动展开并重置至第一页；无待查记录时只展示 `暂无待查记录`，不摆放无意义禁用按钮。
- 复用现有 Ant Design Select / Pagination；审核记录行内间距由 `py-3` 收至 `py-2`，减少无意义高度。
- 当前工作区真实快照全部通过，不借虚拟问题伪造警报。

### ② 生产监控 · 只读阶段筛选

文件：`web-console/src/components/views/RuntimeAuthorityPanel.tsx`

- 只读权威证据表格新增 Ant Design `筛选权威阶段`，候选项根据已加载的 `production_stage` 自动生成。
- 选择阶段只过滤本次已读取列表，匹配数与 Table 分页总数联动；切换筛选时重置页码，不改变服务端 offset 或历史 Run 列表。
- 本地文件 API 的 `UNKNOWN` 或 `未提供` 保留真实证据语义；仍可点击行打开右侧详情抽屉。
- 原有只读阶段总数、数据来源标识、缺失字段与未加载完成告警保留。

### ③ 工作流 · 排序与快速详情

文件：`web-console/src/components/views/WorkflowWorkspaceView.tsx`

- 名称、更新时间列复用 Ant Design Table 原生排序。
- 点击任意有数据的作品行可直接打开 440px 阶段检视器；操作按钮与行点击不会重复处理事件。
- 有搜索条件时显示 `重置筛选`，一次恢复全部已载入记录并回第一页；选定作品的详情不会因刷新被无故收起。
- 现有搜索、筛选、分页与只读摘要保留。

### ④ Run 详情 · 分镜展示模式

文件：`web-console/src/components/views/StoryRunDetailView.tsx`

- 在原缩略矩阵外，新增 Ant Design `Segmented` `缩略矩阵 / 状态列表` 切换，原始网格仍为默认，防止旧交互倒退。
- 状态列表展示真实 `Frame No.`、`frameCode`、原始状态码、历史耗时、尝试次数与经证实的原图存在与否。
- 20 帧状态按每页 10 条分页；点击列表行继续打开既有分镜检视器，支持关闭回原列表。
- 没有已验证素材时不生成占位图片；历史 Run 仍仅用于追溯，不能据此声称实时 Worker 心跳。

## 真实 Chrome 截图

使用运行中的本机只读 StoryOS 控制台，逐条完成浏览器交互并生成截图，而非 UI mockup。

| 槽位 | 宽度 | 本机文件 |
|---|---:|---|
| 故事制作审核 | 1366px | `.storyos-tmp/ui-qa/r23/storyos-r23-story-review-focus.png` |
| 生产监控阶段筛选 | 1280px | `.storyos-tmp/ui-qa/r23/storyos-r23-monitor-authority-filter.png` |
| 工作流排序与抽屉 | 1280px | `.storyos-tmp/ui-qa/r23/storyos-r23-workflow-sort-inspector.png` |
| Run 分镜状态列表 | 1024px | `.storyos-tmp/ui-qa/r23/storyos-r23-run-frame-status-list.png` |

截图仅为真实页面表现；`UNKNOWN`、未提供原图等均是实际只读证据状态。

## 验收矩阵

| 验收 | 本轮结果 |
|---|---|
| `npm run lint` (TypeScript) | 通过 |
| `npm run build -- --base=./` | 通过 |
| `npm run test:r23` | 4/4 真实 Chrome 页面交互 + 截图 |
| `npm run test:r22` | 4/4；修复工具栏新增后的旧测试定位选择器 |
| `npm run test:r20` | 3/3 |
| `npm run test:r19` | 2/2 |
| `npm run test:responsive` | 4/4 |
| `npm run test:console` | 5/5 |
| `npm run test:workflow` | 2/2 |
| `npm run test:episodes` | 11/11 冻结历史作品 |
| `npm run test:runs` | 11/11 冻结历史 Run |
| `npm run test:monitor-pages` | 100→101 后端分页/重复请求隔离通过 |
| `npm run test:local-real` | 本机真实文件状态 20 条及来源验证通过 |
| `npm run test:bundles` | Episode / Run 按需分包检查通过 |

注：R23 浏览器专项验证生产阶段过滤控件、当前匹配数、分页与阶段详情；选项实际切换采用 Ant Design 已有 `onChange` 控制逻辑，自动化脚本未模拟该项合成事件驱动的下拉选项点击，不声称已覆盖该单项。服务端分页与并发边界另由 `test:monitor-pages` 保障。

## 剩余建议

继续压缩无必要标题解释与重复边框；对尚无真实原图的 Run 默认仍保持缩略矩阵，但使用状态列表可立即提高扫描效率。后续可在稳定事实字段基础上统一审计日志空状态、历史 Run 操作面板、工作流阶段列密度，继续每轮提供真实页面截图。

## 仓库保护

其他任务的 `reports/account-pattern-registry.json` 修改及既有未跟踪工作区证据均未触碰。本轮仅提交上述 UI、必要的 R22 测试适配、新增 R23 浏览器脚本、package.json 命令以及本文件。
