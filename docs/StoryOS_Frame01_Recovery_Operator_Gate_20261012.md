# StoryOS Frame01 恢复操作规范

新增三个阶段：plan、backup、execute。plan 和 backup 均为只读数据核查，不写正式 MySQL；execute 需要独立审批、来源证明与备份，并且本轮不执行。

本轮仅针对隔离工作树进行代码开发和测试。正式生产状态保持阻断，绝不新增图片 Attempt，也不代替像素审核。
