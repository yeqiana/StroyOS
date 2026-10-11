# StoryOS Web Console R24 · 全页面布局重新规划（2026-10-11）

## 设计决策

本次不是更换主题，而是重排页面的信息架构与主数据区域。依据仓库 `web-console/DESIGN.md`、`web-console/AGENTS.md` 和 StoryOS UI Skill，继续采用深灰、薄分割线、高密度数据表与 Ant Design 原生交互；不构造营销卡片、假图片或虚假的在线 Runtime 指标。

统一结构：左侧导航 224px（窄屏 64px）→ 顶部 48px 工作区标题 → 主数据列表/矩阵 → 右侧按需检视抽屉。桌面工作台可使用非对称双栏，其他页面表格优先；次要参考资料默认折叠。

## 四槽落地

### 1. 生产监控：单一主工作区

- 过去的“阶段证据表格 + 大段状态统计 + 历史 Run 表格”上下堆叠导致历史 Run 长期处于首屏之外。
- 新增 Ant Design Segmented 主视图导航：`阶段证据 (已载入数量)` 与 `历史 Run (历史索引数量)`。只显示当前主视图的数据列表，首屏即进入表格。
- 默认阶段证据，保留只读平台来源与断网提醒；切换历史 Run 显示其独立状态条、搜索、筛选及分页。
- 两套状态仍绝对独立；历史 Run 快照不是在线执行状态，不能冒充 Worker 心跳。切换 tab 不重置已设定的 Run 筛选。
- `RuntimeAuthorityPanel` 默认每页 12 条记录（原 6 条），减少人工翻页与列表下方留白；新增原生 12/20/50 分页档位。
- 不变更 Platform API、请求去重、后台 100→101 分页策略。

### 2. 故事制作：非对称左右工作区

- 已批准素材（如果有）仍单独一行；“当前批次”与“逐帧审核”在宽屏下并排显示（左侧为主要批次、右侧为审核辅助轨）。
- 实际展示采用 1.55:1 主辅列 + 16px 间距。窄屏自动回到单列，不让审核栏挤压批次记录。
- 无原图批次按状态格展示、在双栏下最多五列（超宽 8 列），避免在 600px 左侧轨道硬塞 10 列。
- 继续保留 `WARN/FAIL` 快捷筛选与审核数据分页、只读动作警示。

### 3. 工作流：完整表格主视区

- 默认每页 20 条（原 15 条）；列表成为页面主体，当前完整 20 条真实作品记录可以在同页查看。
- 合并记录数量信息与标题，减少重复副标题和分割空间；标准七阶段说明仍默认折叠。
- 保留排序、搜索、重置、点击整行检视和右侧 Drawer，以及未加载全部数据的事实边界。

### 4. 历史 Run 详情：图像证据驱动的默认布局

- 有可验证的缩略图或本地已批准图片时，默认分镜矩阵；没有可信图片时，默认 Ant Design 状态表格。
- 保留手动切换“缩略矩阵 / 状态列表”，不移除 20 帧操作与抽屉。
- 默认列表依旧显示所有有证据字段（帧、分镜代码、状态、耗时、尝试次数、原图是否可信），不生成虚拟缩略图。

## 新版浏览器截图

R24 Chrome 真正打开用户本机只读控制台，用户可查看本机项目文件：

| 页面 | 截图文件 | 宽度 |
|---|---|---|
| 故事制作双栏 | `.storyos-tmp/ui-qa/r24/storyos-r24-workbench-dual-column.png` | 1366px |
| 生产监控·阶段主视图 | `.storyos-tmp/ui-qa/r24/storyos-r24-monitor-primary-stages.png` | 1366px |
| 生产监控·历史 Run 主视图 | `.storyos-tmp/ui-qa/r24/storyos-r24-monitor-history-switch.png` | 1366px |
| 工作流·完整列表 | `.storyos-tmp/ui-qa/r24/storyos-r24-workflow-full-list.png` | 1280px |
| Run·无可信原图自动表格 | `.storyos-tmp/ui-qa/r24/storyos-r24-run-auto-list.png` | 1024px |

验收检查了 5 个对应场景的可交互组件、列表行数/切换结果、阶段数据来源、分镜默认表格以及无视口横向溢出；并保留老版网格的显式入口。

## 验证命令

- `npm run lint`：TypeScript/项目 lint
- `npm run build -- --base=./`：Vite 生产构建
- `npm run test:r24`：R24 新布局真实 Chrome 5 场景
- `npm run test:r23`：R23 对应页面交互
- `npm run test:r22`、`npm run test:r20`：旧版流程导航和网格兼容（因布局变化同步更新测试前置的历史 Run 视图切换）
- `npm run test:r19`、`npm run test:responsive`：侧边栏/页面导航/折叠与响应式
- `npm run test:workflow`、`npm run test:monitor-pages`、`npm run test:console`、`npm run test:episodes`、`npm run test:runs`、`npm run test:local-real`、`npm run test:bundles`：旧版烟雾、业务基线、事实来源与性能。

本地 3100/19117 模式只读真实磁盘状态，不能据此宣称在线 Scheduler 运行正常；审计接口不可读取时继续提示，不用假数据填充页面。

## 发布与保护

- 仅改动 R24 布局相关前端文件、对旧浏览器测试的必要更新、新 R24 测试、package 脚本和验收文档。
- `reports/account-pattern-registry.json` 与其他任务的全部未跟踪/未提交资产保持原样。
- 后续建议：在 R25 针对更窄屏幕对筛选控件顺序、分页跨页定位以及经验证的列表排序状态做专项细化；不要恢复长页面堆叠。
