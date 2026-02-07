#!/usr/bin/env python3
import argparse
import json
import sys

from md_scan import iter_paragraph_chunks


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List paragraph chunks (with chunk_id) for multi-agent translation.",
    )
    parser.add_argument(
        "--path", "-p", required=True, help="Path to the Markdown file."
    )
    parser.add_argument(
        "--format",
        choices=["jsonl"],
        default="jsonl",
        help="Output format (default: jsonl).",
    )
    parser.add_argument(
        "--section-id",
        type=int,
        help="Filter chunks by section_id.",
    )
    parser.add_argument(
        "--include-descendants",
        action="store_true",
        help="When used with --section-id, include chunks under descendant sections too.",
    )
    parser.add_argument(
        "--min-chars",
        type=int,
        default=1,
        help="Only emit chunks with at least this many characters (default: 1).",
    )
    parser.add_argument(
        "--no-text",
        action="store_true",
        help="Omit source_md from output (metadata only).",
    )
    args = parser.parse_args()

    try:
        with open(args.path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: file not found: {args.path}", file=sys.stderr)
        raise SystemExit(1)

    for item in iter_paragraph_chunks(lines):
        if item["char_count"] < args.min_chars:
            continue

        if args.section_id is not None:
            if args.include_descendants:
                if args.section_id not in item["section_path_ids"]:
                    continue
            else:
                if item["section_id"] != args.section_id:
                    continue

        if args.no_text:
            item = dict(item)
            item.pop("source_md", None)

        sys.stdout.buffer.write(json.dumps(item, ensure_ascii=False).encode("utf-8"))
        sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
