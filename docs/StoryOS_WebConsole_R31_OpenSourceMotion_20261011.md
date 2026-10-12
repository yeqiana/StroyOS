# StoryOS Web Console R31 · 开源交互动效增强与可访问性验收

日期：2026-10-11
分支：story-platform-v3-rever
基线：R30 提交 db47ab28

## 一、本轮目标与范围

用户要求：**增加一些动效让操作更加流畅，继续使用成熟开源组件，不自己设计交互动画库。**

本轮严格只改 StoryOS 一级「工作台」的局部交互表现，保留 R30 结构、所有业务数据/API/路由不变，冻结「故事制作」「作品详情」、Run 详情与其他一级菜单。

## 二、开源实现与动效参数

| 交互 | 技术来源 | 实际效果 | 边界 |
|---|---|---|---|
| 按钮点击、范围/视图分段切换 | **Ant Design 6.6.5** 自带交互与 wave/segmented 效果 | 原生按钮反馈、分段选择滑块 | 无自制按钮/Tab/控制组件 |
| 「列表 ↔ 画廊」内容切换 | **@rc-component/motion 1.3.3**（Ant Design 已使用的开源底层组件，显式锁定直接依赖） | 有明确用户动作时，160ms 透明度+纵向 6px 进入过渡 | 不触发无意义的初次页面加载动画；不重建作品业务状态；React keyed 控制确保每次切换真的触发生命周期 |
| 真实批准作品封面 hover | CSS 仅作开源组件样式层 | 120ms 边框变化，卡片上移 2px，封面 180ms 缩放 1.8% | 只作用于 HomeOverviewView 的真实作品卡，不给表格添加跳动 |
| 快捷操作区 hover/focus | Ant Design Button + 页面样式 Token | 120ms 背景和图标反馈 | 点击操作保留原 onNewStory/onSelectEpisode/onNavigate |
| 无图紧凑行 | 原生可点击行 + 页面 Token | 120ms 背景反馈 | 没有放大空卡或加载假素材 |
| 操作系统“减少动态效果” | CSS media query：prefers-reduced-motion: reduce | 过渡、图片缩放及位移均禁用，视图仍同步切换 | 不依赖动画才显示内容，保证可访问性和低性能机器可用 |

使用既有配色 Token 和 StoryOS DESIGN.md Motion 规范：hover 120ms ease-out、enter 160ms cubic-bezier(.2,.8,.2,1)。没有加入 Framer Motion、GSAP、动态粒子、渐变背景、轮询闪烁或新的第三方图片来源。

## 三、修改文件

- web-console/src/components/views/HomeOverviewView.tsx：引入 rc-motion CSSMotion 包裹列表/画廊，按实际视图 key 挂载，第一次首页渲染不动；添加局部样式作用类。
- web-console/src/index.css：仅在 #storyos-home-overview 范围内添加交互反馈与 rc-motion appear CSS 过渡；支持 prefers-reduced-motion: reduce。
- web-console/package.json 与 package-lock.json：将已存在于 antd 依赖树中的 @rc-component/motion@1.3.3 显式固定为直接依赖，不安装另一个大型动效库。
- web-console/scripts/test-r31-motion-browser.mjs：新真实 Chrome E2E 验证效果与可访问性。
- 本验收文档。

**未修改：** App.tsx、ActivityStream、SeriesLibraryView、StoryRunDetailView、Runtime API、发布逻辑、正式生图与持久化状态。

## 四、实测视觉与交互验收

npm run test:r31：实际 Windows Chrome DevTools 协议在 1440px、1024px 两种屏宽各验收：

1. R30 创作入口、3 张已批准图片真实解码、列表/画廊、搜索、导航、回来继续制作及无全页面横向溢出均保持正常。
2. Chrome 原生鼠标移动到真实作品卡：:hover=true，计算到 transform matrix(..., -2)；内部封面 transform matrix(1.018, ...)，确定不是只有 CSS 文件而没有实际生效。
3. 点击原生 Ant Design「画廊」模式，Chrome 真正捕获 @rc-component/motion 的 appear-active 生命周期，transitionDuration=0.16s，切换后业务数据无丢失。
4. CDP 模拟系统 prefers-reduced-motion: reduce，检查媒体查询为 true，图片/卡片 transitionDuration=0s，切换的画廊内容 opacity=1，mode pane transitionDuration=0s；没有闪退、遮挡或丢数据。
5. 真实截图在未跟踪目录 .storyos-tmp/ui-qa/r31，包含首页、hover、reduce 以及从列表切换到画廊的 5 张连续帧。连续帧可生成简短 GIF 给用户验收。

验证数据为本机只读真实素材：三部拥有批准图片的作品、共 60 张素材；技术阶段记录仍来自本机工作区磁盘快照，并非在线 Runtime。

## 五、兼容回归记录

- npm run test:r31：1440/1024 正常动效 + reduced motion 两组全部通过。
- npm run test:r30：R30 三种屏宽的已有工作台业务链路通过。
- npm run test:r28：七个一级菜单 × 1440/1024，14/14 通过。
- npm run test:r25：作品库/详情/故事制作六场景，6/6 通过。
- npm run test:r19：原首页阶段明细展开分页与项目菜单，2/2 通过。
- npm run test:media：受控批准图片真实性、无批准素材不串图，4/4 通过。
- npm run test:responsive：四个历史屏宽布局，4/4 通过。
- npm run test:episodes：11 部作品内容等价。
- npm run test:runs：11/11 历史 Run 等价。
- npm run test:bundles：历史作品与 Run 独立分包。
- npm run test:local-real：20 条工作区只读磁盘状态、未知 Worker 心跳保留。
- npm run lint / npm run build -- --base=./：TypeScript 与 Vite 编译通过。
- git diff --check、逐文件定向提交与后置工作区检查。

## 六、工程备注

本机 node_modules 在本轮工作过程中一度缺失 TypeScript/Vite 及 @ant-design/icons 运行文件。按锁文件恢复依赖后，以官方 npm 图标包补齐本地缺失的 849 个 JavaScript 资源，生产构建恢复正常。这个**本地临时依赖修复不作为产品代码提交**，提交只包含 R31 动效和测试等必要文件。

其他任务的 reports/account-pattern-registry.json 修改和未跟踪业务文档均必须保留，不纳入 R31 Git commit。
