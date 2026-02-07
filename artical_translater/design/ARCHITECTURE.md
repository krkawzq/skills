# Artical Translater - Design

This folder is a Codex-friendly "skill" that provides **CLI tools** for turning an
OCR-produced Markdown paper into a **translation workflow** (either single-agent with
high-concurrency API calls, or multi-agent with chunk-based coordination).

The toolkit includes a translator (`translate_concurrent.py`) and supporting primitives so a
primary agent can:

- understand document structure (menu/tree + stats),
- normalize headings (when OCR output is flat),
- extract sections / list paragraph chunks (for task splitting),
- safely collect per-chunk translation results from multiple sub-agents,
- assemble a final bilingual Markdown output.

## Goals

- Work on OCR-produced academic papers (Markdown).
- Enable parallel translation via chunk IDs + append-only JSONL "translation DB".
- Support optional OCR correction: sub-agent can provide corrected source text + translation.
- Keep tooling easy to call from other agents; core utilities remain stdlib-only,
  while the translator uses `aiohttp`, `tqdm`, `tenacity`, and `pyyaml`.

## Non-goals (for now)

- Perfect Markdown semantics (tables, nested lists, math) for every edge case.
- Automatic LLM translation inside the scripts.
- Automatic "best heading hierarchy" inference (we provide deterministic helpers).

## Concepts / Data Model

### Section

A "section" is defined by an ATX heading line:

```md
## Methods
```

Each heading gets an auto-increment `section_id` in document order (`1..N`).
Content before the first heading belongs to `section_id = 0` (document root).

### Paragraph Chunk

A "paragraph chunk" is a block of **non-empty** lines separated by blank lines, excluding
code-fence blocks (```/~~~). Each chunk belongs to the *current* section at the time it
appears.

Chunk ID format (stable as long as headings + paragraph boundaries are unchanged):

```
s{section_id:04d}p{para_index_in_section:04d}
```

Example: `s0003p0007`

### Translation DB (JSONL)

Sub-agents append translation results as JSON objects (one per line) into a single file:

```
work/translations.jsonl
```

Order does not matter. The assembler uses `chunk_id` as the key (last entry wins).

Recommended minimal schema:

```json
{
  "chunk_id": "s0003p0007",
  "target_lang": "zh",
  "target_md": "..."
}
```

Optional OCR correction fields:

```json
{
  "chunk_id": "s0003p0007",
  "source_md": "corrected English paragraph (optional)",
  "target_lang": "zh",
  "target_md": "Chinese translation",
  "notes": "optional"
}
```

## Tools

### 1) Structure / Menu Scan

`scripts/scan_structure.py`

- Builds a section tree from headings.
- Prints per-section stats (direct paragraphs/chars and totals).
- Intended for a primary agent to decide chunking/parallelism.

### 2) Normalize Heading Levels (OCR often flattens headings)

`scripts/normalize_headings.py`

- `--mode numbering`: infer heading levels from prefixes like `1`, `1.1`, `1.1.1`.
- `--mode map`: apply a manual mapping from "heading index -> level".

Workflow is typically:

1. scan
2. normalize headings
3. scan again (now the structure is correct)

### 3) List Headings / Extract Section

- `scripts/list_headings.py`: print heading list with indices and section IDs.
- `scripts/extract_section.py`: extract a section to stdout by heading index/title/regex.

### 4) List Paragraph Chunks (for sub-agent tasks)

`scripts/list_chunks.py`

- Emits JSONL records for each chunk:
  - `chunk_id`, `section_id`, `section_path`, `para_index`, `char_count`, `source_md`, `source_sha1`
- Supports filtering by section/subtree.

### 5) Append Translation (Safe for Concurrency)

`scripts/append_translation.py`

- Reads JSON / JSONL from stdin.
- Uses a lock file (atomic create) to avoid concurrent append corruption.
- Appends entries to the translation DB (JSONL).
- Optionally validates entries against `work/chunks.jsonl` to reject bad formats and prevent link/image corruption in `source_md`.

### 6) Assemble Final Bilingual Markdown

`scripts/assemble_bilingual.py`

- Reads source Markdown + translation DB.
- Inserts translation blocks after each paragraph chunk (by chunk ID).
- Optionally replaces OCR source paragraph with `source_md` from DB when provided.

### 7) Export Aligned EN/ZH Pair + Merge

- `scripts/export_aligned_pair.py`: write an aligned corrected-source Markdown and a target-language Markdown.
- `scripts/merge_aligned_bilingual.py`: merge the aligned pair into a bilingual Markdown output.

## Recommended End-to-End Workflow (Primary Agent)

1. `scan_structure.py` to understand the document tree and size.
2. If headings are broken/flat:
   - `normalize_headings.py` to rewrite heading levels
   - re-run `scan_structure.py`
3. `list_chunks.py` (optionally filtered by section) to create translation tasks.
4. Dispatch chunks to sub-agents (each chunk is independent).
5. Sub-agents call `append_translation.py` to store results.
6. `assemble_bilingual.py` to generate final bilingual Markdown output.
7. (Optional) `export_aligned_pair.py` + `merge_aligned_bilingual.py` when you want separate EN/ZH files plus a merged bilingual file.

## Concurrency Notes

- Appending uses a `.lock` file next to the DB.
- If the process crashes while holding a lock, the lock file may remain; manual deletion
  may be required.

## Reliability Notes (Retry)

- Recommended workflow is "validate -> append": run `check_translation_entry.py` before appending.
- When a sub-agent produces invalid JSON/fields, the primary agent can retry by sending back
  the checker/append error message and requesting a fixed entry.
