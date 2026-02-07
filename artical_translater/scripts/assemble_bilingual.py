#!/usr/bin/env python3
import argparse
import json
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
            translations[chunk_id] = obj  # last entry wins
    return translations


def to_blockquote(md_text: str) -> List[str]:
    lines = md_text.splitlines()
    if not lines:
        return ["> \n"]
    out: List[str] = []
    for line in lines:
        if line.strip() == "":
            out.append(">\n")
        else:
            out.append(f"> {line}\n")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assemble bilingual Markdown by inserting translations after each paragraph chunk.",
    )
    parser.add_argument("--path", "-p", required=True, help="Path to the source Markdown file.")
    parser.add_argument("--translations", required=True, help="Path to translations JSONL DB.")
    parser.add_argument(
        "--out",
        "-o",
        required=True,
        help="Output Markdown path, or '-' for stdout.",
    )
    parser.add_argument(
        "--prefer-corrected-source",
        action="store_true",
        help="If an entry provides 'source_md', replace the OCR paragraph with it.",
    )
    parser.add_argument(
        "--annotate",
        action="store_true",
        help="Insert HTML comments with chunk_id before translation blocks.",
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

    out_lines: List[str] = []
    cursor = 0
    for p in paragraphs:
        start = p["start_idx"]
        end = p["end_idx_exclusive"]
        if start < cursor:
            # Should not happen; indicates a scanner bug.
            continue

        out_lines.extend(source_lines[cursor:start])

        chunk_id = p["chunk_id"]
        entry: Optional[dict] = translations.get(chunk_id)

        # Source paragraph text (original or corrected)
        if args.prefer_corrected_source and entry and isinstance(entry.get("source_md"), str) and entry["source_md"].strip():
            corrected = entry["source_md"].rstrip("\n") + "\n"
            out_lines.append(corrected)
        else:
            out_lines.extend(source_lines[start:end])

        if entry:
            target_md = None
            for key in ("target_md", "target_text", "translation"):
                val = entry.get(key)
                if isinstance(val, str) and val.strip():
                    target_md = val
                    break

            if target_md is not None:
                out_lines.append("\n")
                if args.annotate:
                    out_lines.append(f"<!-- chunk_id: {chunk_id} -->\n")
                out_lines.extend(to_blockquote(target_md))
                out_lines.append("\n")

        cursor = end

    out_lines.extend(source_lines[cursor:])

    output_text = "".join(out_lines)
    if args.out == "-":
        sys.stdout.write(output_text)
        return

    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(output_text)


if __name__ == "__main__":
    main()

