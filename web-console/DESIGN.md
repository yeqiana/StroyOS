# StoryOS Design Language & Interface Contract (DESIGN.md)

本文件是 StoryOS 视觉设计语言、界面拓扑与去 AI 化规范的唯一持久化契约。
无论由任何模型、Agent 或工程师执行前端迭代，**必须严格遵守本契约，严禁自行臆造风格或引入 AI Slop 模式**。

---

## 1. Product Mode (产品模式与定位)

StoryOS Web Console 属于：
- **Product / Workspace**
- **Data / Dashboard**
- **Operations Console (Dense Operations Console / Operations Workbench)**

**绝对不是**：
- Marketing Website
- Landing Page
- Creative Showcase
- Cyberpunk / AI Neon Dashboard

### UI 优先级
1. **Scanability** (扫描效率，一屏秒级识别当前流水线状态与阻断)
2. **Operational clarity** (操作确定性，行为危险级分明，无歧义反馈)
3. **Information hierarchy** (视觉主次分明，主表/工作区为绝对核心)
4. **State recognition** (状态语义化，状态文字与指示点强绑定)
5. **Density** (高信息密度，符合工业控制台视线节奏)
6. **Consistency** (组件间距、尺寸、圆角一致性)
7. **Decoration** (极低装饰度，严禁无业务意义的视觉填充)

---

## 2. Visual DNA (视觉基因)

- **Dark neutral background** (深灰暗调中性表面，无泛暖灰污浊感)
- **Compact operational density** (紧凑且符合 4px 栅格的操作密度)
- **Thin separators** (1px 极细微弱边框与分割线，替代浮华卡片包装)
- **Flat surfaces** (纯平实体表面，杜绝半透明玻璃拟态与弥散光)
- **Strong typography hierarchy** (鲜明的字号与行高梯次，数字等宽化)
- **Semantic status color only** (状态色彩纯语义化，仅作信号，不铺大色块)
- **Minimal radius** (3px ~ 8px 紧凑圆角，禁止任何药丸胶囊大圆角)
- **Almost no decorative gradient** (严禁无业务意义的紫蓝渐变与流光)
- **Table / Data Grid first** (数据表与矩阵优先，杜绝泛滥的 Card 堆叠)
- **Inspector / Drawer first** (右侧抽屉渐进式披露排障细节，杜绝弹窗轰炸)

---

## 3. Color Tokens (色彩系统与语义契约)

项目色彩映射到以下统一 Design Token 体系，严禁在不同组件中私自发明冲突颜色：

### 3.1 Surfaces & Backgrounds
```css
--bg-app:        #0A0B0D; /* 底层应用背景：极深中性青黑 */
--bg-workspace:  #171717; /* 工作区背景：表头、侧栏与次级面板底色 */
--bg-surface:    #1C1E21; /* 主要表面底色：主数据网格、状态条、容器卡片 */
--bg-elevated:   #25282C; /* 浮动/检视底色：Inspector Drawer、浮层、二级控件 */
--bg-hover:      #292D32; /* 悬停交互底色：数据行与按钮 hover */
--bg-selected:   #343940; /* 选中行指示底色 */
```

### 3.2 Borders & Dividers
```css
--border-subtle: #30343A; /* 默认极细分割线与普通边框 */
--border-normal: #41474F; /* 控件边框、激活面板边框 */
--border-strong: #56606A; /* 焦点高亮边框、强调区分线 */
```

### 3.3 Typography Contrast (文字对比度阶梯)
```css
--text-primary:   #F4F6F8; /* 主要文本：标题、当前任务名、核心指标数值 (高对比) */
--text-secondary: #BEC5CC; /* 次要文本：字段标签、阶段名称、辅助说明 */
--text-tertiary:  #969FA8; /* 第三级文本：时间戳、次级计数、单位标识 */
--text-disabled:  #737C86; /* 占位与禁用：技术占位符 `-`、无数据状态 */
```

### 3.4 Semantic Status Tokens (语义状态契约)
```css
--success: #3FB950; /* RUNNING / HEALTHY / COMPLETED 信号点 */
--waiting: #C9A227; /* QUEUED / WAITING 等待槽位调度 */
--retry:   #D28B26; /* RETRYING 自动退避重试 */
--danger:  #E05252; /* BLOCKED (需人工) / FAILED (致命阻断) */
--info:    #72A6F7; /* FOCUS / ACTIVE / 调度链路高亮 */
```
**主题取舍**：深色参考可灵近黑工作区与即梦 #171717 侧栏；浅色使用 #FAFAFA 画布、#F1F2F4 侧栏和白色内容区。主创作按钮采用主文字色反相，焦点与运行信息仍用蓝色，成功仍用绿色。Ant Design 与 CSS Token 一致。

