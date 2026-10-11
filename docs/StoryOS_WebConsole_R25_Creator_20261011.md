# StoryOS Web Console R25 · 创作中心优先四槽改造（2026-10-11）

分支：`story-platform-v3-rever`；基线：R24 `f077eb2e`。模式：本地真实作品状态与本机已批准图片，只读；**不是生产在线 Runtime**。

## 方向（吸收即梦 / 可灵的交互理念，不复制品牌风格）

- 从长期堆叠的“生产阶段说明 → KPI → 批次 → 审核 → 素材”，转为**最短创作动线：作品库 → 作品预览 → 分镜/素材画布 → Frame 检视**。
- 页面仍遵守 StoryOS `DESIGN.md`：深灰实体表面、最少卡片、可扫描的编号/状态、440px 右侧 Ant Design Drawer、4px spacing。生产监控和权威工作流不改动。
- 优先展示真实素材，**不能把未验证缩略图或历史通过状态假装成新一轮生成成功**；缺图片时只显示有依据的 Frame 状态矩阵。

## 四槽实施

### ① 故事制作首页 · 创作画布优先（`App.tsx`）

- 保留 `StoryNextAction` 重点提醒，避免视觉优先导致门禁异常被藏掉。
- 将冗长的 `StatusFlowBanner` 与 `ProductionMetricsPanel` 包进可展开的“生产阶段与制作指标”，默认收起；已有阶段/指标随时可访问，不改变原始快照。
- `ActivityStream` 进入统一 Ant Design `AntdSurface` 主题上下文，Frame Drawer 和 Segmented 与全站深色/浅色切换一致。真实 Chrome 验证新 Drawer 不再错误显示白底。
- 作品切换为 ActivityStream 设定 `key={activeEpisode.id}`，使当前帧选择不会误带入下一部作品。

### ② 中央分镜与视觉素材（`ActivityStream.tsx`）

- 延续 R24 的**批次 / 审核**非对称双栏，但批次主区进一步拆为“创作参数（只读）/ 分镜画布”，参考可灵的控制与结果同屏。
- Ant Design Segmented 切换 `当前批次` 和 `已批准素材`；只有真实 approved 素材存在时才给出批准素材选项，默认优先显示批准图片。
- 本机批准图片来自受控 `/api/v1/local-media/catalog`；Frame 卡片真实图片采用原始已批准 URL，不上传/编辑/重绘。
- Frame 点击打开 440px 详情 Drawer：来源、状态、编号、已有 Prompt；只有已验证图片才显示实际照片和原图链接，未验证则说明缺证据。
- 本地状态记录而无批准图片的作品显示 20 帧紧凑矩阵；审核 WARN/FAIL 筛选、分页等旧操作仍在右侧。

### ③ 作品库 + 导航（`SeriesLibraryView.tsx`、`Sidebar.tsx`、`localApprovedMedia.ts`）

- 作品与项目支持**封面画廊 / 列表**两种可切换模式；画廊按真实已批准素材优先展示，避免首屏全部是未验证封面的空卡。列表保留原表格排序、筛选、分页、查看操作。
- 画廊卡片提供实图封面、业务编号、阶段、**工作区帧进度**和独立的**已批准图片数量**；标注不同数据源的区别，避免把 0/20 与批准 20 张混为一谈。
- 点击卡片打开 440px 作品详情 Drawer：安全封面、工作区阶段与帧数、批准素材计数、故事简介；“进入故事制作”继续使用原有导航及按需加载完整历史详情，不提交生产指令。
- 左侧项目树默认按需展开；大屏右侧工作区证据栏默认关闭，但原入口仍可打开，给画布更大空间。
- 已确认本机素材目录中包含《误入桃花源》《婚礼前夜》《仲夏夜惊魂｜停电夜蜕壳》三个作品各 20 张 approved 图片。本轮仅针对历史目录里 `code===title` 的非业务编号，允许**标题在本机 approved 目录中精确唯一**时安全匹配；遇到真实业务 ID 不匹配或标题重名立即拒绝，绝不在不同作品间串图。

### ④ Chrome 真实截图与兼容性验收

新增 `npm run test:r25`（`scripts/test-r25-creator-browser.mjs`），验证：
1. 1366px 作品库画廊与真实媒体来源；
2. 1280px 真实封面作品详情 Drawer；
3. 1440px 完整“作品预览 → 进入创作 → 已批准 Frame → 深色 Drawer”链路；
4. 1366px 缺真实图片时的安全状态矩阵与帧检视；
5. 1024px 窄屏画布、侧边导航与审核堆叠；
6. 1280px 原列表模式与项目树展开功能；
并分别验证视口无水平溢出。

### 截图（本机文件，不提交证据目录）

| 真实视图 | 本机路径 |
|---|---|
| 全部作品封面画廊 | `.storyos-tmp/ui-qa/r25/storyos-r25-library-gallery.png` |
| 真实素材作品预览 | `.storyos-tmp/ui-qa/r25/storyos-r25-library-preview.png` |
| 20 张真实图片 + 分镜 Drawer | `.storyos-tmp/ui-qa/r25/storyos-r25-creator-approved-frame.png` |
| 没有图片时的证据矩阵 | `.storyos-tmp/ui-qa/r25/storyos-r25-creator-empty-evidence.png` |
| 1024px 创作响应式 | `.storyos-tmp/ui-qa/r25/storyos-r25-creator-compact.png` |
| 传统列表视图 | `.storyos-tmp/ui-qa/r25/storyos-r25-library-list-compat.png` |

## 工程验证（最终以控制台测试结果为准）

- `npm run lint`、`npm run build -- --base=./`
- `npm run test:r25`：6 个 Chrome 真实页面场景。
- `npm run test:r24`、`npm run test:r23`、`npm run test:r22`、`npm run test:r20`、`npm run test:r19`、`npm run test:responsive`：既有布局和导航回归。
- `npm run test:episodes`（11 个冻结作品）、`npm run test:runs`（11 个冻结历史 Run）、`npm run test:local-real`、`npm run test:monitor-pages`、`npm run test:workflow`、`npm run test:console`、`npm run test:bundles`。
- 已更新历史 R16 本机批准素材浏览器用例的端口与界面入口，旧用途仍是**图片真实性/负向防泄漏**验收。

## 安全边界与下一轮建议

- 这是创作素材**只读检视**，不是可写 Prompt 编辑器或受控生图入口。没有批准素材时不展示假的生成图片。
- 所有画面没有推断或覆盖新生产结果；审核/返修/发布仍需受控 Runtime。
- 额外修复历史 Run 中已批准图片异步到达时的默认布局：图片获得可信证据后自动从状态列表切换到矩阵；用户明确手动选择过展示方式后不自动覆盖。历史真实批准素材 Chrome R16 回归 **4/4 通过**（包括未批准作品不能串图）。
- 本轮不触碰 `reports/account-pattern-registry.json`、其他任务的未跟踪文件、MySQL、Redis、Gateway 及正式生图配额。
- R26 可继续专注于可验证素材的多选比较 / 分镜详情预览（仅在真实资产存在时），以及移动窄屏的工具栏整理，避免重新堆叠营销卡片。
