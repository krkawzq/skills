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

system_prompt: |
  ...（翻译规则）...
```

**API Key 优先级**：若设置 `OPENAI_API_KEY`，会覆盖 `config.yaml` 中的 `api_key`。

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

## 8) 关键规则（必须遵守）

1. **一条 chunk = 一段正文**，禁止空行分割  
2. **不引入结构符号**：`#` 标题、``` 代码围栏、`$$` 数学围栏  
3. **链接与图片路径保持不变**  
4. **LaTeX 公式需保持语义一致**（默认允许格式微调；若需严格一致，可手动使用 `check_translation_entry.py --protect-math`）

---

## 9) 常见问题

**Q: API key 报错**  
A: 设置 `OPENAI_API_KEY` 或在 `config.yaml` 中填写 `api_key`。

**Q: 429 速率限制**  
A: 降低 `concurrency`，提高 `retry_delay`。

**Q: 校验失败（空行/结构符号）**  
A: 删除段内空行，禁止新增 `#`、```、`$$`。

---

## 10) 推荐清单

开始前：
- [ ] `pip install -r requirements.txt`
- [ ] `config.yaml` 已配置
- [ ] `work/` 已创建

完成后：
- [ ] `check_translations_db.py` 显示 missing=0
- [ ] `paper.bilingual.md` 生成成功