**关键约束**：
- 绿色不得作为 StoryOS 通用品牌色，绿色仅服务于健康与顺利完结；
- 状态颜色只做信号指示（6px dot、文本、2px 高亮条），严禁大面积彩色背景铺色。

---

## 4. Radius (圆角系统)

```css
--radius-xs: 3px; /* 微标签 (Tag)、状态点容器 */
--radius-sm: 4px; /* 操作按钮 (Button)、输入框 (Input)、下拉选单 */
--radius-md: 6px; /* 主数据表面容器 (Panel, Container)、分镜缩略图 */
--radius-lg: 8px; /* 极少使用，最大外层主控卡片约束 */
```
**强制限制**：
- 严禁使用 12px、16px、20px、24px 及其以上大圆角；
- 严禁任何 Pill 胶囊型大圆角药丸；
- Inspector Drawer 默认 **0 radius** (直角贴边，无接缝)。

---

## 5. Spacing (4px Base Grid 间距规范)

统一采用 4px 基础网格：`4px`, `8px`, `12px`, `16px`, `20px`, `24px`, `32px`, `40px`。
- **组件内部间距**：`8px` / `12px`
- **组件/控件之间**：`16px`
- **Section 区块间距**：`24px`
- **Major Section 主区域**：`32px`

**强制限制**：严禁 Agent 随意手写 `13px`, `17px`, `21px`, `27px` 等无体系杂乱 spacing。

---

## 6. Typography (字体与排版阶梯)

### 字体栈 (Font Stack)
- **UI 界面字体**：`Inter, "SF Pro Text", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif`
- **Runtime / ID / Trace / 数值字体**：`"JetBrains Mono", SFMono-Regular, Consolas, monospace`

### 排版阶梯与行高
| 层级 | 字号 / 行高 | 字重 | 用途 |
| :--- | :--- | :--- | :--- |
| **Page Title** | 20px / 28px | 600 | 页面主控标题 |
| **Run Title** | 18px / 26px | 600 | 当前正在执行的故事任务名称 |
| **Section Title** | 14px / 20px | 600 | 区块分组标题、抽屉分类头 |
| **Primary Data** | 13px / 20px | 500 | 表格主行、关键状态名称 |
| **Body** | 13px / 20px | 400 | 一般正文、阶段日志说明 |
| **Metadata** | 12px / 18px | 400 | 表头文字、次要属性描述 |
| **Small Status** | 11px / 16px | 500 | 紧凑状态徽标、小指标数字 |
| **Runtime Mono**| 12px / 18px | 400 | Run ID、时间戳、代码块、Trace 日志 |

**关键权衡**：
- 业务标题 > Stage / Status > Runtime Metadata；
- Run ID、Heartbeat、时间等技术元数据不得抢夺 Story Name 的主导视觉权重；
- 所有数值、百分比、时间戳必须开启 `tabular numbers`，消除刷新时宽度抖动。

---

## 7. Layout (整体拓扑与断点)

- **Sidebar 宽度**：标准展开 `224px`，折叠模式 `64px`；
- **Top Header 高度**：`48px`；
- **Page Padding**：
  - $\ge 1600\text{px}$：`24px`
  - $1440\text{px} \sim 1599\text{px}$：`20px`
  - $1366\text{px} \sim 1439\text{px}$：`16px`
- **桌面断点设计**：
  - $\ge 1600\text{px}$：完整视图（主表 + 完整右侧 Rail）
  - $1440\text{px} \sim 1599\text{px}$：标准视图
  - $1280\text{px} \sim 1439\text{px}$：收缩次要元数据列
  - $1024\text{px} \sim 1279\text{px}$：Sidebar 自动折叠为 64px 图标条
  - $< 1024\text{px}$：保证可用，但桌面生产监控优先，绝不为小屏破坏桌面排障效率。

---

## 8. Data Grid (生产监控数据网格)

