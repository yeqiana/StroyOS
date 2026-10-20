# StoryOS Web Console

StoryOS 的 React + TypeScript 前端生产控制台。默认入口是高密度 Production Monitor，并通过唯一的 Platform API 边界读取运行态、执行链路与生产证据。

## 当前数据边界

- Web Console 只通过 `VITE_PLATFORM_API_URL` / Vite 同源代理访问 StoryOS Platform API，不直接调用 Gemini 或其他模型 SDK。
- 前端不得直接推进 Episode stage；正式阶段以 StoryOS canonical state transition 为准。
- `src/data/storyosRealData.ts` 是历史工作区证据索引，不是实时 Runtime 权威数据；本地真实文件只读模式从主工作区 `episodes/**/meta/episode-state.json` 读取当前磁盘记录，未读取到的心跳/Worker/执行动作必须保持未知。生成器不复制生产像素资产到 `web-console/public`。
- WebCodex 是 Workspace Provider，不是 Episode Authority。

## 本地运行

要求 Node.js 22+，统一使用 npm。仓库只维护 `package-lock.json`，不要生成第二套 Bun/Yarn/PNPM 锁文件。

```bash
npm ci
npm run dev
```

默认开发服务监听 `0.0.0.0:3100`。

如果 Platform API 不与前端同源，可设置：

```bash
VITE_PLATFORM_API_URL=http://127.0.0.1:<platform-port>
```

未设置 `VITE_PLATFORM_API_URL` 时，Vite dev/preview 代理默认转发到 `http://127.0.0.1:8080`。

### 使用主工作区的真实作品状态（安全只读）

在 `web-console` 下执行：

```bash
npm run dev:local:real
```

然后打开 `http://127.0.0.1:3100/`。它只在本机启动 Vite 和一个 **127.0.0.1:19117** 的只读 Python 文件 API，从当前 Git 主工作区的 `episodes` 读取现存作品阶段记录。只允许 `GET /healthz`、`GET /api/v1/runtime/statuses` 和 `GET /api/v1/runtime/status`；不连接 MySQL/Redis、不启动图片模型。主工作区位置默认由 Git common-dir 推导，可用 `STORYOS_LOCAL_DATA_ROOT` 显式覆盖。

该模式的数据源为 `local_workspace_episode_state_file`：是真实磁盘记录，**不是 MySQL 权威实时调度态**。页面有来源提示；需要真正的 MySQL Runtime 联调时应单独审计配置和只读权限。`npm run dev:local:fixture` 仍可用于隔离内存数据测试。

## 校验

```bash
npm run lint
npm run build
```

`npm run lint` 当前执行 TypeScript `tsc --noEmit` 校验。

## 主要入口

当前 React 版本是单页控制台，浏览器入口统一为 `/`，不再维护旧 Vue Router 的独立 URL。侧栏在同一页面内切换 Production Monitor、生产流水线、剧集/素材、Agent、数据看板、异常中心、系统设置与运行日志等工作区视图。

后端能力仍以 Platform API 的真实可用契约为准；前端不为尚未提供的 controller/API 保留伪造入口。

## Docker

构建镜像使用 `npm ci` 锁定依赖树：

```bash
docker build -f docker/Dockerfile -t story-os-web-console .
```

### 实时监控：MySQL 权威只读目录

本地真实控制台在启动时读取用户专属的
`%LOCALAPPDATA%\\StoryOS\\monitoring\\mysql-monitor-ro.json`（仅供本机 Python API）；
需要独立 SELECT-only MySQL 账号，并由 API 自行验证 `SHOW GRANTS`、
`START TRANSACTION READ ONLY`，不复用正式生产凭据。

- 配置项：`STORYOS_LOCAL_MONITOR_MYSQL=1`、
  `STORYOS_MONITOR_MYSQL_RO_USER`、
  `STORYOS_MONITOR_MYSQL_RO_PASSWORD`、
  `STORYOS_MONITOR_MYSQL_RO_DB=STORY_OS_RUNTIME`、
  `STORYOS_MONITOR_MYSQL_RO_PORT=13307`（也支持本机旧端口 `3307`）
- 账号仅需 `TB_EPISODE`、`TB_EPISODE_STATE`、`TB_TASK`、
  `TB_PRODUCTION_ATTEMPT`、`TB_GENERATION_ATTEMPT` 五张表的 SELECT。
- 接通后从 MySQL ACTIVE Episode 目录发现新故事，`CURRENT_STATE` 为阶段权威；
  目录文件只补充 Driver 观察与最近执行节点，不作为在线执行或成功出图的证明。
- 未配置只读数据库时，会显示已有磁盘快照，并从本机正式 Episode 目录补充
  无状态文件的新故事，阶段显示 `UNKNOWN`，不会猜测数据库阶段。
- Redis 旧 TaskState 不包含可靠 Episode 身份，不能把它的任务计数当作本剧集进度。
- 只在 `127.0.0.1` 提供 GET，前端经同源代理访问。不得提交本地监控凭据。
