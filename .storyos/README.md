# .storyos

Story OS 内部维护目录，不是人工生产配置入口。

- `history/install/`：历史安装与补丁记录。
- `history/migrations/`：迁移账本。
- `history/legacy/`：已被新结构替代但暂时保留的兼容文件。
- `user-visual-references/`：仅本地保存用户原始参考图片的 SHA 命名执行副本；`source-packages/` 保留对应原始文件名、manifest 与说明。两者均受 `.gitignore` 保护，不属于剧情/人物/审片权威，也不随 Git 推送。

人工配置统一位于 `config/storyos.yaml`，仓库索引位于 `config/index.yaml`。