StoryOS Production Monitor 的主要视觉 Surface 是 **Data Grid**，而不是 Card。
- **Header Height**：`36px`，字体 `12px / 500`，字色 `--text-secondary`
- **Default Row Height**：`44px`（Compact Row 为 `40px`）
- **Cell Padding**：水平横向 `12px`，垂直纵向 `8px`
- **行分割规则**：默认仅采用 1px 细微 `--border-subtle` 底部分割线，严禁每行加完整包裹边框；
- **Hover**：轻微背景明度提亮（`--bg-hover: #1B2027`）；
- **Selected**：`--bg-selected: #20262E` 配合左侧 **2px `--info` 高亮指示条**；
- **状态行限制**：严禁整个 Row 因为 RUNNING 变为全行绿色，或因为 BLOCKED 变为全行刺眼大红色。

---

## 9. Operational Status Strip (状态条替代散乱 KPI)

Production Monitor 顶部严禁堆放 6 个等权 KPI Card，统一设计为单条贯穿的 **Operational Status Strip**：
- **高度约束**：`48px ~ 56px`
- **Label 尺寸**：`11px ~ 12px`
- **Value 尺寸**：`16px ~ 18px / 600`，Monospace Tabular
- **结构区隔**：依靠 spacing (16px)、1px 垂直微弱分割线（`--border-subtle`）与文字对比建立层级；
- **禁止项**：禁止彩色 icon 方块、禁止 6 张独立大卡片、禁止任何深色弥散投影。

---

## 10. Status Indicator (状态表达契约)

默认表达范式：
`● Running` / `● Waiting` / `● Retrying` / `● Blocked` / `● Completed`
- **实心状态点 (dot)**：直径 `6px`
- **间距 (gap)**：`6px`
- **状态文字**：`12px / 500 font-mono`
- **状态色限制**：色彩仅赋给 dot、状态文字、2px 标记条与小进度条，严禁大面积铺色。

---

## 11. Controls & Toolbar (控件规范)

- **Small Button**：高度 `28px`，padding `0 8px`，圆角 `4px`
- **Default Button**：高度 `32px`，padding `0 12px`，圆角 `4px`
- **Large Button**：高度 `36px`（StoryOS 后台严禁 40px~48px 巨大按钮）
- **Input / Select**：高度 `32px`，内边距 `0 10px`，圆角 `4px`
- **Toolbar 操作条**：高度 `40px ~ 44px`，整合搜索框与状态过滤器。

---

## 12. Drawer / Inspector (右侧技术排障检视器)

- **标准宽度**：`440px`（超宽屏或复杂排障模式允许 `520px`，最大上限 `640px`）；
- **容器风格**：直角 `radius: 0`，左侧 `1px solid --border-subtle`，背景 `--bg-elevated: #171B21`，极弱或无 shadow；
- **Header**：高度 `48px ~ 56px`，padding `0 16px`；
- **内容区 Padding**：`16px ~ 20px`，Section 间距 `24px`；
- **定位**：像 **IDE Inspector**，提供参数、Prompt、原图对比、质检项与生图 Trace，绝不是电商详情弹窗。

---

## 13. Pipeline & Stage Bar (管线阶段条)

阶段流转：`Create` → `Story Lock` → `Storyboard` → `Character` → `Visual Lock` → `Production` → `Review` → `Publish`
- **高度**：`56px ~ 64px`；
- **进度表达**：Production 阶段以文字清晰表达内部进度（如 `14 / 20`）；
- **严禁**：整块绿色/蓝色霓虹发光；活跃阶段使用微弱底色高亮、6px 状态点与极细高亮线即可。

---

## 14. Frame Grid (分镜缩略图矩阵)

- **桌面默认**：`5 columns` (超宽屏可 6 columns)
- **网格间距 (Gap)**：`12px`
- **卡片圆角**：`4px ~ 6px`
- **状态契约**：卡片内必须有状态代码文字与图标（`PASSED`, `RUNNING`, `QUEUED`, `RETRYING`, `BLOCKED`, `FAILED`, `NOT_STARTED`），严禁仅依靠边框颜色区分。

---

## 15. Shadow (阴影与物理深度)

- **默认表面**：Panel、Table、Section 一律使用 `shadow: none`，依靠表面底色差（`#0B0D10` vs `#13161B`）与 1px 细分割线区分；
- **仅限浮层**：Dropdown、Popover、Modal、Floating Inspector 允许使用极弱阴影：
  ```css
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.28);
  ```

---

## 16. Motion (动效与过渡契约)

