# StoryOS Web Console R29 · 工作台首页 Creator-first 二次重构（2026-10-11）

基线：`story-platform-v3-rever`，R28 提交 `ffdbe858`。
改造入口：一级菜单 **「工作台」/ HomeOverviewView**。
用户明确冻结：一级菜单 **「故事制作」**、已有 **「作品详情」** 预览抽屉以及其他一级页面。

## 重新设计的原因

R28 虽然把作品表格扩大到全宽，但首屏仍然按“统计数字 → 异常提醒与快捷入口 → 大表格”的运维 Dashboard 顺序排列。作品内容被压在二级区域；首屏图片尺寸太小，缺乏连续创作感。

R29 改为产品内工作台布局：**真实作品焦点 > 最近有素材的其他作品 > 工作区作品清单 > 折叠式阶段证据**。结构参考创作工具的“继续上次项目 + 素材浏览”，不改 StoryOS 的暗色中性 Token、4px 网格和扁平专业控制台视觉规则。

## 新布局

1. **顶部低占用数字带**：仅展示工作区作品数量、含已批准图片作品、未发布作品和项目空间，明确“当前工作区、非实时执行状态”；不再摆三张 KPI 卡片。
2. **焦点创作区**：优先选出「未发布且有受控批准素材」中按 `updatedAt` 最近的一部；没有批准素材时回退到最近的未发布作品；作品只有真实受控文件索引匹配才显示封面，不合成占位封面。
3. **真实批准分镜微胶片条**：若焦点作品至少 12 张受控批准图片，展示该批中实际存在的 Frame 05/10/15/20；数据较少时只展示实际存在的索引帧。点击缩略图进入该作品进行检视，不冒充能直接跳到某帧。
4. **工作区进度与批准素材分账**：清晰显示“工作区 0 / 20 帧”和“20 张已批准”。两者属于不同来源，不因批准图片存在擅自覆盖工作区进度或推断生产完成。
5. **右侧近期真实素材区**：最多三个其他具有受控批准图片的作品缩略图，优先让图片与点击入口占首屏；明确审核阻塞只来自已载入的 frameReview/preflight 数据，无实据不标红。
6. **下方全宽作品表格**：按工作区更新日期排序，Ant Design `Segmented` 支持「全部 / 未发布 / 有批准图片」；`Input.Search` 搜标题、编号、类型；10 条分页，可直接点击作品名、行、进入按钮进入已有创作页。
7. **技术证据从创作视线移走**：平台阶段记录仍保留原 `details` 折叠、10 条分页、刷新、异常说明和工作流直达；默认合起，未将本机磁盘快照当作实时 Runtime。

## 代码与测试范围

| 文件 | 修改 |
|---|---|
| `web-console/src/components/views/HomeOverviewView.tsx` | 首页组件重排、真实封面/胶片条、筛选/排序、作品直达、阶段证据保留 |
| `web-console/scripts/test-r29-home-browser.mjs` | 新 Chrome CDP 端到端实测：图片必须解码、筛选和作品直达后返回、截图须滚动归零 |
| `web-console/scripts/test-r25-creator-browser.mjs` | 修正旧测试在批准媒体目录异步加载期间持有失效卡片 DOM 导致的竞态；不改故事制作/作品详情功能 |
| `web-console/package.json` | `npm run test:r29` 命令 |

**未修改**：`web-console/src/App.tsx`、`web-console/src/components/ActivityStream.tsx`、`web-console/src/components/views/SeriesLibraryView.tsx`、`StoryRunDetailView.tsx`、生产 Runtime、API、数据库和正式业务权限。

## 截图与浏览器验收

本机真实 Chrome CDP 逐一访问 `http://127.0.0.1:3100/`，完成：
- **1440px、1366px、1024px：3/3**。首页真实焦点封面和其他已批准图片成功解码；能筛到 3 部已批准作品、恢复全部列表；按焦点「继续制作」打开同名真实作品，再回到首页；文档无全局横向溢出。
- 本机截图：
  - `.storyos-tmp/ui-qa/r29/storyos-r29-overview-1440.png`
  - `.storyos-tmp/ui-qa/r29/storyos-r29-overview-1366.png`
  - `.storyos-tmp/ui-qa/r29/storyos-r29-overview-1024.png`
- 截图只作为 UI 复核材料，不提交图片二进制；严格使用实际可解码的批准图片。

回归：
- `npm run lint`：TypeScript 通过。
- `npm run build -- --base=./`：Vite 生产构建通过。
- `npm run test:r29`：Creator 首页专项 **3/3**。
- `npm run test:r28`：全部七个一级菜单，1440 / 1024 **14/14**。
- `npm run test:r19`：首页折叠阶段记录与分页、收窄侧栏项目入口 **2/2**。
- `npm run test:r25`：作品画廊、预览、创作画布与历史作品列表 **6/6**；修复旧测试的异步卡片引用时序问题。
- `npm run test:media`：批准媒体只展示其真实图片、无批准图片作品不串图 **4/4**。
- `npm run test:episodes`：11 部历史作品内容等价。
- `npm run test:runs`：11 条历史 Run 内容等价。
- `npm run test:local-real`：本机 20 条真实状态文件，只读与未知心跳保持原样。
- `npm run test:responsive`：检查 1024 / 1280 的主页面，防全局溢出。
- `git diff --check` 与 Git 单独提交本轮文件，其他任务的 `reports/account-pattern-registry.json` 和未跟踪业务文档不纳入。

## 明确限制

本机 Console 仍是 **本机磁盘工作区证据**，不是在线 Worker、并发队列、正式生产进度或 MySQL 权威状态。已批准图片与工作区已完成帧来源不同：即使某作品有 20 张已批准图片，工作区记录为 0/20 时本轮仍原样显示，不能当成 bug 自动覆写数据。

若后续希望点击小胶片条直接定位特定 Frame，需要另行定义与已有「故事制作」已完成交互之间的参数协定；本轮不动用户已冻结的创作页面。
