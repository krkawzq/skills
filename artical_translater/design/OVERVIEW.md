# 项目概览

## 定位
该项目是一个用于学术论文（Markdown）的翻译工具集，核心能力包括：
- 结构扫描与分块（章节树、段落块、稳定的 chunk_id）
- 高并发翻译（异步 API 调用）
- 逐条校验与锁保护的翻译数据库（JSONL）
- 双语输出与对齐导出

## 核心特性
- 高并发：可配置并发数，支持中断后继续
- 可追踪：chunk_id 对应段落块，进度可精确统计
- 可恢复：翻译数据库为追加式，支持重试与补录
- 安全写入：`append_translation.py` 使用锁文件避免并发写入冲突

## 设计要点
- 段落块以空行分隔；代码块与数学块视为“保护块”，不会被分块
- 验证器（`check_translation_entry.py`）提供结构化错误，便于自动重试
- 翻译流程支持两种模式：
  1) 单体高并发翻译（`translate_concurrent.py`）
  2) 多代理/多人协作分块翻译（`list_chunks.py` + `append_translation.py`）

## 数据模型摘要
- **Chunk**：一段正文，具备稳定 ID（`s{section_id}p{para_index}`）
- **Entry**：翻译条目（JSON），最小字段为 `chunk_id` + `target_md`
- **DB**：JSONL 追加式数据库，按 `chunk_id` 聚合（最后一条生效）
