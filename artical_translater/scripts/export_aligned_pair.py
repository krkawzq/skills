#!/usr/bin/env python3
import argparse
import json
import re
import sys
from typing import Dict, List, Optional

from md_scan import iter_paragraph_chunks


def load_translation_db(path: str) -> Dict[str, dict]:
    translations: Dict[str, dict] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in translations DB at line {line_no}: {e}") from e
            if not isinstance(obj, dict):
                raise ValueError(f"Translations DB line {line_no} is not a JSON object.")
            chunk_id = obj.get("chunk_id")
            if not isinstance(chunk_id, str) or not chunk_id.strip():
                raise ValueError(f"Translations DB line {line_no} missing chunk_id.")
            translations[chunk_id.strip()] = obj  # last entry wins
    return translations


def pick_target_text(entry: dict) -> Optional[str]:
    for key in ("target_md", "target_text", "translation"):
        val = entry.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return None


def ensure_single_paragraph(text: str) -> bool:
    # Reject blank-line-separated content to keep alignment stable.
    return re.search(r"\n\s*\n", text.replace("\r\n", "\n").strip()) is None


def has_block_openers(text: str) -> bool:
    heading_line_re = re.compile(r"^\s*#{1,6}\s+")
    for ln in text.replace("\r\n", "\n").split("\n"):
        stripped = ln.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            return True
        if ln.strip() in ("$$", r"\["):
            return True
        if heading_line_re.match(ln):
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export two aligned Markdown files: corrected source and translated target (one paragraph per chunk).",
    )
    parser.add_argument("--path", "-p", required=True, help="Path to the source Markdown file.")
    parser.add_argument("--translations", required=True, help="Path to translations JSONL DB.")
    parser.add_argument("--out-source", required=True, help="Output path for corrected source Markdown.")
    parser.add_argument("--out-target", required=True, help="Output path for target-language Markdown.")
    parser.add_argument(
        "--prefer-corrected-source",
        action="store_true",
        help="If an entry provides source_md, replace the OCR paragraph with it in the source output.",
    )
    parser.add_argument(
        "--annotate",
        action="store_true",
        help="Insert HTML comments with chunk_id before each paragraph in both outputs.",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Allow missing translations; keep the original paragraph in target output for missing chunks.",
    )
    args = parser.parse_args()

    try:
        with open(args.path, "r", encoding="utf-8") as f:
            source_lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: file not found: {args.path}", file=sys.stderr)
        raise SystemExit(1)

    try:
        translations = load_translation_db(args.translations)
    except FileNotFoundError:
        print(f"Error: translations DB not found: {args.translations}", file=sys.stderr)
        raise SystemExit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(2)

    paragraphs = list(iter_paragraph_chunks(source_lines))

    out_source_lines: List[str] = []
    out_target_lines: List[str] = []

    cursor = 0
    for p in paragraphs:
        start = p["start_idx"]
        end = p["end_idx_exclusive"]
        if start < cursor:
            continue

        # Copy non-paragraph scaffolding to both outputs (headings, code/math blocks, blank lines, etc.)
        out_source_lines.extend(source_lines[cursor:start])
        out_target_lines.extend(source_lines[cursor:start])

        chunk_id = p["chunk_id"]
        entry = translations.get(chunk_id)

        # Source paragraph (corrected optional)
        if args.prefer_corrected_source and entry and isinstance(entry.get("source_md"), str) and entry["source_md"].strip():
            src_text = entry["source_md"].rstrip("\n")
            if not ensure_single_paragraph(src_text):
                print(f"Error: {chunk_id}: source_md contains blank lines; must be a single paragraph.", file=sys.stderr)
                raise SystemExit(3)
            if has_block_openers(src_text):
                print(
                    f"Error: {chunk_id}: source_md contains code/math/heading block openers; keep it as a paragraph.",
                    file=sys.stderr,
                )
                raise SystemExit(3)
            src_block = src_text + "\n"
        else:
            src_block = "".join(source_lines[start:end])

        # Target paragraph
        tgt_block: str
        if entry:
            tgt_text = pick_target_text(entry)
        else:
            tgt_text = None

        if tgt_text is None:
            if not args.allow_missing:
                print(f"Error: missing translation for chunk_id {chunk_id}", file=sys.stderr)
                raise SystemExit(4)
            tgt_block = "".join(source_lines[start:end])
        else:
            tgt_text = tgt_text.rstrip("\n")
            if not ensure_single_paragraph(tgt_text):
                print(f"Error: {chunk_id}: target_md contains blank lines; must be a single paragraph.", file=sys.stderr)
                raise SystemExit(3)
            if has_block_openers(tgt_text):
                print(
                    f"Error: {chunk_id}: target_md contains code/math/heading block openers; keep it as a paragraph.",
                    file=sys.stderr,
                )
                raise SystemExit(3)
            tgt_block = tgt_text + "\n"

        if args.annotate:
            marker = f"<!-- chunk_id: {chunk_id} -->\n"
            out_source_lines.append(marker)
            out_target_lines.append(marker)
            # Keep markers as their own paragraph block for later merge tooling.
            out_source_lines.append("\n")
            out_target_lines.append("\n")

        out_source_lines.append(src_block)
        out_target_lines.append(tgt_block)

        cursor = end

    out_source_lines.extend(source_lines[cursor:])
    out_target_lines.extend(source_lines[cursor:])

    with open(args.out_source, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(out_source_lines))

    with open(args.out_target, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(out_target_lines))


if __name__ == "__main__":
    main()
