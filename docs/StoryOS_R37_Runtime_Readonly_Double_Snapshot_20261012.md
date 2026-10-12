# StoryOS R37 · Runtime 只读证据链双读一致性与显式接线验收

日期：2026-10-12
分支：`story-platform-v3-rever`
基线：R36 `176530eb`
范围：R37 四槽非付费推进，真实 Chrome 视觉核验、隔离 Python / Node 测试、中文 Git 提交。

## 一、交付边界

**本轮是只读证据链的安全加固，不是正式 Runtime 或付费图像生产已上线。**

- 没有启动正式 Driver、Provider、生图、发布；没有读取任何未经授权的生产 MySQL / Redis。
- 当前 `http://127.0.0.1:3100/` 仍使用主工作区本机历史阶段证据，通过 GET 查询；`GET /api/v1/runtime/authority` 的五类在线 Runtime 来源均如实为 `UNAVAILABLE`，已核验 **0/5**。
- `production_authorization`、`can_start`、`can_retry`、`can_publish` 始终为 `false`；只读快照不构成容量 Permit 或 Generation Attempt 重试授权。
- StoryOS 永久生产契约不变：不同 Episode 可并行、相同 Episode 仅一名 Writer；同一 Git Common Directory 下所有图片入口共享 **5 张**在途上限，必须先拿容量 Permit 再预留 Attempt，UNKNOWN 不能自动重试；不能借本机 OS 锁声称跨主机安全。

## 二、四槽推进内容

### 槽 1：Worker Task/Redis 双读一致性

修改 `platform/operations/runtime_live_authority_readers.py`。

R36 原先通过一次 MySQL 唯一 RUNNING Task 身份读取、一次 Redis GET/PTTL 返回健康证据；如果期间 Task 被移交给新 Worker、Redis 心跳刷新或键过期，这种跨库瞬时观察可能发生 TOCTOU 竞争。

R37 依次执行：

1. 验证合法的唯一 Episode namespace、存储 UID 和唯一 RUNNING Task 的 `TASK_ID + OWNER_ID`；
2. 读取该 Task Owner 的 Redis `storyos:worker:{id}:heartbeat`，验证 worker_id、ONLINE、有效 UTC 心跳时间及正值 PTTL；
3. 第二次读取相同 Redis GET/PTTL，心跳内容变化或 TTL 过期即阻断；
4. 第二次校验 Episode namespace 与存储 UID，再读唯一 RUNNING Task，比对 `TASK_ID + OWNER_ID` 未变化才给出 **read-only heartbeat proof**。

SQL 仅 `SELECT`，Redis 仅 `GET / PTTL`；保持最大记录体积、最长 TTL、120s 心跳、时区校验规则。变化被视为证据不可用，不会重新派发 Provider 或尝试“纠正”数据库。即便双读稳定也**不证明 Task 独立执行 Lease 有效**。

新增针对 Worker 中途改派、Episode UID 变更、Redis 心跳被替换或 TTL 在两次读取间到期的隔离回归。

### 槽 2：Writer 双向核验与实际 fencing 缺口

继续使用 R36 注入的两条独立只读读取器：
`driver_status(episode_ref)` 和 `owner_fence(episode_ref)`。

R37 在原有 RUNNING/ALIVE/PID/beacon、唯一 Owner、fencing_epoch、租约有效期验证之后，**重新读取 fenced owner 与 Driver**：
- 任一 Episode 身份、Owner 数量、PID、fencing epoch、lease 到期时间、Owner 生效状态发生变化，阻断；
- 第二次 Driver PID 或 liveness、beacon 已变化为不可信、fence 观察过期、租约第二次读取时已到期，阻断；
- 不能用 pid 文件、旧 JSON、Redis 无 TTL 锁、`EpisodeLockManager` 替代可信的 CAS/fencing Source of Truth。

当前仓库 `platform/state/episode_lock_manager.py` 的现有 `SET NX` fallback 及无 owner-token 比对的 `release()` **不具备严格 fencing 语义**，也没有可证明的独立 Writer Lease Authority。R37 **没有**把它接作已验证 Writer 数据源，后续跨进程 / 跨主机正式生产前必须专项修复并验收。二次读取仍非原子事务，只用于诊断。

### 槽 3：显式只读接线工厂 + 测试

新增 `platform/operations/runtime_authority_composition.py` 的
`build_runtime_authority_readonly(status_reader, approve_external_reads=False, ...)`。

