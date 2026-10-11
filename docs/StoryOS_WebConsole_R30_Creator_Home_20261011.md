# StoryOS Web Console R30 · 工作台创作入口与素材管理重构

日期：2026-10-11
分支：story-platform-v3-rever
基线：R29 168305be

## 目标与边界

本轮只改一级「工作台」首页，吸收即梦的创作入口优先和可灵的真实素材展示动线。不复制品牌、不增加没有授权能力的提示词输入框，也不改变 StoryOS 正式执行流程。

严格冻结「故事制作」「作品详情抽屉」和 Run 详情，以及其他一级页面。后端 Runtime、数据库、Redis、批准素材目录、正式运行状态完全不改。工作区 Frame 进度与批准媒体来自不同来源，不互相覆盖。

## R29 → R30 布局变化

| 位置 | 旧版 R29 | 新版 R30 |
|---|---|---|
| 顶部 | 标题 + 概况 + 单一新建按钮 | “今天想创作什么？” + 新建故事、继续制作、查看素材三项真实操作 |
| 视觉主体 | 一部焦点作品封面 + 右侧小型近期列表 | 按实际批准素材作品数铺满的横向大图画廊；3 部作品在 1440px 和 1024px 均同排 |
| 作品管理 | 默认只有高密度表格 | 复用 Ant Design 的列表/画廊切换，保留搜索、全部/未发布/有批准图筛选与分页 |
| 管理画廊 | 无 | 有批准素材的作品显示真实图片；缺真实批准图的作品只显示紧凑列表，不造假图或巨大空卡 |
| 证据来源 | 只读阶段记录默认折叠 | 完整保留，不把本机磁盘证据混同在线 Worker 运行态 |

## 实施范围

- web-console/src/components/views/HomeOverviewView.tsx：唯一业务视图变更。使用原有批准素材查询，只显示来自已验证素材目录的图片 URL。
- web-console/scripts/test-r30-home-browser.mjs：Chrome 真实浏览器验收，三种屏宽 × 首页、管理列表、管理画廊截图。完整验证真实图片解码、创作入口、搜索、两种模式、全部/批准筛选、返回首页及无横向溢出。
- web-console/scripts/test-r29-home-browser.mjs：调整旧版测试对已废弃的“焦点封面”组件的断言，保留旧版关于图片真实性、搜索和进入创作的行为要求。
- web-console/package.json：新增 npm run test:r30。

## 可验证数据与安全边界

- 本机只读 approved catalog 包含三部作品、共 60 张已批准素材；未批准作品不展示不属于它的图片。
- 每张封面链接来自原有受控 /api/v1/local-media/images/ 安全目录 URL。无图片时使用真实文字状态，而非合成缩略图。
- 继续制作和查看素材只调用既有导航；新建故事继续使用既有入口；没有任何新的生图、审核或发布请求。
- 生产阶段技术证据保留原始分页/刷新和来源说明，默认折叠。
- 其他任务的脏文件、未跟踪业务文档、reports/account-pattern-registry.json 不纳入此轮提交。

## Chrome 浏览器验收

三种分辨率：1440、1366、1024px。每组至少检查：
1. 三个真实创作入口存在且可交互。
2. 三张已批准作品图片地址正确且在 Chrome 中解码成功，页面没有横向滚动。
3. 作品管理列表/画廊切换正常，筛到三部含批准图片的作品，再恢复全部；搜索真实作品名称有效。
4. 查看素材进入作品库；继续制作进入同一真实作品的已存在故事制作界面，返回首页正常。
5. 本机运行证据默认折叠，保持其只读身份。

真实截图（本机忽略目录，不提交图片二进制）：
- .storyos-tmp/ui-qa/r30/storyos-r30-overview-1440.png
- .storyos-tmp/ui-qa/r30/storyos-r30-overview-1366.png
- .storyos-tmp/ui-qa/r30/storyos-r30-overview-1024.png
- .storyos-tmp/ui-qa/r30/storyos-r30-management-list-1440.png
- .storyos-tmp/ui-qa/r30/storyos-r30-management-gallery-1440.png

## 旧功能与工程验收

- npm run lint，npm run build -- --base=./
- npm run test:r30：三宽度实际 Chrome 路线与首页三态截图。
- npm run test:r28：7 个一级菜单、2 种宽度，共 14 个场景。
- npm run test:r29：上轮已有真实图片、筛选、创作入口行为。
- npm run test:r25：故事制作与作品详情冻结回归。
- npm run test:r19：工作台旧生产阶段展开与分页。
- npm run test:media：真实批准图片与防串图。
- npm run test:episodes / test:runs：冻结作品和历史 Run 合同。
- npm run test:responsive：原有窄屏业务页。
- git diff --check，提交后核查相关文件干净、并行任务资产未被触碰。

**注意**：这仍然是本地工作区的只读创作入口，不代表正式生产在线执行。