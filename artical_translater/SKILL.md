---
name: artical-translater
description: 学术论文 Markdown 翻译工具链（高并发翻译 + 分块校验 + 双语输出）
---

# Artical Translater 使用指南（唯一入口）

本文件是 **唯一** 的使用指南。阅读完即可完成从 Markdown 论文到双语文档的全流程操作。
所有脚本都假设在项目根目录 `artical_translater/` 下执行。

## 0) 最快上手（5 步）

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 准备工作目录
mkdir -p work

# 3. 扫描结构与切块
python scripts/scan_structure.py -p paper.md
python scripts/list_chunks.py -p paper.md > work/chunks.jsonl

# 4. 高并发翻译（自动验证与追加）
python scripts/translate_concurrent.py \
  --chunks work/chunks.jsonl \
  --output work/translations.jsonl \
  --config config.yaml

# 5. 生成双语文档
python scripts/assemble_bilingual.py \
  -p paper.md \
  --translations work/translations.jsonl \
  -o paper.bilingual.md \
  --prefer-corrected-source
```

如中断，使用 `--resume` 继续翻译：
```bash
python scripts/translate_concurrent.py \
  --chunks work/chunks.jsonl \
  --output work/translations.jsonl \
  --config config.yaml \
  --resume
```

---

## 1) 输入与前置条件

- 输入文件：Markdown 论文（推荐 UTF-8）
- 依赖：Python 3.8+，`requirements.txt`
- API：OpenAI 兼容的 Chat Completions 端点
- 运行目录：`artical_translater/`

---

## 2) 配置说明（config.yaml）

示例（关键字段）：
```yaml
api:
  base_url: "https://api.openai.com/v1"
  api_key: ""   # 也可用环境变量 OPENAI_API_KEY
  model: "gpt-4"

translation:
  concurrency: 100
  timeout: 60
  max_retries: 3
  retry_delay: 1
  target_language: "Chinese"
  enable_iterative_validation: true
  max_validation_iterations: 3

  # 新增特性开关
  enable_source_correction: false  # AI 同时输出校准原文和翻译
  enable_math_fixing: true         # AI 修复 OCR 公式格式问题
```

**API Key 优先级**：若设置 `OPENAI_API_KEY`，会覆盖 `config.yaml` 中的 `api_key`。

**注意**：系统提示词已硬编码在 `scripts/prompts.py` 中，不再需要在 config.yaml 中配置。

---

## 3) 主流程详解

### 3.1 结构扫描（可选但推荐）
```bash
python scripts/scan_structure.py -p paper.md
```
输出章节树与统计信息，用于估算规模与分块策略。

### 3.2 标题层级修复（可选）
OCR 常见问题是标题全部变成 `#`。可用：
```bash
python scripts/normalize_headings.py --in paper.md --out paper.norm.md --mode numbering --strip-numbering
python scripts/scan_structure.py -p paper.norm.md
```
后续命令用 `paper.norm.md`。

### 3.3 列出分块
```bash
python scripts/list_chunks.py -p paper.md > work/chunks.jsonl
```
每行是一个 chunk（JSON），字段包含 `chunk_id`、`section_id`、`source_md` 等。

### 3.4 高并发翻译（推荐默认方式）
```bash
python scripts/translate_concurrent.py \
  --chunks work/chunks.jsonl \
  --output work/translations.jsonl \
  --config config.yaml
```
特性：
- 并发 API 调用（`concurrency`）
- 自动重试（`max_retries`, `retry_delay`）
- 逐条验证并追加（内部调用 `check_translation_entry.py` 与 `append_translation.py`）
- 支持 `--resume` 跳过已完成条目
- **结构化 AI 输出**：AI 输出分析、翻译（在 ```markdown translated``` 块中）、元信息（难度、置信度等）
- **CHECKER_BYPASS 机制**：AI 可声明 checker 误报，系统自动 sanitize 后接受

**带主 agent 指导的翻译**（推荐用于复杂论文）：
```bash
# 直接传入指导文本
python scripts/translate_concurrent.py \
  --chunks work/chunks.jsonl \
  --output work/translations.jsonl \
  --config config.yaml \
  --guidance "本文是关于深度学习的论文，注意术语：attention→注意力机制，transformer→变换器"

# 从文件读取指导文本（适合长文本）
python scripts/translate_concurrent.py \
  --chunks work/chunks.jsonl \
  --output work/translations.jsonl \
  --config config.yaml \
  --guidance-file work/guidance.txt
```
主 agent 可在 guidance 中传递：
- 论文摘要分析
- 领域术语表
- 翻译风格要求
- 特殊处理说明

### 3.5 进度监控
```bash
python scripts/check_translations_db.py --chunks work/chunks.jsonl --db work/translations.jsonl
```

### 3.6 生成双语文档
```bash
python scripts/assemble_bilingual.py \
  -p paper.md \
  --translations work/translations.jsonl \
  -o paper.bilingual.md \
  --prefer-corrected-source
```
输出格式：
```
英文段落

> 中文段落
```

---

## 4) 翻译条目格式（Entry）

最小格式：
```json
{
  "chunk_id": "s0003p0001",
  "target_md": "中文翻译..."
}
```

可选字段（用于 OCR 修正）：
```json
{
  "chunk_id": "s0003p0001",
  "source_md": "修正后的英文段落",
  "target_md": "中文翻译",
  "notes": "可选备注"
}
```

---

## 5) 多代理/多人协作（可选）

流程与脚本不变，只是翻译环节由多个代理/人员分块完成：

