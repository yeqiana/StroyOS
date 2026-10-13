# StoryOS R14 · Web Console 产品化首轮四槽实施与验收

日期：2026-10-13
基线：fcb7a32e
主旨：优先提升创作者使用体验与真实数据来源可解释性；不增加集群、分布式 Writer、自动重试、生产写权限。
生产工作台不等于已开放真实生图，所有服务端生产写操作仍 403。

## A · 工作台数据来源对账

\`runtimeCatalogReconciliation.ts\` + \`HomeOverviewView.tsx\`：
- 单次从现有 read-only \`runtimeStatuses\` 中读取真实状态，保留静态已知剧集目录与浏览器草稿，增加可折叠「作品来源对账」。
- **仅在唯一业务编号与标题同时精确一致时**认定 Runtime ↔ 静态目录对应。拒绝名称相似、重命名猜测、重复编号、归档测试条目、路径形态不符的来源。
- 当前真实 11 部中与静态目录精确匹配的 **4/11**，其余不等于丢失：是快照目录/重命名/编号不一致或未建映射，需要后续以真实 Episode Identity 合同替代静态目录。
- 分页或请求异常显示「来源未完整核验」，不声称全量。浏览器本地草稿不算正式 Episode，不替用户提交 Runtime。
- 提供跳转生产监控核对的入口，不创造虚拟任务。

## B · 任务证据链现状清楚展示

\`recordedTraceCoverage.ts\` + \`RuntimeAuthorityPanel.tsx\`：
- 只对现有 MySQL Episode 身份、SELECT-only 授权验证通过的 Task、Production Attempt、Generation Attempt 样本展示统计。
- 明示三表是按作品分别查询的样本，**尚无可核验的 Task → Generation Attempt → Trace → Artifact 全链路关联**。绝不把行数、帧号、时间相近作为外键或“已完整定位”的假象。
- \`OUTCOME_UNKNOWN\` 仅提示人工处理，不主动生产或重试。
- 当前独立只读接口仍然不能读取 Event 列表、Agent Registry；没有恢复成完整技术管理后台。

## C · 20 帧快速定位

\`ActivityStream.tsx\`：
- 分镜与审核区上方提供 01–20 可访问的快速定位条，真实批准素材/批次帧可跳转，缺证据按钮禁用。
- WARN / FAIL 仅由记录过的 FrameReviewResult 着色；一键定位第一条**同时存在可检视帧证据**的待查帧。无可检视证据不强行跳转。
- 批准图片与当次制作帧进度仍分开计数；没有升级人工审核权限、没有提交审核或生成。
- 原有左右方向键、图像比对、批次/批准切换和 Reviewer inspector 不移除。

## D · 真实全菜单 Chrome 与回归验收

- 四个隔离分支独立提交：
  - A: 84ee1fc4
  - B: 9eda5690
  - C: 8b88b88b
  - D: 5e5fd06e
- 整合基线 fcb7a32e，顺序 cherry-pick，无文件冲突。
- TypeScript lint、Vite build PASS。
- Python 真正的 Driver/Provider/监控合同回归：**44 passed, 5 subtests passed**，不访问付费模型、不修改真实生产 MySQL/Redis。
- Node 精确身份与来源/Trace 强制保守断言：**11 个断言通过**。
- R14 \`test-r14-product-ui-browser.mjs\` 真实 Windows Chrome 1440x900、独立只读预览 \`3196/19926\`：工作台来源对账、故事制作 20 帧定位、作品素材库、真实监控 Task/Trace 来源提示、工作流、Agents、审计日志、系统设置 **8/8 页面通过**。
- Chrome 截图在隔离工作树 \`.storyos-tmp/ui-qa/r14/storyos-r14-{overview,creator,library,monitor,workflow,agents,logs,settings}-1440.png\`，测试页面真实本机 approved-media、11 部正式 Episode、写入接口仍 HTTP 403。
- 当前只做一轮 1440 宽度真实验收；1024/移动端需要进一步专门完整回归，不将旧 R28 14/14 误当作本轮多宽度测试。

## 关键剩余问题与下一步

- **核心 P0 尚未完成：** 将浏览器本地项目/故事草稿与正式 Runtime Episode/Project 从读写接口上建立唯一主键、可靠保存与迁移。R14 的对账只揭示问题，**尚未实现创建/编辑正式项目**。
- **技术链路尚待打通：** 可信 Task ID → Generation Attempt → Trace → Artifact 的精确外键及只读图形追踪，非仅显示行数。应先实证现有数据字段。
- **StoryOS 制作仍只读：** 受控生产任务派发、审核提交、版本变更、结算与发布权限均未开放，UI 不能误导为已完成。
- 继续优先统一读数据范围、真正的 20 帧审核决策和可追溯执行链。暂不扩充多租户、跨机 Worker/Redis 分布式高可用，不继续堆首页和监控卡片。
- 独立 worktree 中执行；主工作树现有脏文件未经任何覆盖。安全合入需保留备份、明确回退 tag、事后 SHA256 比对。
