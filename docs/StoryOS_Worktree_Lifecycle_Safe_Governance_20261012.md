# StoryOS Worktree 生命周期与安全退役门禁（2026-10-12）

## 基本原则

- 工作树按 ACTIVE → MERGED / PATCH_EQUIVALENT_REVIEW → VERIFIED → RETIRED 管理。
- git branch --merged 证明提交祖先关系；git cherry 全为 - 仅提示 Patch-ID 等价，不代表运行数据可清理，更不代表正式生产完成。
- scripts/storyos_worktree_audit_readonly.py 永远只读，safe_to_delete 始终为 false；不执行 git worktree remove、reset、clean，不自动删除分支。
- Git status 干净也不能证明安全：忽略目录里可能有 MySQL、Episode、Canary、Review Authority、UNKNOWN Attempt、浏览器失败证据。
- Windows Junction 与 symbolic link 的目标可能位于主工作树共享 node_modules。不得递归跟随或删除链接目标。

## 日常只读审计

在主工作区运行：

    python scripts/storyos_worktree_audit_readonly.py --main-ref story-platform-v3-rever --offset 0 --limit 20

每页最多 30 个工作树。报告包含 Git 提交祖先性、未合并 Patch-ID 等价线索、Git 状态、忽略项、Junction 入口，以及安全保护原因；仅供人工核查。

## 人工退役门禁

1. Fetch 最新主线并核对工作树 HEAD 未变化；不能重置其他 Agent 的工作区。
2. 核对 Git tracked/untracked status；若仅 Patch-ID 等价，还必须人工验明业务等价和无独有资料。
3. 排查所有被忽略的运行资产、生产回执、Canary、媒体素材、QA 失败截图及锁文件；只允许经过详细白名单与人工验收的已知构建缓存。
4. 排查运行进程和 Worktree 锁；对于已批准过期浏览器 Profile，先将必留截图、报告、失败回执按 SHA-256 归档。
5. 对指定单棵已审核树使用非强制 git worktree remove；如存在 Windows Junction，应先严格核对其指向主工作区依赖目录，只移除旧树链接本身。
6. 验证分支引用、Git worktree list、目标路径、生产资产和共享依赖、归档哈希以及磁盘可用空间。将回执保存在本地 .storyos/archive/worktree-retirement-YYYYMMDD/。

禁止按 integrated 名称、日期、Patch-ID 等价标志批量强制删除。禁止把工作树清理作为正式发布权限。

## 历史执行记录（非发布许可）

- 2026-10-11：退役 9 个已合并历史工作树，QA 证据归档 187 份。
- 2026-10-12：退役 44 个 Patch-ID 等价且额外安全门禁通过的历史树，另外回收 R10 的 4 个旧浏览器 Profile。
- 清理回执由本地忽略目录保存，不会在 git push 时自动同步，不得据此伪造生产审核通过。
