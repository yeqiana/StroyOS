# StoryOS 单机精简第五轮 · 四槽真实只读 HTTP 与浏览器验收

日期：2026-10-13
干净基线：`6641c4ed`
集成分支：`refactor/storyos-single-node-integrated-20261012`

## 范围

单机 + 单实例 MySQL/Redis（本轮不访问）+ 已有本机 Writer/OS 五图锁。此次没有新的服务体系、生产写库、付费 Provider 或正式发布。使用独立四个 Git Worktree 串行安全集成。

**和先前离线验收不同**：本轮使用已存在的 `scripts/storyos_local_readonly_api.py`，仅通过 `127.0.0.1` 读取原主工作区的 `episodes/**/meta/episode-state.json`，且不连接 MySQL/Redis/Worker；Chrome 访问真实本机状态文件投影。阶段文件不得冒充在线任务心跳、重试授权或真实运行结果。

## 四槽完成

| 槽 | 代码变化 | 依据 |
|---|---|---|
| A · 关联身份 | 历史 Run 只有 `storyName`、并无受信任 `Episode ID`；从历史 Run 进入制作时，仅唯一匹配标题才自动打开作品；同名跳到作品管理让用户按编号选，无匹配不盲猜 | `storyRunEpisodeMatch.ts`，身份测试 6/6 |
| B · 只读监控 | 下一页接口失败时保留已读记录，但不再维持 `ok` 完整状态；改为 `partial` 并显示已读范围不完整 | `ProductionMonitorView.tsx`，已有只读分页覆盖率测试 |
| C · 恢复/详情隔离 | `current_action\|\|next_step` 的 next_step 改为只从当前已核实 Episode 的 `visibleDetail` 读取，杜绝在切换详情瞬间泄漏旧 Episode 的建议步骤 | `RuntimeAuthorityPanel.tsx`，7/7，新旧恢复安全 14/14，身份 5/5 |
| D · 真实本地 HTTP/Chrome | 新增可重复使用的 `test-single-node-r5-real-readonly.mjs`，在隔离端口启动现有单机状态文件只读 HTTP 和 Vite，验证首页、监控、详情来源及未知心跳，验证写入禁用，退出自动终止两服务 | 真实状态文件 20 条、HTTP 200、POST 403、Chrome PASS，真实截图 507,317 字节 |

## 真实独立联动证据

- 主工作区检出 20 份作品状态文件，HTTP 投影读取 **20** 条合法记录，具有唯一非冲突 Episode Ref。
- `GET /api/v1/runtime/statuses` 返回 `state_source=local_workspace_episode_state_file`；`GET /api/v1/runtime/status` 返回 `execution_status=UNKNOWN`、`heartbeat.health=unknown`。**不能据此声称 Worker 在线或图片生成成功。**
- `POST /api/v1/runtime/statuses` 返回 **403**；不存在的 `GET /api/v1/events` 返回 **403**；正式写入/Agent/发布未开启。
- Chromium 真正进入工作台与生产监控，验证真实磁盘来源提示、读取真实作品标题以及无假在线状态。
- 浏览器画面存放在 `.storyos-tmp/ui-qa/single-node-r5-real-readonly-1440.png`（集成工作区，**507317 bytes**）；没有重设计页面，本轮截图用于记录真实数据接入状态。
- 服务全部为临时 `127.0.0.1` 随机端口，HTTP/Vite 子进程均在测试结束时清理；既有 Redis/MySQL/Provider 未触碰。

## 测试与提交

四槽原始提交：A `a00705de`、B `2787c3b1`、C `96701945`、D `a0bf1d06`。

单机集成提交：A `c503ea16`、B `6dc9b030`、C `8df3bda0`、D `dd8f7dde`。

集成 TypeScript `npm run lint` **PASS**；Vite `npm run build` **PASS**；身份 6/6；监控分页身份 6/6；新增安全后备字段检查 7/7、恢复合同 14/14、当前 Episode 详情匹配 5/5、R37 失效凭据 3/3；真实只读 HTTP/Chrome **PASS**。

单机跨阶段 Python 集成回归：**241 passed、12 skipped、5 subtests passed，0 failed（17.54 秒）**。跳过项为未打开 TEST_ONLY MySQL 数据库准入的旧 SQL 实写专项，不能计作通过。本轮没有新建测试 MySQL 容器。

## 本轮最终 Git 集成

四槽依序 cherry-pick 成功，R38 分布式实验分支和脏主分支均不参与此次发布候选。验收文档提交在本次四槽代码提交之后。

## 阻塞与生产边界

1. 本次是真实**磁盘文件状态**而不是已连接生产 Writer、真实 MySQL Attempt/任务队列；不能声称生产运行全链路。
2. 状态文件缺少对在线调度的证明，所以 `UNKNOWN` 是正确状态，不可借页面写入口触发恢复。
3. 历史 Run 只有标题，没有受信任的 Episode ID。B/C 只避免错误关联与误读证据；彻底一一关联需要业务数据契约未来提供真正 canonical ID，**不以模糊匹配代替身份**。
4. 同名作品匹配拒绝、下一页故障提示有源代码/专项与 TypeScript 验证，尚未用后端故意制造全链路同名/101+页失败完成逐个 Chrome 场景；不应把 HTTP/Chrome 首页通过外推到所有边界。
5. 正式生产系统、付费图像 Provider、发布、交互式 Windows Task Scheduler Carrier 未执行，且本轮未更新原工作分支。

## 后续单机方向

保持现有一台电脑部署。把真正的 Episode 业务 ID 在历史 Run 的数据合同时补齐；有经授权的真实只读调度 API 后验收 Worker 心跳与 Attempt 展示，不新增 Redis Cluster、远端 Consumer、分布式 Worker 或跨主机容量。
