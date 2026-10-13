# StoryOS R17 · 隔离 MySQL8 Project/Episode 草稿持久化

日期：2026-10-13。正式图片、生产 Episode、Writer/Driver、mysql8.0 容器均不进入本方案。

## 独立测试数据库

- 单独使用已存在的专用 TEST_ONLY 容器 `storyos-test-only-mysql-frame01-pr72-20261011`（宿主端口 13306）。
- 独立 schema `STORYOS_R17_DRAFT_TEST_20261013`、独立受限 MySQL 账户；凭据存在主工作区 Git 忽略的 `.storyos-tmp/r17-test-only/mysql-auth.json`。
- `platform/repository/mysql/r17_test_only_draft_schema.sql` 只能在上述数据库执行，和 `STORY_OS_RUNTIME` 完全隔离。
- Python 实现 `r17_isolated_draft_repo.py` 会核对数据库名、宿主地址和测试端口，拒绝正式生产数据库。

## 已实现

- R16 格式的浏览器草稿与自建 Project 作为整体导入。
- 独立 `TEST_BUNDLE`、`TEST_PROJECT`、`TEST_DRAFT` 测试身份，没有任何正式 canonical Episode 主键。
- MySQL InnoDB 主键和唯一索引、原子事务、`request_id` 业务幂等、来源 ID 冲突阻断。
- 草稿标题 `expected_version` 乐观锁、幂等回执、只追加测试操作审计。
- 并行同一个请求只持久化一次。MySQL 的 source data 和正式 State/Attempt 无交叉写端。

## 不可越过的阶段

这不是正式服务端 Writer。Node 独立 TEST_ONLY 端口仍使用此前已实现的 SQLite 测试存档。MySQL 实现是更接近正式部署的数据合同验证，尚未接入浏览器或真正的 Operator Session。

正式开放之前，需要：安全操作会话、明确 CSRF token、MySQL 专用正式 schema 设计评审、人工 `draft_id→canonical_episode_id` 分配和映射审计、同 Episode Writer admission、Runtime Request 与 Gate 的事务化接入、进一步真机故障注入验收。不得通过此 TEST_ONLY 证明授权正式生产。
