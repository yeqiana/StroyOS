# StoryOS R15 · 正式 Runtime 作品目录跨页面统一（只读第一轮）

日期：2026-10-13
基线：851e6b64，集成开始前主分支额外吸收了 M00 安全修复
候选：refactor/storyos-r15-integrated-20261013

## 产品目标与范围

R14 的 11 部真实 Runtime Episode 中仅 4 部可凭业务编号及标题双重唯一匹配历史静态目录；其余无法可靠关联。R15 不是以名称猜测伪造分镜详情，更不是开放生产写权限，而是让**工作台、作品与项目直接展示同一份正式 Runtime 只读目录**，并对已匹配的旧分镜保留快速入口。

## 四槽交付

A. \`canonicalCatalogProjection.ts\`、\`canonicalRuntimeCatalog.ts\`、\`CanonicalRuntimeDirectory.tsx\`：
- 真正通过 \`GET /api/v1/runtime/statuses?limit=100&offset=0\` 获取同一源的 11 部正式作品；10 秒内共享缓存和请求去重，刷新时显式重新读取。
- 只收 \`state_source=local_workspace_episode_state_file\`、合法 \`LOCAL_...\` 身份、非空 business_episode_id/title、无重复引用的记录；数据源分页、不完整、错误时仅报告部分数据，不假称全量。
- 只在唯一**业务编号+标题**与历史 Episode 同时精确一致时开启「检视历史分镜」；本地浏览器草稿不参加正式作品身份映射。不存在历史精确匹配时，显示「查看真实监控」，保留独立作品身份，绝不替用户创建草稿或拼接虚构审核结果。

B. \`HomeOverviewView.tsx\`：
- 工作台顶部仍是「今天想创作什么？」及三项快捷操作；紧随其后放正式 Runtime 目录，默认紧凑展示 5 项，允许展开全部 11 部；旧素材画廊仍使用批准目录，已知项目空间与历史统计明确标注是工作区快照而非 Runtime 全量。

C. \`SeriesLibraryView.tsx\`、\`App.tsx\`：
- 作品库以三列紧凑形式展示同一 Runtime 目录 **11/11**，下面保留已批准真实封面与旧作品详情。
- 未匹配的 Runtime 作品携带**原始安全 Episode ref**，直接进入对应作品的生产监控详情；不走 title-only join，不丢入一般监控首页。
- 匹配作品仍打开旧详情的 lazy loader，保持 20 帧审核、视觉锁等历史证据，不把 Runtime 阶段强行覆盖到旧详情。

D. \`test-r15-canonical-source-contract.mjs\` + \`test-r15-canonical-catalog-browser.mjs\`：
- 强制边界：完整、部分返回、分页、错源测试 fixture、恶意 ref、重复正式 ref、重复历史编号+标题、浏览器本地草稿、变更标题/编号均不能假匹配。
- Windows 实机 Chrome 1440px，隔离只读服务 \`3197/19927\`，8/8 一级菜单通过；Home 和 Library 都显示真实 11 部，未匹配作品能跳到*对应* Runtime 监控详情；真正 approved 图、StoryMaker 20 帧导航、Agents、工作流、审核日志不回退。
- 前端 TypeScript lint、Vite build PASS；只读监控及 Writer/Provider safety Python **44 passed，5 subtests passed**。
- 现场原服务 \`3100/19117\` 仍仅属于真实生产数据的只读投影，HTTP POST 应继续 403；此次不生成图片，不发生产任务、不修改 MySQL/Redis 数据。

## Chrome 证据

在 R15 集成 worktree：
\`.storyos-tmp/ui-qa/r15/storyos-r15-{overview,creator,library,monitor,workflow,agents,logs,settings}-1440.png\`。

来源显示的是实时读取目录，图片只来自原批准媒体目录，不拿生成示意图替代真实结果。图片预览和浏览器草稿绝不代表真实生产执行或已对模型付款。

## 尚未完成的 P0

1. **尚未实现正式 Episode/Project 服务端持久化**：浏览器本地项目和故事草稿仍以 localStorage 保存，清理浏览器缓存可能丢失草稿。R15 是读取路径统一第一轮，不是写路径迁移。
2. **部分历史分镜无法精确关联**：只说明没有经过双重身份核验，不能声称真实 Runtime 作品不存在、没有图片或生产失败。建议后续建立稳定业务 Episode 主键和正式历史迁移映射（需人工审核），不要凭文件目录或相似名称猜测。
3. **真正完整 Event/Trace/Task/Generation Attempt → Artifact 关联及人工审核写入**尚未打通，需继续按现有单机 Writer + 5 图容量 + Generation Attempt 边界设计受控操作，不能在监控页直接提供无权的操作按钮。
4. 本轮是 1440px 完整 Chrome 现场验收；1024/移动设备需单独跑，不把曾经的旧截图视为本轮结果。

## 安全交付

四槽位先在独立 worktree 各自提交，再将最新主分支上其他 M00 改动保留后 Cherry-pick；安全 FF 合入主分支前备份原有脏文件 SHA256，建立 rollback tag。仅重启原本已启动的本地只读 Web Console+API，绝不重启真正的生产 Driver。