- 不提供 `approve_external_reads=True` 时不允许带入任何 MySQL/Redis/Driver/容量来源；默认仅生成 `AUTHORITY_NOT_CONFIGURED`；
- MySQL 必须搭配唯一 Episode repository；Redis Worker 还必须具备 Task 的参数化 `SELECT` 列表读取；Writer 必须同时注入 Driver 与独立 fenced owner；capacity 必须注入只读 snapshot callback；
- 缺少 `query_one`、`query_all`、`get`、`pttl` 等必要入口或来源不是可调用对象，在构建时拒绝，而不是启动运行后产生错误状态；
- 只从**调用方已经授权且有限权限**的 Reader 装配。该工厂不建立连接、不读取 `production.env`、不获取实际生产凭据，不修改 Runtime Controller 的默认 opt-in 行为；
- Local 本机历史状态源即便误配置外部 Reader 也仍只返回 5 类 `LOCAL_STAGE_ONLY`，不会触发任何外部数据库读取；
- 通过 Fake MySQL、Fake Redis、Fake fenced owner / Driver 证明接线五域 read-only 结果可被解析，但它们的测试结果**不能声称在线生产数据已接通**。

新增 `tests/platform/test_runtime_authority_composition.py`，覆盖未授权禁止读取、缺依赖 fail-closed、完整隔离装配、来源脱敏、没有 provider action。

### 槽 4：Web Console 采样有效期与真实 Chrome

修改现有 Ant Design Drawer 组件 `RuntimeRecoveryInsight.tsx`、`runtimeAuthorityPresentation.ts`：
- 保留 R36 `TTL / fencing` 与 **已核验 0/5** 的含义；添加紧凑的 `R37 · 双读一致性` 信息及“采样不是原子事务”的说明；
- 本地 inspector 每 15 秒仅重算前端证据时效，**不发送新的网络请求、不发 POST、不重置表格筛选/Drawer**；
- 凡验证时间戳超过 120 秒、来自未来时间、没有时区或伪造来源，原先的 verified 结果自动失效；
- 双读只代表读取阶段未见身份变化，绝不自动授权开始、重试、发布或图片 Permit；
- 不重排故事制作/作品详情已冻结页面，不创建新手工 UI 组件。

浏览器 `web-console/scripts/test-r37-authority-browser.mjs` 实际点击工作流 / 生产监控并验证 Ant Design Drawer、GET-only、当前 Episode 身份、0/5、R37说明与只读保护，在 1440px 和 1024px 共生成四张截图：

`.storyos-tmp/ui-qa/r37/storyos-r37-workflow-1440.png`
`.storyos-tmp/ui-qa/r37/storyos-r37-workflow-1024.png`
`.storyos-tmp/ui-qa/r37/storyos-r37-monitor-1440.png`
`.storyos-tmp/ui-qa/r37/storyos-r37-monitor-1024.png`

## 三、最终实测记录

| 验收项目 | 结果 |
|---|---|
| Platform API、显式只读装配、MySQL/Redis/Driver 重采样安全测试 | **160/160 passed** |
| Attempt/Driver/共享五图容量/异常恢复系统测试 | **93/93 passed** |
| R37 前端 120s 到期、时区、伪造来源、local 不升级权威 | **3/3 passed** |
| R36 前端已有 TTL / fencing 合约 | **4/4 passed** |
| 工作流 / 生产监控 R37 Chrome × 1440/1024 | **4/4 passed** |
| 七个一级菜单 R28 Chrome × 1440/1024 | **14/14 passed** |
| 故事制作、作品详情 R25 Chrome | **6/6 passed** |
| `npm run lint` / `npm run build -- --base=./` | **通过** |
| `git diff --cached --check` / 提交范围 | 提交前单独检查 |

重要：平台回归以原本隔离连接、Fake driver、Fake redis、真实浏览器**本地只读**为依据。真实授权生产 Worker/Writer/Lease 尚未配置。生产 API 的实际 MySQL/Redis read-only 权限及独立 Writer Fencing 源仍是上线阻塞。

## 四、下一轮 R38 阻塞与建议

1. **P0：Writer Source of Truth**。先设计并验收可 CAS 续租、严格 Owner token 比对、单调 fencing epoch、租约到期回收，以及 compare-and-delete 的唯一 Writer Lease 存储；现有 `EpisodeLockManager.release()` 无 Owner 核验，不得据此证明跨主机安全。
2. **P0：受授权的只读部署**。由部署方授予真正的 SELECT-only MySQL 和 Redis GET/PTTL 账户、受控 Driver / fenced owner read API，显式在生产 Bootstrap 注入，再做实际 Episode/Task/Worker/Writer 谱系验收。
3. **P0：一致性再确认**。双读不能跨 MySQL/Redis 原子确认，任何准备执行的 Worker 必须在真正 Provider Gateway 取得有效 fencing / Permit 后才有动作权限。
4. **P1：Canary**。真实非付费 Canary 仍需正式读端接线与权限验收之后另行安排；本轮未实施付费生产 Canary。

## 五、版本与资产保护

本次仅定向提交 R37 Python 只读组合工厂、Worker / Writer 读端双读补丁、针对应的隔离测试、现有 Console 的时效与信息标签、新浏览器脚本、npm 脚本与本 MD。不触碰 Provider Gateway、Episode 生产数据、已有图片/字幕/审核、R25 冻结布局，或其他任务的 `reports/account-learning-index.json`、`reports/account-pattern-registry.json` 与既有 untracked 文件。