- **Hover 过渡**：`120ms ease-out`
- **Dropdown 展开**：`140ms cubic-bezier(.2, .8, .2, 1)`
- **Drawer 进出**：`180ms cubic-bezier(.2, .8, .2, 1)`
- **Modal 弹出**：`160ms cubic-bezier(.2, .8, .2, 1)`
- **默认禁止**：呼吸灯闪烁、弹性弹跳 (Spring abuse)、背景流动光效、无业务意义的入场过渡。

## 创作交互与 Icon 语言（REA 行为提取 P0）

- **作品入口明确**：图库卡片单击打开右侧只读预览；列表“预览”是眼睛图标 + 文案，“作品标题”是直接进入制作；预览抽屉使用“进入故事制作”显式动作，不在预览时执行生产或审核写入。
- **列表 / 画廊切换**：统一复用 Ant Design Segmented；线性 List / Images 图标旁保留文字，所选模式只改变内容排布，不改变数据与审核身份。
- **线性图标契约**：复用项目既有 Lucide；导航 16px、密集控件 14px、小状态 12–14px、描边 1.75px，继承文本色；必须有可访问名称 / 文字说明，不用装饰性大色块，不新增 Icon 库或自制拟物资源。
- **图文产品语义**：故事用 BookOpenText，图片用 Image，分镜工作台用 PanelsTopLeft；避免 Film / Video / Clapperboard 暗示不提供的视频制作。品牌 StoryOSMark 独立保留。
- **逆向证据边界**：REA 是取证工具，并非可灵/即梦视觉组件库；只能复用交互理念，禁止把未经过登录与行为观测的细节说成对方产品的已验证实现。

## 轻量工具导航与参考素材草稿（REA 取证延伸 P0）

- 创作工作区顶部只有一条 32px 高的文字 + Lucide 14px 线性 Icon 快捷导航：帧定位、素材画布、审核记录、参考关联；只滚动当前工作区或打开既有 Inspector，不复制业务路由和页面。
- 帧级“参考关联”与“固定双帧对照”是不同功能：前者用于拟引用草稿，后者只是视觉比较。参考草稿只接受当前作品 local_workspace_approved_only 目录验证过的图片，不支持外部 URL 和跨作品引用。
- 每个目标 Frame 最多一个拟引用来源；保存于浏览器 localStorage，仅存 1..20 的目标帧号与经验证的同作品来源帧号/图片 URL 标识，载入时验证格式、展示时重新校验来源 ID/URL。允许解除关联，不把草稿传给 Runtime、生成请求或正式作品契约。
- UI 必须明确：仅本地草稿、未提交生产，不代表生成时实际使用了该参考图片。不能把参考数量、对照帧或作品级视觉锚点冒充真实 Prompt reference binding。
- 逆向证据：REA 官方 Chrome CDP passive page capture 用于结构/能力核验，不能推断未观察到的可灵或即梦后台行为。

## REA 快捷技能与逐帧一致性线索（P0）

- 已实测即梦的 `/` 技能入口，但 StoryOS 的 `/分镜`、`/角色`、`/提示词`、`/阻断` **只填写可编辑的生产指令草稿**。用户按 Enter 或点击技能不会下发任务；只有复制文本后在经过授权的生产入口才能进一步执行。切换作品时草稿重置，避免跨作品误用。
- 20 帧一致性检视只聚合当前作品 `frameReviews` 的 `WARN`/`FAIL` 问题标签，分为人物/画风与光影/场景。分类为文本标签匹配，不是视觉模型评分，也不等于对角色或场景一致性的正式认证。没有标签或审核记录时标记「未验证」，不伪造通过。
- 参考素材正式写入需 **目标 Frame 的稳定身份、来源已批准图的内容身份、授权写入 API、生成指令实际参考参数、provider 调用和执行回执** 共同闭环。现有 `localReferenceDraft` 永远仅是浏览器拟引用，不得基于 UI 或帧号匹配宣传正式绑定；Runtime writer 接口实现、审核后另议。

## REA 参考源身份核验（本机只读 P0）

