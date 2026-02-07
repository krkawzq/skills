# 项目结构

```
artical_translater/
├── SKILL.md                    # 唯一使用指南（Agent 直接阅读）
├── config.yaml                 # API 与翻译配置
├── requirements.txt            # 依赖
├── scripts/                    # 核心脚本
│   ├── translate_concurrent.py
│   ├── handle_failed_chunks.py
│   ├── scan_structure.py
│   ├── list_chunks.py
│   ├── list_headings.py
│   ├── extract_section.py
│   ├── normalize_headings.py
│   ├── check_translation_entry.py
│   ├── append_translation.py
│   ├── check_translations_db.py
│   ├── batch_validate.py
│   ├── batch_append.py
│   ├── assemble_bilingual.py
│   ├── export_aligned_pair.py
│   ├── merge_aligned_bilingual.py
│   ├── md_scan.py
│   └── md_tokens.py
├── design/                     # 设计/架构文档（面向人类）
│   ├── ARCHITECTURE.md
│   ├── OVERVIEW.md
│   ├── PROJECT_STRUCTURE.md
│   └── IMPROVEMENTS.md
├── examples/                   # 示例素材（可选）
└── agents/                     # Agent 配置（可选）
```
