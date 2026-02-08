# 文章翻译框架 - 重构完成

## 重构概述

本次重构完成了以下核心改进：

### 1. 模块化架构
- **`scripts/shared.py`** - 共享工具函数（load_config, source_md_is_safe, sanitize_target_md 等）
- **`scripts/prompts.py`** - 硬编码提示词模块（避免 .format() 与 LaTeX 冲突）
- **`scripts/response_parser.py`** - 结构化输出解析器（解析 AI 的 markdown 代码块和元信息）
- **`scripts/normalize_math.py`** - 公式标准化工具（规则引擎 + AI 引擎）

### 2. 核心改进
- ✅ **彻底解决 LaTeX 冲突** - 提示词硬编码，使用字符串拼接，不再需要 `{{}}` 转义
- ✅ **结构化 AI 输出** - AI 输出分析 + ```markdown translated``` 块 + 元信息
- ✅ **CHECKER_BYPASS 机制** - AI 可声明 checker 误报，系统尝试 sanitize 后直接接受
- ✅ **主 agent 指导接口** - 支持 `--guidance` / `--guidance-file` 参数
- ✅ **原文校准功能** - `enable_source_correction` 开关，AI 同时输出校准原文和翻译
- ✅ **公式格式修复** - `enable_math_fixing` 开关，AI 修复 OCR 公式问题

### 3. 新增工具
- **normalize_math.py** - 独立的公式标准化工具
  - 规则引擎：Unicode → LaTeX 映射，空格修复
  - AI 引擎：处理复杂 OCR 错误（需要 --ai 标志）

### 4. 配置变更
`config.yaml` 中：
- ❌ 移除 `system_prompt` 字段
- ✅ 新增 `enable_source_correction: false`
- ✅ 新增 `enable_math_fixing: true`

## 使用方法

### 基本翻译
```bash
python scripts/translate_concurrent.py \\
    --chunks work/chunks.jsonl \\
    --output work/translations.jsonl \\
    --config config.yaml
```

### 带主 agent 指导的翻译
```bash
python scripts/translate_concurrent.py \\
    --chunks work/chunks.jsonl \\
    --output work/translations.jsonl \\
    --config config.yaml \\
    --guidance "本文是关于深度学习的论文，注意术语：attention→注意力机制"
```

### 公式标准化
```bash
# 规则引擎（快速）
python scripts/normalize_math.py --input paper.md --output paper.fixed.md

# AI 引擎（处理复杂情况）
python scripts/normalize_math.py \\
    --chunks work/chunks.jsonl \\
    --output work/chunks.fixed.jsonl \\
    --config config.yaml --ai
```

## AI 输出格式

AI 现在输出结构化格式：

```
### Step 1: Analysis
This is a simple paragraph with no formulas.

### Step 2: Translation
```markdown translated
这是一个没有公式的简单段落。
```

### Step 3: Meta-info
DIFFICULTY: easy
POTENTIAL_ISSUES: none
CONFIDENCE: high
CHECKER_BYPASS: none
NOTES: none
```

## 向后兼容性

- ✅ JSONL 数据库格式完全兼容
- ✅ 所有现有工具脚本（check_translation_entry.py, append_translation.py 等）无需修改
- ❌ 不再支持旧的"直接输出原始文本"模式（强制结构化格式）

## 测试

运行测试以验证重构：
```bash
# 测试公式标准化
python scripts/normalize_math.py --input test.md --output test.fixed.md

# 测试翻译（少量 chunks）
python scripts/list_chunks.py -p test.md --min-chars 50 | head -5 > work/test_chunks.jsonl
python scripts/translate_concurrent.py \\
    --chunks work/test_chunks.jsonl \\
    --output work/test_translations.jsonl \\
    --config config.yaml
```

## 文档

详细使用说明请参考 `SKILL.md`。
