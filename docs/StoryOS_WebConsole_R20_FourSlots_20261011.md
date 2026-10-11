# StoryOS Web Console R20：四槽位统一布局及真实状态验收

日期：2026-10-11  
目标分支：`story-platform-v3-rever`  
开发起点：`5124f589`（包含 R19 `826edefb`）  

## 目标与范围

基于 R19 已验收的工作台、生产监控、窄屏导航和 Run 页面，统一故事制作、Run 详情、审计日志的工具栏、筛选栏、主列表与详情面板。遵循 `DESIGN.md` 和 `storyos-ui-design` 约定：操作优先、表格优先、使用现有 Ant Design、减少装饰性卡片，不改动后端写入或生产事实。

## 四个隔离槽位的交付

| 槽位 | 位置 | 用户可见变化 | 真实性边界 |
|---|---|---|---|
| 1 | `src/components/views/RuntimeLogsView.tsx` | 日志模块下拉换成 Ant Design 可搜索 Select；详情改为右侧 AntD Drawer，不再将主表挤窄；统一工具栏密度及筛选高度；权限不足或后端不可用时明确展示错误提示 | 当前 `events(100,0)` 仅拉取最多 100 条；筛选与分页仅针对**已加载记录**，不能冒充服务端全集分页 |
| 2 | `src/components/views/StoryRunDetailView.tsx` | Run 日志搜索、级别筛选对齐 36px；增加 DEBUG 级别和结果数；分镜诊断改为贴右覆盖式检视区，窄屏不再挤压帧网格 | 历史 Run、帧、Worker、心跳仍仅代表保存时的快照；未增加任何状态写入 |
| 3 | `src/components/ActivityStream.tsx` | 展开逐帧审核后增加 Ant Design 审核结论筛选及 10 条/页真实记录分页，切换筛选自动回第一页；收起时复位筛选 | 仅展示本地加载的审核证据，不把未审核帧认定为通过 |
| 4 | `src/index.css`、`web-console/scripts` | 抽取共同工具栏和筛选区布局契约，保持现有主题和断点；新增 R20 三场景浏览器交互测试，并修复一项旧测试对已修改数据来源文案的过时断言 | 不改变真实作品内容、文件、阶段、图片审核或 Runtime |

## 启动与数据来源

本机入口：`http://127.0.0.1:3100/`；由 `scripts/launch-local-real-console.mjs` 启动本机状态文件只读服务（`127.0.0.1:19117`）与 Vite。检查 `/api/v1/runtime/statuses?limit=1&offset=0` 返回 `code=OK`、`total=20`、`state_source=local_workspace_episode_state_file`。该模式是磁盘证据投影，不是线上 Runtime、MySQL、可写权限或 Worker 探活。

**日志限制：** 当前本机只读 API 对 `/api/v1/events` 返回 `READ_ONLY_LOCAL_EVIDENCE`（HTTP 403）；页面应显示真实错误和空日志，不允许用演示事件伪造日志、声称实时连接。要支持日志全集/服务端分页，后续必须由授权事件 API 提供 `total/has_more/offset` 等契约。

## 验收

| 项目 | 验证 |
|---|---|
| TypeScript `npm run lint` | 通过 |
| Vite `npm run build -- --base=./` | 通过（保留原有大 chunk 警告） |
| `test:console` | 5/5 |
| `test:episodes` | 11 部作品历史详情逐字段基线一致 |
| `test:runs` | 11 部历史 Run 详情逐字段基线一致 |
| `test:bundles` | Episode 11/11、Run 11/11 延迟分包 |
| R19 浏览器回归 | 2/2 |
| R17 响应式浏览器回归 | 4/4 |
| R12 作品制作及 Run 深层浏览器回归 | 2/2 |
| 新增 R20 交互浏览器回归 | 3/3：1366px 审核筛选、1024px Run 日志筛选+分镜抽屉、1280px 审计日志筛选/错误提示；均检查无整页水平溢出 |
| 本机真实数据 | 接口 20 条本机文件状态，非实时执行 |
| `git diff --check` | 通过 |

R20 浏览器回归：`cd web-console && npm run test:r20`，默认读取 `3100`，截图在不跟踪的 `.storyos-tmp/ui-qa/r20/`。现有 `test-local-real-browser.mjs` 原先匹配了两处过时文案（横幅及生产阶段标题），按已在页面存在的真实来源描述进行修正；不弱化关于只读来源、未知执行状态和未知心跳的安全断言。

## 保留与排除

- 不覆盖 `reports/account-pattern-registry.json` 的并发任务修改。
- 不删除、不统一整理、不提交原有约 193 项未跟踪工作文件。
- 不改写 `episodes/`、媒体资源、审批记录、阶段状态或后端 API。
- 保留 R19 已有的项目快捷抽屉、已批准图片预览、分页、响应式入口。
- R20 只提交上表列出的前端文件、专项测试和本文档，代码提交信息采用中文。

## 后续迭代建议

日志高流量场景应优先增加服务端条件查询与可靠分页接口，然后升级前端；目前只对已加载 100 条使用前端分页是明确的限界设计，不应声称已实现全量搜索或服务端日志翻页。
