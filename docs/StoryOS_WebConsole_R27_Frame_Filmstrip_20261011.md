# StoryOS Web Console R27 · 二轮四槽连续创作优化与验收（2026-10-11）

分支：`story-platform-v3-rever`
基线：R26 `3642b934`
性质：Web Console 只读创作检视 UI，不改变生产 Runtime、正式门禁、素材文件或接口权限。

## 设计目标

继续参考即梦、可灵的“连续素材浏览 + 当前片段直达”创作动线，并保留 StoryOS 的工业控制台规范：第一层聚焦真实图片和 Frame，深色实体表面、状态文字、窄分隔、右侧 Inspector，不使用假图或无实际作用的卡片。

## 四槽实施

### ① 20 帧快速定位：从反复翻页变为一次点击

- 分镜检视抽屉新增横向滚动的 `分镜快速定位` 轨道，**仅从真实当前批次/approved 素材的实际帧集合**构建编号，不凭空补齐。
- 有受控批准素材时显示对应真实缩略图；图片加载前保留编号底图，加载失败仅留下编号，禁止错误图片和空白黑格。
- 无真实图片时直接显示可识别的数字状态条，不生成假缩略图。
- 点击 Frame 16 等任意帧，右侧立即进入对应的真实图片、Prompt/审核证据；上一帧/下一帧和键盘切换时横向轨道自动将当前帧滚入中部区域。抽屉从 440px 增宽至 620px 时，借助 ResizeObserver 在实际宽度变化后重新定位，避免窄屏偶发错位。
- 当前帧使用主题 `--info` 细边框及 `aria-current` 指示，不依赖颜色单独表达状态。

### ② 审核直达：出现实际异常才允许快捷导航

- 只有当前作品 `frameReviews` 确有 WARN/FAIL 时，抽屉才显示 `下一待查`，数量来自原始审核记录去重后的真实帧编号。
- 跳转按帧号从当前帧向后查找、必要时回到首个待查帧，并选择该帧实际可用的 approved/批次来源。
- 当前真实工作区历史作品没有 WARN/FAIL 测试目标：**不注入虚假的异常状态**；真实 Chrome 对“不存在异常入口”做负向验证，跳转逻辑保留在界面代码中，后续有真实待查证据再专项验收。

### ③ 窄屏可用与真实图像来源

- 横向快捷轨道只在抽屉内部滚动；1024px 对照布局保持最大 100vw，无全局溢出。
- 固定 Frame 01 后，快速切到 Frame 16，继续和固定帧并排比较；当前批准图片、原始图片链接和审核记录均来源原有受控文件索引。
- 缩略图高度 48px、宽度 40px、紧凑 4px/8px 栅格；没有生成新图片、没有改动文件路径。

### ④ 真实浏览器回归与可靠截图

新增 `web-console/scripts/test-r27-filmstrip-browser.mjs`（`npm run test:r27`）六个 Chrome 场景：
1. 1440px · 批准图 Frame 1 直接跳 Frame 16，再跳 17，快速定位条同步
2. 1440px · 跳 Frame 20，下一帧不可继续
3. 1440px · 真实 Frame 01 固定对照后快速跳 Frame 16，两张图片均成功解码
4. 1024px · 同样的快速跳转与对照，无视口横向溢出
5. 1366px · 无真实图片的批次可快速跳 16，但不能固定对照
6. 1366px · 审核条目直接进入 Frame 详情，轨道同步；当前确无 WARN/FAIL 时不显示“下一待查”虚构入口

扩展已有 CDP 工具 `npm run capture:r26` 的泛化参数，新增 `npm run capture:r27`：在**同一次 Chrome 页面完成 20 帧跳转、两张真实图片均解码成功后**保存最终截图：
- `.storyos-tmp/ui-qa/r27/storyos-r27-cdp-compare-1440.png`
- `.storyos-tmp/ui-qa/r27/storyos-r27-cdp-compare-1024.png`

其它 R27 场景的截图均位于 `.storyos-tmp/ui-qa/r27/storyos-r27-*.png`，不提交图片二进制。

## 工程验证

- `npm run lint`、`npm run build -- --base=./`
- `npm run test:r27`：新交互 6/6
- `npm run capture:r27`：两个有真实图像的浏览器 CDP 页面截图 2/2
- `npm run test:r26`：继续保证上一轮上下帧切换 / 图片比对 / 审核联动
- `npm run test:r25`、`npm run test:r24`、`npm run test:r23`、`npm run test:r22`、`npm run test:responsive`：旧版布局/导航交互兼容
- `npm run test:media`：批准素材真图解码、未批准作品不串图
- `npm run test:episodes`、`npm run test:runs`、`npm run test:bundles`：冻结历史数据与懒加载合同
- `npm run test:local-real`：保留本机只读工作区状态来源，不能宣称在线 Worker 状态

## 安全与后续

未更改数据库、Redis、Provider Gateway、正式生图共享配额和 Runtime API；`reports/account-pattern-registry.json` 与所有其他任务的未跟踪文件保持原状。已批准素材只有受控 `/api/v1/local-media/images/<hash>` 地址进入浏览器。

R28 建议围绕“分镜详情中的真实 Prompt 文本阅读、字幕证据与审核问题位置”提高阅读效率；在没有正式可写接口前仍保持只读，不模拟生成按钮或假任务进度。