1. 主代理生成 `work/chunks.jsonl`
2. 分配 chunk_id 给子代理
3. 子代理生成 entry JSON
4. 子代理先校验再追加：
```bash
python scripts/check_translation_entry.py --in work/entry_xxxx.json --chunks work/chunks.jsonl
python scripts/append_translation.py --db work/translations.jsonl --chunks work/chunks.jsonl --in work/entry_xxxx.json
```
5. 主代理用 `check_translations_db.py` 统计进度

如需批量校验/追加：
```bash
python scripts/batch_validate.py --dir work --chunks work/chunks.jsonl
python scripts/batch_append.py --dir work --db work/translations.jsonl --chunks work/chunks.jsonl --validate
```

---

## 6) 失败条目处理

若 `translate_concurrent.py` 结束后有失败条目，会生成：
```
work/failed_chunks.json
```
可用：
```bash
python scripts/handle_failed_chunks.py \
  --failed-chunks work/failed_chunks.json \
  --chunks work/chunks.jsonl \
  --output work/translations.jsonl \
  --config config.yaml
```

---

## 7) 其他工具（按需）

- **公式标准化工具**（处理 OCR 公式格式问题）：
  ```bash
  # 处理完整 Markdown 文件（仅规则引擎，无 API 调用）
  python scripts/normalize_math.py --input paper.md --output paper.fixed.md

  # 处理 chunks JSONL（仅规则引擎）
  python scripts/normalize_math.py --chunks work/chunks.jsonl --output work/chunks.fixed.jsonl

  # 处理 chunks JSONL（规则 + AI 引擎，需要 API）
  python scripts/normalize_math.py \
    --chunks work/chunks.jsonl \
    --output work/chunks.fixed.jsonl \
    --config config.yaml --ai --concurrency 50
  ```
  规则引擎修复：Unicode → LaTeX 映射（∫→\int, ×→\times 等）、公式内空格、下标/上标空格
  AI 引擎修复：复杂 OCR 错误（需要 `--ai` 标志）

- 列出标题：
  ```bash
  python scripts/list_headings.py -p paper.md
  ```
- 提取章节：
  ```bash
  python scripts/extract_section.py -p paper.md --index 3 > section.md
  ```
- 导出对齐双文件：
  ```bash
  python scripts/export_aligned_pair.py \
    -p paper.md \
    --translations work/translations.jsonl \
    --out-source paper.en.md \
    --out-target paper.zh.md \
    --prefer-corrected-source
  ```
- 合并对齐双文件为双语：
  ```bash
  python scripts/merge_aligned_bilingual.py \
    --source paper.en.md \
    --target paper.zh.md \
    -o paper.bilingual.md
  ```

---

## 8) 新架构特性（v2.0 重构）

### 8.1 结构化 AI 输出
AI 翻译器现在输出结构化格式，包含：
- **Step 1: Analysis** - 翻译前分析（内容类型、棘手元素、潜在问题）
- **Step 2: Translation** - 翻译内容（在 ```markdown translated``` 代码块中）
- **Step 2b: Source Correction** - 原文校准（条件性，在 ```markdown corrected``` 代码块中）
- **Step 3: Meta-info** - 元信息字段：
  - `DIFFICULTY`: easy/medium/hard
  - `CONFIDENCE`: high/medium/low
  - `POTENTIAL_ISSUES`: 预估问题
  - `CHECKER_BYPASS`: AI 声明 checker 误报的说明
  - `NOTES`: 翻译选择说明

### 8.2 CHECKER_BYPASS 机制
当 AI 认为验证器误报时，可在 `CHECKER_BYPASS` 字段中说明原因。系统会：
1. 尝试 `sanitize_target_md()` 修复常见格式问题
2. 重新验证，若通过则接受
3. 若仍失败，标记为需人工审查但不再重试

这减少了无效重试，提高了效率。

### 8.3 原文校准功能
当 `enable_source_correction: true` 时，AI 同时输出：
- 校准后的原文（修复 OCR 错误）
- 基于校准原文的翻译

一轮 API 调用完成两项工作，更高效。

### 8.4 公式格式修复
当 `enable_math_fixing: true` 时，AI 修复 OCR 公式问题：
- 移除多余空格：`$ x ^ 2 $` → `$x^2$`
- 修复下标/上标：`\int _ { 0 } ^ { 1 }` → `\int_{0}^{1}`
- Unicode → LaTeX：`∫` → `\int`, `×` → `\times`
- 保留数学内容，只修复格式

### 8.5 模块化架构
新架构将代码分为 4 个核心模块：
- **scripts/shared.py** - 共享工具函数（消除重复代码）
- **scripts/prompts.py** - 硬编码提示词（避免 .format() 与 LaTeX 冲突）
- **scripts/response_parser.py** - 结构化输出解析器
- **scripts/normalize_math.py** - 公式标准化工具（规则 + AI 双层）

---

## 9) 关键规则（必须遵守）

1. **一条 chunk = 一段正文**，禁止空行分割  
2. **不引入结构符号**：`#` 标题、``` 代码围栏、`$$` 数学围栏  
3. **链接与图片路径保持不变**  
4. **LaTeX 公式需保持语义一致**（默认允许格式微调；若需严格一致，可手动使用 `check_translation_entry.py --protect-math`）

---

## 10) 常见问题

**Q: API key 报错**  
A: 设置 `OPENAI_API_KEY` 或在 `config.yaml` 中填写 `api_key`。

**Q: 429 速率限制**  
A: 降低 `concurrency`，提高 `retry_delay`。

**Q: 校验失败（空行/结构符号）**  
A: 删除段内空行，禁止新增 `#`、```、`$$`。

---

## 11) 推荐清单

开始前：
- [ ] `pip install -r requirements.txt`
- [ ] `config.yaml` 已配置
- [ ] `work/` 已创建

完成后：
- [ ] `check_translations_db.py` 显示 missing=0
- [ ] `paper.bilingual.md` 生成成功
