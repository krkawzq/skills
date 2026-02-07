#!/usr/bin/env python3
import argparse
import json
import re
import sys
from typing import Dict, Optional

from md_scan import HEADER_RE, fence_delim


NUMBERING_RE = re.compile(r"^(?P<num>\d+(?:\.\d+)*)(?:\.)?\s+")


def clamp_level(level: int) -> int:
    return max(1, min(6, level))


def infer_level_from_numbering(title: str, base_level: int) -> Optional[int]:
    match = NUMBERING_RE.match(title)
    if not match:
        return None
    num = match.group("num")
    depth = num.count(".") + 1
    return clamp_level(base_level + depth - 1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize Markdown heading levels (useful for OCR-flattened headings).",
    )
    parser.add_argument("--in", dest="in_path", required=True, help="Input Markdown path.")
    parser.add_argument("--out", dest="out_path", required=True, help="Output Markdown path.")
    parser.add_argument(
        "--mode",
        choices=["numbering", "map"],
        default="numbering",
        help="Normalization mode (default: numbering).",
    )
    parser.add_argument(
        "--base-level",
        type=int,
        default=1,
        help="Base heading level for numbering mode (default: 1).",
    )
    parser.add_argument(
        "--unmatched",
        choices=["keep", "base"],
        default="keep",
        help="For headings without numbering, keep original level or force base level (default: keep).",
    )
    parser.add_argument(
        "--strip-numbering",
        action="store_true",
        help="Strip the numbering prefix from the title in numbering mode.",
    )
    parser.add_argument(
        "--map",
        dest="map_path",
        help="JSON file mapping heading index (1-based) -> new level (required for mode=map).",
    )
    args = parser.parse_args()

    if args.mode == "map" and not args.map_path:
        print("Error: --map is required when --mode map", file=sys.stderr)
        raise SystemExit(2)

    index_to_level: Dict[int, int] = {}
    if args.mode == "map":
        try:
            with open(args.map_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError:
            print(f"Error: map file not found: {args.map_path}", file=sys.stderr)
            raise SystemExit(2)

        if not isinstance(raw, dict):
            print("Error: map JSON must be an object (e.g. {\"1\": 1, \"2\": 2})", file=sys.stderr)
            raise SystemExit(2)

        for k, v in raw.items():
            try:
                idx = int(k)
            except ValueError:
                print(f"Error: invalid heading index key in map: {k!r}", file=sys.stderr)
                raise SystemExit(2)
            if not isinstance(v, int):
                print(f"Error: map value for index {k!r} must be int, got {type(v).__name__}", file=sys.stderr)
                raise SystemExit(2)
            index_to_level[idx] = clamp_level(v)

    try:
        with open(args.in_path, "r", encoding="utf-8") as f:
            in_lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: input file not found: {args.in_path}", file=sys.stderr)
        raise SystemExit(1)

    out_lines = []
    in_fence = False
    fence = None
    heading_index = 0

    for line in in_lines:
        delim = fence_delim(line)
        if delim:
            if not in_fence:
                in_fence = True
                fence = delim
            elif fence == delim:
                in_fence = False
                fence = None
            out_lines.append(line)
            continue

        if in_fence:
            out_lines.append(line)
            continue

        match = HEADER_RE.match(line)
        if not match:
            out_lines.append(line)
            continue

        heading_index += 1
        indent = match.group("indent")
        hashes = match.group("hashes")
        old_level = len(hashes)
        title = match.group("title").rstrip("\n")
        title_stripped = title.strip()

        new_level: Optional[int] = None
        new_title = title_stripped

        if args.mode == "map":
            new_level = index_to_level.get(heading_index)
        else:
            new_level = infer_level_from_numbering(title_stripped, base_level=args.base_level)
            if new_level is None and args.unmatched == "base":
                new_level = clamp_level(args.base_level)

            if args.strip_numbering:
                m = NUMBERING_RE.match(title_stripped)
                if m:
                    new_title = title_stripped[m.end() :].strip()

        if new_level is None:
            new_level = old_level

        out_lines.append(f"{indent}{'#' * clamp_level(new_level)} {new_title}\n")

    with open(args.out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(out_lines))


if __name__ == "__main__":
    main()

