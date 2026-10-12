# StoryOS Web Console R32 · 四槽全站功能真实验收与修复

日期：2026-10-12
分支：story-platform-v3-rever
基线：R31 55be79c6

## 一、验收边界

四槽并发滚动检查：①创作、②生产、③管理安全、④交互/质量。分别验证真实 Chrome 页面、本机磁盘只读 API 与离线夹具，不能把只读磁盘状态或隔离测试当成正式 Worker 生产完成。

本地受控 API 仅绑定 127.0.0.1；工作区状态来自 episodes 状态文件。实际可读到 20 条阶段记录和 3 部作品的 60 张批准图片。未启动正式生产 Runtime、MySQL、Redis 或收费生图 Gateway。

## 二、缺陷闭环

### P0 · 本机真实控制台启动过早超时 — 已修复

症状：日志中 Python 只读 API、Vite 都提示就绪，但本机启动器在第一次 API 阶段查询尚未响应时退出，产生 Local endpoint not ready。

隔离端口排查：Python 服务直连、Vite 同源代理均返回 code=OK / total=20 / source=local_workspace_episode_state_file，证明代理和磁盘来源本身有效。原总等候 25s、单请求 1.3s 在机器繁忙和首次目录扫描期间过短。

修复：总等待扩展至 60s、单请求 5s，记录最后 HTTP/超时信息；依然要求 code、stage source、total 均真实通过才能打印 LOCAL_STORYOS_READY，不降级为只凭 Vite 首页 HTTP 200 就认为 API 在线。

修改：web-console/scripts/launch-local-real-console.mjs。修复后真实服务重新打印 LOCAL_STORYOS_READY，阶段和媒体查询可用。

### P1 · 新建草稿不显示在最近更新作品首位 — 已修复

症状：创建本地草稿时把 updatedAt 写成中文“刚刚”，首页按 Date.parse 排序会当作 0，导致新故事被压到底部，违背“最近创作”。

修复：只在 buildNewEpisode 创建时写真实 ISO 时间，保留所有历史作品原始字段和 StoryOS 分镜画布布局。

新增 test:r32：在隔离 Chrome profile 中点击新建故事、确认本地草稿持久化、返回工作台核对第一行、真实刷新 Chrome 后确认同一草稿仍在首行。两项验证通过，不写入用户自己的 Chrome 个人资料。

修改：web-console/src/App.tsx；web-console/scripts/test-r32-local-draft-browser.mjs；web-console/package.json。

### P1 · 生产监控分页回归误报 — 已修复

R28 页面已经使用“匹配 100 / 已读 100 / 101”，旧测试却等待“已读取 100 / 101”。修复仅调整过期文案断言，不绕过加载状态、请求次数与分页验证。

修复后 test:monitor-pages 证明：100 → 101 条服务端记录，连续双击只发一次第二页请求，历史快照不被覆盖。

修改：web-console/scripts/test-monitor-pagination-browser.mjs。

### P1 · 本机只读权限边界增加真实自动验证 — 已交付

新增 test:r32:boundary，真实查询本机只读 API：
- 源信息是 local_workspace_episode_state_file，且有真实阶段记录；
- 批准媒体采用受控 token URL，返回真实图片 MIME，禁止缓存；
- Agents 和 Events 未开放接口返回 403，不能冒充线上数据；
- POST 请求写入阶段被拒绝；
- 外站 Origin 读取本机媒体目录被拒绝。

修改：web-console/scripts/test-r32-readonly-boundary.mjs；web-console/package.json。结果 5/5。

### P2 · 首次截屏显示暂无批准图 — 已查明，非数据丢失

页面初次加载媒体 catalog 是异步的，太早拍照可能看到临时无图状态。重新通过本机 API 直连和浏览器代理验证均为 3 部/60 张；R25 和素材专项在图片成功解码后验收通过。无需伪造封面、不允许从其他故事串图片。

## 三、四槽完成的测试矩阵

| 槽位 | 检查 | 结论 |
|---|---|---|
| 创作 | test:console 离线五页面 | 5/5 |
| 创作 | test:r25 作品预览/故事制作/无图证据/窄屏 | 6/6 |
| 创作 | test:r32 新草稿排序与刷新恢复 | 通过 |
| 创作 | test:media 已批准真图与防串图 | 4/4 |
| 生产 | test:monitor 重叠读/过期回调/幂等锁 | 五类通过 |
| 生产 | test:monitor-pages 权威阶段 100→101 | 通过，仅一次翻页 |
| 生产 | test:workflow 工作流与离线降级 | 2/2 |
| 生产 | test:runtime-coverage 阶段覆盖率边界 | 五类通过 |
| 平台 | test:api 严格信封/超时/离线 | 7/7 |
| 平台 | test:readonly-probe 本机只读探测 | 4/4 |
| 平台 | test:r32:boundary 阶段/图像/接口权限 | 5/5 |
| 体验 | test:r28 七个一级菜单 × 两种屏宽 | 14/14 |
| 体验 | test:accessibility 标题/按钮/可见导航 | 3/3 |
| 体验 | test:r31 动效和系统减少动态效果 | 2/2 |
| 基线 | test:episodes / test:runs | 各 11/11 |
| 基线 | test:local-real 本机真实来源、未知心跳 | 20 条 |
| 基线 | test:bundles 作品与 Run 懒加载 | 通过 |
| 基线 | npm run lint / npm run build -- --base=./ | TypeScript 和构建通过 |
| 基线 | test:responsive | 原有四种布局通过 |

R32 Chrome 截图：.storyos-tmp/ui-qa/r32/storyos-r32-draft-1440.png（新草稿）；storyos-r32-{library,monitor,workflow,agents,logs,settings}-1440.png（六类一级页面）；storyos-r32-{monitor,workflow}-1024.png（窄屏）。后八张为本轮重新运行 R28 浏览器验收后按原样复制归档，不是模拟页面。

## 四、阻塞与后续

- P0/R33 前置：完整 Agent Registry、审计 Event、正式生产 Runtime 写接口不属于本机只读环境，本轮不能证明正式 Writer、队列、Worker、发布与真实退款/重试的端到端行为。需要独立授权的生产或受控 Canary 环境。
- P1/R33–R34：真实多 Episode 生图并发共享硬上限、门禁、发布和异常恢复需遵守既有 Gateway 与执行契约，不能为测试绕过容量或授权。
- P2：海量数据容量与更加复杂的键盘导航可以在有真实数据的环境下扩充，不应由 20 条本机文件外推线上性能。

## 五、源码保护与提交

只定向提交：启动器、App 新草稿时间戳、监控分页旧测试、新建草稿与只读边界两个新增测试、package scripts、本验收文档。保留故事制作/作品详情既有 UI，其他一级菜单布局及动效、照片、生产 Gateway 和数据库均未修改。

报告前校验 git diff --check，提交时保护其他任务的 reports/account-pattern-registry.json、Git 之外未跟踪文件与并行 worktree。