- Frame 参考草稿依然只存浏览器，不可直接生成为正式绑定。为了避免“匿名展示 URL 代表内容 SHA”的误判，来源图片需通过本机只读 `GET /api/v1/local-media/source-fingerprint/{episode_ref}/{token}` 重新读取原始图片字节计算 SHA-256。服务端只接受同作品、已批准图库的精确 opaque ref + token；拒绝跨作品、跨域、路径穿越、查询参数和所有写方法。
- 核验返回完整 SHA 仅作为 **LOCAL_APPROVED_SOURCE_BYTES**，明确 `production_reference_binding=NOT_SUBMITTED`、`provider_execution=UNVERIFIED`；界面显示的是核验时的源图内容，不是生产 Writer 授权，也不是已传给 Provider 的回执。源图重绘／替换后必须重新核验。
- 下一阶段正式接入须走现有 `image_scheduler.contract_references`、`reference_arbitrator.MAX_REFS=2`、锁定身份锚点、`image_worker_pool._payload_reference_evidence` 与 `production_ledger_run.merge_provider_reference_evidence`，由授权 Writer 进行 Attempt 写入并在 provider receipt 后校验；禁止从浏览器 localStorage 直接写 ledger、MySQL 或人设契约。

## REA 状态、批量分镜、素材关系与多作品分流（P0）

- REA 的公开界面/本地 CDP 观察只用于 UI 信息层级与互动模式；无登录态证据不宣称竞品后台实现细节。StoryOS 历史 Run 不代替在线 Runtime 权威。
- 历史 Run Frame 矩阵和状态列表共用「全部 / 异常 / 未通过」过滤。异常仅来自 BLOCKED、RETRYING 或明确的 lastError，未通过包含其余非 PASSED 记录；这是只读定位，不是批量审批或重新生图。筛选后空集要说明证据范围，切换矩阵/列表不重置条件。
- 历史异常详情不为缺失的错误码、失败阶段、失败时间和重试时间填入假数据；未知写「未记录」。重试预计秒数若有值也仅作为保存时历史数值，不是实时倒计时。
- 多作品关注索引由已载入的作品级 preflight blocking 与 Frame FAIL 审核记录派生，按数量排序展示最高优先级 4 部；不能推断实时调度或未载入的作品状态。
- 参考源关系显示「目标帧 ← 拟引用源已批准帧 → 当前 SHA 核验状态」，并始终明确「生产未提交 / Provider 使用未验证」。不改变 Runtime、审批、MySQL、数据模型或生图链路。
## REA 字体与设置页可读性（界面 P1）

- REA 的可访问页面与既有取证用于研究深色紧凑工作台的字体层级和设置入口；没有可灵/即梦登录态后台的实测证据，不声称其字体实现等于 StoryOS。
- 页面/区块标题复用既定 Typography Token：20px/28px/600 与 14px/20px/600。历史 R14/R17 覆盖与 DESIGN.md 不一致，后置规则统一回到合同，不修改状态色、表格数据和业务流程。
- 「均衡显示」沿用 Inter → 现有系统中英文字体回退，「中文优先」调整系统字体候选顺序（苹方、微软雅黑、Noto），**不下载第三方字体、不引入字体资产/许可风险**。Runtime ID、日志、时间戳仍为系统等宽栈和 tabular nums；控件借助 Ant Design fontFamily Token 复用同一 `--font-sans`。
- 浏览器本机键 `storyos:font-preference:v1` 只允许 `balanced`/`chinese`，写入失败需显示「仅当前会话生效」而非谎称持久化。切换字体不修改生成 Prompt、合同、MySQL、生产权限。
- 设置页以「主题」和「字体与排版」两组可用功能配合实时预览；「生产管线」维持只读权限说明，不添加虚假的模型/并发设置开关。
## REA 设置全页与个人资料 · 公开证据限度（P0）

