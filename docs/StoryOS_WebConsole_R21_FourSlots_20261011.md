# StoryOS Web Console R21 · 四槽滚动优化验收（2026-10-11）

## 交付范围

1. 生产监控：筛选搜索、只看异常、重置统一 Ant Design Input/Checkbox/Button；过滤工具栏复用 os-console-filterbar。旧版历史 Run/在线 Runtime 证据边界不变。
2. 工作流：阶段详情改为右侧 440px Ant Design Drawer；元数据改为紧凑的键值分割行，不再挤占主表格宽度。
3. Run 分镜：缺少可验证图片时由 96px 最低高度压缩为 72px，序号、无原图、状态保留；小屏增加 3/5/7/10 自适应列数。严禁使用假素材。
4. 交互验收：修正 R20 分镜矩阵回归选择器，让测试检查网格行为而不是固定依赖 grid-cols-2；Chrome 分镜与其他布局截图已验证。

## 验证

- npm run lint：通过。
- npm run build -- --base=./：通过。
- npm run test:console：5/5。
- npm run test:workflow：2/2。
- npm run test:r20：3/3（真实浏览器截图）。
- npm run test:r19：未通过：collapsed-projects missing，原有导航交互断言需独立核实；R21 尚不能宣称全量旧版回归通过。

## 页面截图（项目本地，只读证据）

- .storyos-tmp/ui-qa/r20/storyos-run-detail-inspector.png（本轮重新生成，1024px）
- .storyos-tmp/ui-qa/r20/storyos-workbench-reviews.png（1366px）
- .storyos-tmp/ui-qa/r20/storyos-audit-logs.png（1280px）

## 已知边界

本地 3100 页面及 19117 API 来自只读工作区状态文件，不代表生产在线调度；审计事件 API 在该模式下不可用。不会修改其他任务的 report 和 untracked 数据。
