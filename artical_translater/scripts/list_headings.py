#!/usr/bin/env python3
import argparse
import json
import sys

from md_scan import iter_headings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List Markdown headings with indices and auto section IDs.",
    )
    parser.add_argument("--path", "-p", required=True, help="Path to the Markdown file.")
    parser.add_argument(
        "--format",
        choices=["table", "jsonl"],
        default="table",
        help="Output format (default: table).",
    )
    args = parser.parse_args()

    try:
        with open(args.path, "r", encoding="utf-8") as f:
            headings = list(iter_headings(f))
    except FileNotFoundError:
        print(f"Error: file not found: {args.path}", file=sys.stderr)
        raise SystemExit(1)

    if args.format == "jsonl":
        for h in headings:
            print(json.dumps(h, ensure_ascii=False))
        return

    # table
    print("idx  line  lvl  section_id  title")
    for h in headings:
        print(f"{h['index']:>3}  {h['line']:>4}  {h['level']:>3}  {h['section_id']:>9}  {h['title']}")


if __name__ == "__main__":
    main()