- 使用 REA 6.4.0（本机缓存可复现的版本）通过 CDP 观察即梦未登录创作页：公开导航存在登录与更多设置入口；点击登录出现手机号／验证码输入、其他登录方式、服务条款勾选和退出按钮。此次未登录，因此**无法逆向其登录后个人资料、安全、通知设置的实际读写与权限**；可灵公开页仅确认 Explore、Assets、Omni、Generate、All Tools 导航，没有已验证账号设置页面。不得将公开营销入口当作完整管理台设计事实。
- StoryOS 设置区使用一个受控 Tab 状态与清晰的多页层级：外观设置、个人资料、通知与提醒、账号与安全、生产管线。侧栏「个人资料」直接进入同一账号资料页；「系统设置」默认进入外观。复用既有紧凑排版及 Lucide 图标，不新建路由／账号管理栈。
- StoryOS **未提供可信认证身份及资料读写 API**：资料页所有字段必须明示未获取，禁止从 Git 用户名／环境信息／浏览器存储推导真人昵称、头像、邮箱、登录状态或会员等级；不能提供模拟保存、登出、修改密码、2FA 或访问密钥操作。
- 通知设置只能读取前端已载入会话的未读数，可通过「打开通知中心」调用真实抽屉。此值不是服务端通知总数，邮件/桌面推送没有持久化设置接口时不提供假开关；空通知应有真实空状态。
- 账号安全页与生产管线均只读，必须声明认证/授权尚未打通。外观、字体偏好仍只是浏览器 localStorage；页面不得暴露 Token、凭据、MySQL 配置或宣称跨设备同步。
## REA Mock 账号体验（访客、演示、过期）
- 即梦公开未登录页的登录弹窗/设置菜单取证只用于 UI 模式参考，可灵登录后数据与详情未获得实测；不得复制其未观察到的业务字段。StoryOS 左下角使用真实弹出账号菜单，键盘 Esc 与外部点击可关闭。
- `createMockAuthAdapter` 是 **UI 演示专属** adapter；`storyos:mock-ui-auth:v1` 使用严格 schema，只接受 guest/mock/expired 三种界面状态、预设头像/1-30 字符昵称，且写入失败明确「仅当前页面可用」。它不提供 token、角色、权限、真实 session、后台身份、跨端同步，也绝不能传给生产 Runtime 作为 Authority。
- 默认访客；「进入演示账号」不收集真实密码、手机号或验证码；个人资料可编辑本地昵称、预设头像并刷新恢复；退出清空本机演示会话，账号与安全页可模拟过期。模拟过期不授权、不可编辑；重新登录重置演示预设。
- 原有「系统设置」快捷入口继续可用，五个设置页复用受控状态；通知中心复用既有本地数据；生产管线继续只读。真实认证未来必须独立提供权限与后端审计，不可用浏览器 Mock 来跳过 Gate。
- 快速验收必须覆盖：弹窗与菜单开关、浏览器刷新恢复、资料保存和 Avatar、过期、重新登录、退出、禁用 localStorage、1024/1440 布局、字体/主题回归与原生 API 7/7 合同。
## REA 账号与设置高保真整改（2026-10-14 · 四槽）
- 取证基线：即梦公开未登录页可观察宽屏两栏登录弹层（约 984×560，实际 DOM 与截图），右上角单独「更多设置」用于深色模式/产品入口；未取得即梦与可灵登录后资料页的真实 DOM。因此只对齐可验证的信息分层与交互，不声称复刻登录后的私有页面。
- 登录窗口采用 StoryOS 自有原创故事视觉抽象排版作为左栏，右栏为明确标识「Mock」的一键演示登录；绝不模拟真实验证码、第三方 OAuth token、账户签约或复制竞品图像；窄屏折叠视觉左栏，保持可用。
- 左下角账号卡片与「系统设置」快捷入口分层：前者账号/个人资料/安全/通知，后者进入原五个设置页。账号菜单支持 ArrowDown/ArrowUp/Home/End、Esc 关闭与焦点恢复、Tab 离开关闭和点击外部关闭，且没有后台权限意义。
- 个人资料改为预览态 → 显式「编辑资料」 → 保存/取消；仍只编辑本地昵称和预设头像，恢复持久化/失败反馈；真实账号数据未接入的部分明确标示无授权。
- 登录对话框 Tab/Shift+Tab 在模态框内循环，Esc 与关闭按钮释放焦点回账号卡片；不触及生产的 Runtime Gate、MySQL、native Codex 图片通道和审核提交。浏览器验收包括 390/1024/1440 视口、旧 Mock 5 阶段、原设置/字体/主题/API 回归。

## R18 侧栏底栏视觉减法（2026-10-14）
- 正式 3100 实测：旧底栏约 139.75px，高度由三层（外观标签+主题、系统设置整行、带边框账号卡）组成。桌面新版约 89.25px（在相同 1424×805 视口），仅保留一排低对比度设置/主题图标和一个无常驻边框的账号行。功能和菜单项没有删减。
- 快捷设置仍保留 `aria-label="系统设置"`；深色/浅色按钮仍可直接访问，且提供 `aria-pressed`。账号入口继续使用 `aria-label="账号菜单"` 与完整 Mock/访客状态说明。
- 1120px 及以下侧栏缩至图标轨道：设置保持居中 42px 点击区域，主题组折叠至系统设置页；账号只显示头像，并将其菜单从图标轨道右侧展开，避免紧窄侧栏中菜单向左溢出。
- 继续遵守 Mock 身份无生产授权；没有重写账号适配层、生产 Runtime 或相关证据。
