# StoryOS Web Console R26 · 四槽分镜导航、实图对照与审核联动验收

日期：2026-10-11
分支：`story-platform-v3-rever`
基线：R25 `40ef5e01`
主界面：`http://127.0.0.1:3100/`（本机只读证据模式）

## 设计目标

继续吸收即梦、可灵创作平台中**连续看图、就地比较、减少页面往返**的操作理念，不引入营销卡片、不伪造素材和状态，也不改变 StoryOS 正式 Runtime/审核/分账或生产网关。遵循既有 `DESIGN.md` 中的中性深灰、窄间距、真实数据、右侧按需 Inspector 与主创作区优先原则。

### 四槽实现

**槽1 · 连续分镜检视**

- `ActivityStream` 的右侧 Drawer 增加明确的“上一帧/下一帧”按钮和 `当前位置 / 总帧数`。
- 打开 Drawer 时，左/右方向键可依当前作品的批次或 approved 帧序列前后浏览；首尾按钮禁用，保留原图入口。输入/组合框不被方向键劫持。
- 按批准帧/当前批次分别计算帧序列，**不通过臆测缺失帧填补记录**；跨作品继续由 `App.tsx` 原有 key 隔离，避免带入上一部的对照状态。

**槽2 · 真实批准图片双帧对照**

- Drawer 可点击“固定对照”将有可信图像证据的当前帧锁定为参考，然后切换到下一帧，左右并排查看两张真实图。
- 固定后在主画布顶部显示可关闭的对照工具条；按用户操作清除、切换素材类别、切换作品时不强留过期对照。
- 宽屏 Inspector 从 440px 按需增加至最大 620px，窄屏最大 100vw；图片使用 `object-contain`，不伪造拉伸或新的生成结果。
- 图像 URL 保持来自原有受控 approved catalog；无可信图片时“固定对照”禁用、双帧比对不可显示。

**槽3 · 逐帧审核直达**

- 审核列表 Frame 名称升级为可操作的只读定位入口，点击即打开对应 Frame 的 Inspector。
- Inspector 按已有 `frameReviews` 中相同 `frameIndex` 展示 PASS/WARN/FAIL 和审核备注；不是重新审核、评分或写入。
- 主画布可见当前选中帧与固定帧标记；筛选、分页、已批准/批次模式仍保留，切换数据类别主动清理旧对照。

**槽4 · 真实 Chrome 验收和截图**

新增 `web-console/scripts/test-r26-creator-browser.mjs` 及 `npm run test:r26`，完整浏览器交互：
1. 1440px：真实 approved Frame 1 → 下一帧 → 键盘右 → 键盘左 → 上一帧，首帧不可再前进
2. 1440px：固定真实 Frame 1 与 Frame 2 并排，并验证两个不同受控图片源
3. 1024px：窄屏对照操作、两张实际图片解码成功及无视口横向溢出
4. 1366px：审核列表直接跳转并显示原始审核结论
5. 1366px：无可验证图片时禁用固定对照、不渲染假图，仍可翻页状态帧
6. 1280px：结束对照恢复单图，同时移除画布固定工具条

浏览器截图新增 `npm run capture:r26`（`scripts/capture-r26-compare-cdp.mjs`）。该工具使用仅绑定本机的 Chrome DevTools 协议，**在同一个通过验证的浏览器页面确认两张图片完整解码后截图**，避免另起 Chrome 时抓到图片半加载或抽屉尚未打开的中间状态。CDP 实测 **2/2 通过**。

真实截图保留在本地忽略目录（不提交图片或有隐私风险的生成素材）：

| 页面 | 本机截图路径 |
|---|---|
| 双帧对照 1440px（同页验证抓拍） | `.storyos-tmp/ui-qa/r26/storyos-r26-cdp-compare-1440.png` |
| 双帧对照 1024px（同页验证抓拍） | `.storyos-tmp/ui-qa/r26/storyos-r26-cdp-compare-1024.png` |
| 连续导航 1440px | `.storyos-tmp/ui-qa/r26/storyos-r26-creator-sequence-1440.png` |
| 审核直达 1366px | `.storyos-tmp/ui-qa/r26/storyos-r26-creator-review-jump-1366.png` |
| 无真实图片保护 1366px | `.storyos-tmp/ui-qa/r26/storyos-r26-creator-no-fake-1366.png` |
| 清除对照 1280px | `.storyos-tmp/ui-qa/r26/storyos-r26-creator-compare-clear-1280.png` |

## 测试、回归和真实来源

- `npm run lint`（tsc --noEmit）、`npm run build -- --base=./`
- `npm run test:r26`，真实 Chrome 6 场景，所有对照图在页面实际解码后判 PASS。
- `npm run capture:r26`，同一浏览器真实双图截图 2 场景。
- `npm run test:r25`、`npm run test:r24`、`npm run test:r23`、`npm run test:r22`、`npm run test:responsive`、`npm run test:console`，保留历史界面兼容性
- `npm run test:media`，保证已批准 20 张图可解码、无批准素材不会跨作品串图
- `npm run test:episodes`、`npm run test:runs` 与 `npm run test:bundles`，不改变历史作品分包及证据
- `npm run test:local-real`：本地只读磁盘状态 20 条，未把它假扮在线 Worker 心跳

## 不在本次范围内

不允许前端直接修改正式生产阶段、不提交图像生成请求、不更改 approved media 目录、MySQL/Redis 状态、不修改 `reports/account-pattern-registry.json` 或其他并行任务资产。未来 R27 可围绕分镜画布的画幅自适应与键盘快捷检视进一步优化，但仍遵守受控资源读写。

最终提交只包含 R26 指定代码、测试脚本、package 脚本和本验收文档，Commit message 必须中文。
