# StoryOS 单机精简 · 第三轮四槽功能闭环验收

日期：2026-10-12
单机基线：`5be08972`
集成分支：`refactor/storyos-single-node-integrated-20261012`
实施原则：不新增服务，不触碰生产 MySQL/Redis，不调用付费生图，不自动发布；维护原有 Git 主分支未提交修改。

## 四槽交付与缺陷

### A · 本地草稿 → 制作页上下文恢复

- `web-console/src/App.tsx`：原状态每次加载默认 `REAL_EPISODES[0]`，尽管草稿 `storyos_local_story_drafts_v1` 已保存，刷新后丢失当前正在制作的本地故事选中上下文。
- 现在只在有效 `ep-home-*` / `ep-proj-*`、并且确实属于已验证浏览器本地草稿的情况下恢复上次选中身份；浏览器禁用 localStorage 时自动采用原有默认，不会恢复历史作品不可信的详情快照。
- `web-console/scripts/test-r32-local-draft-browser.mjs` 真正用 Chrome CDP 验证新建、存储、刷新、回到故事制作以及选中身份与编辑器可见。初版 CDP selector 嵌套转义出现脚本解析错误，已定向修复后 **1/1 通过**。

### B · 队列/Run 异常展示不伪造实时状态

- `web-console/src/components/views/StoryRunDetailView.tsx`：旧异常面板把 `HEALTHY`、`系统自愈中 (1 项生效中)`、`NETWORK_ERROR`、`Attempt 2/3 (17s 后自动触发)`、立即手动触发写死。这与页面已明确的“历史快照，只读”互相矛盾。
- 已替换为来源于 `run.frames` 保存值的 BLOCKED / RETRYING 计数、帧编码、Attempt 和最后异常；显式说明历史快照不代表在线状态、没有经过授权验证的倒计时；“查看记录”只打开帧只读 Inspector，不启动重试或消耗 Attempt。
- 修复 TypeScript 类型检查发现的非法 `FAILED` FrameStatus 引用；只使用现有 `BLOCKED`，不扩大业务枚举。

### C · 失败/待审核入口的操作语义

- `web-console/src/components/StoryNextAction.tsx` 按本地草稿、阻塞、待确认显示“查看制作流程”“查看阻塞阶段”“查看待确认阶段”。仅导航到现有 Workflow 只读视图；悬停说明不执行重试、不更改审核结果。
- 没有添加所谓“立即恢复”或“强制通过”功能，无授权 Runtime API 时继续 fail-closed。

### D · 真正的浏览器与截图验收

- 新增 `web-console/scripts/test-single-node-r3-browser.mjs`：启动独立 localhost 静态 HTTP Server、调用 R32 真实 Chrome CDP 测试，再关闭服务进程，使用新建浏览器 Profile。
- Chrome 1440px：**1/1** 新建草稿、刷新保留、再次进入故事制作；截图在隔离集成工作树 `.storyos-tmp/ui-qa/r32/storyos-r32-draft-1440.png`，确认为 PNG，**109,494 bytes**。
- Vite production build `npm run build` **PASS**；TypeScript `npm run lint` **PASS**；离线五主菜单 `npm run test:console` **5/5**；独立安全规则 `npm run test:r33:safety` **14/14**，另 Episode 详情身份对照 **5/5**；作品详情基线 `test:episodes` **11/11**；Run 详情基线 `test:runs` **11/11**；可访问性 `test:accessibility` **3/3**；单机后端核心保护选集 pytest **33 passed**。

## 仍保留的验证边界

- 截图来自离线 Chrome 静态页面，不可证明真正在线 Runtime 连接。真实生产 Agent/Provider/发布功能仍未执行。
- 现有 `test:workbench-run` 依赖单独在 localhost 运行的只读 Runtime API，在本轮无该服务情况下**不计入已通过**。
- 本轮没有执行生产 MySQL/Redis 写入、付费图片生成、正式发布或交互式 Windows Task Scheduler Carrier 验收。
- 不把演示快照、历史模拟的“正在恢复”当作可验证的实时 Worker/Attempt 状态。
- 本次只改 3 个现有 UI 文件和 1 个既有浏览器测试脚本，另新增 1 个测试启动器；没有新架构组件。

## 提交记录

四个独立 Worktree：
- A `32b98c45` + CDP 修复 `a893c1b3`
- B `1967d5f0` + 类型校正 `03c5ff91`
- C `1be85ead`
- D `e5370a16`

单机集成：`848dc4d6`、`ebafe4a6`、`b3877bb3`、`c6ad7a4f`；校正及本文件以最后提交为准。

## 下一轮只做真实单机业务问题

下一轮如需进一步实际修复，应集中验证已授权只读本地 API 下的故事与 Run 关联、失败时真实错误原因提示；在未开放安全执行 API 的情况下，不应做假重试按钮，也不应扩展分布式组件。
