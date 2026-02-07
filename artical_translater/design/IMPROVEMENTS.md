# 改进与变更摘要

## 文档结构调整
- 使用指南合并为 **单一** `SKILL.md`
- 设计/架构类文档统一放入 `design/` 目录
- 删除分散的多份指南与索引，避免重复与不一致

## 工具链补强
- 批量校验与批量追加脚本保留，用于多人协作场景
- `handle_failed_chunks.py` 与 `translate_concurrent.py` 一致支持环境变量 API Key
- 批量脚本改为 `subprocess` 调用，避免依赖外部 `python` 命令解析

## 稳健性与一致性
- 统一以 `config.yaml` 为唯一配置入口
- 使用指南内容与脚本参数对齐（如 `-p/--path`、`--translations`、`-o` 等）
