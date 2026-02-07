#!/usr/bin/env python3
import argparse
import re
import sys
from typing import Optional

from md_scan import iter_headings


def select_heading(headings: list[dict], args: argparse.Namespace) -> Optional[dict]:
    if args.index is not None:
        for h in headings:
            if h["index"] == args.index:
                return h
        return None

    if args.title is not None:
        for h in headings:
            if h["title"] == args.title:
                return h
        return None

    if args.regex is not None:
        pattern = re.compile(args.regex)
        for h in headings:
            if pattern.search(h["title"]):
                return h
        return None

    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract a Markdown section by heading index/title/regex.",
    )
    parser.add_argument("--path", "-p", required=True, help="Path to the Markdown file.")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--index", type=int, help="Heading index from list_headings.py (1-based).")
    group.add_argument("--title", help="Exact heading title match.")
    group.add_argument("--regex", help="Regex to match heading title (first match wins).")

    parser.add_argument(
        "--include-heading",
        action="store_true",
        help="Include the heading line itself (default).",
        default=True,
    )
    parser.add_argument(
        "--exclude-heading",
        action="store_false",
        dest="include_heading",
        help="Exclude the heading line (content only).",
    )
    args = parser.parse_args()

    try:
        with open(args.path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: file not found: {args.path}", file=sys.stderr)
        raise SystemExit(1)

    headings = list(iter_headings(lines))
    heading = select_heading(headings, args)
    if not heading:
        print("Error: section not found.", file=sys.stderr)
        raise SystemExit(2)

    start_line_1 = heading["line"]  # 1-based
    level = heading["level"]

    end_line_1 = len(lines) + 1  # exclusive, 1-based
    for h in headings:
        if h["line"] <= start_line_1:
            continue
        if h["level"] <= level:
            end_line_1 = h["line"]
            break

    start_idx = start_line_1 - 1
    if not args.include_heading:
        start_idx += 1

    end_idx_exclusive = end_line_1 - 1
    if start_idx < 0:
        start_idx = 0
    if end_idx_exclusive > len(lines):
        end_idx_exclusive = len(lines)

    sys.stdout.write("".join(lines[start_idx:end_idx_exclusive]))


if __name__ == "__main__":
    main()

