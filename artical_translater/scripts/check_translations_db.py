#!/usr/bin/env python3
import argparse
import json
import sys
from typing import Dict, Iterable, List, Optional, Set, Tuple


def iter_jsonl(path: str) -> Iterable[Tuple[int, dict]]:
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except json.JSONDecodeError as e:
                raise ValueError(f"invalid JSON at line {line_no}: {e}") from e
            if isinstance(obj, dict):
                yield line_no, obj


def load_chunk_ids(chunks_path: str) -> Set[str]:
    chunk_ids: Set[str] = set()
    for line_no, obj in iter_jsonl(chunks_path):
        cid = obj.get("chunk_id")
        if isinstance(cid, str) and cid.strip():
            chunk_ids.add(cid.strip())
    if not chunk_ids:
        raise ValueError("no chunk_id found in chunks file")
    return chunk_ids


def load_latest_translations(db_path: str) -> Dict[str, dict]:
    latest: Dict[str, dict] = {}
    for line_no, obj in iter_jsonl(db_path):
        cid = obj.get("chunk_id")
        if isinstance(cid, str) and cid.strip():
            latest[cid.strip()] = obj  # last wins
    return latest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check translations JSONL DB coverage against a chunks JSONL file.",
    )
    parser.add_argument("--chunks", required=True, help="Chunks JSONL (from list_chunks.py).")
    parser.add_argument("--db", required=True, help="Translations JSONL DB.")
    parser.add_argument(
        "--require-target-md",
        action="store_true",
        help="Treat entries missing/empty target_md as missing (recommended).",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )
    args = parser.parse_args()

    try:
        chunk_ids = load_chunk_ids(args.chunks)
        latest = load_latest_translations(args.db)
    except FileNotFoundError as e:
        print(f"Error: file not found: {e.filename}", file=sys.stderr)
        raise SystemExit(2)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(2)

    missing: List[str] = []
    present: List[str] = []
    bad: List[str] = []

    for cid in sorted(chunk_ids):
        entry = latest.get(cid)
        if entry is None:
            missing.append(cid)
            continue
        if args.require_target_md:
            target_md = entry.get("target_md")
            if not isinstance(target_md, str) or not target_md.strip():
                bad.append(cid)
                continue
        present.append(cid)

    extra = sorted([cid for cid in latest.keys() if cid not in chunk_ids])

    if args.format == "json":
        payload = {
            "total_chunks": len(chunk_ids),
            "present": len(present),
            "missing": missing,
            "bad": bad,
            "extra": extra,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        raise SystemExit(0 if (not missing and not bad) else 1)

    # text
    print(f"total_chunks: {len(chunk_ids)}")
    print(f"present:      {len(present)}")
    print(f"missing:      {len(missing)}")
    if args.require_target_md:
        print(f"bad:          {len(bad)}  (missing/empty target_md)")
    print(f"extra:        {len(extra)}  (in DB but not in chunks)")

    if missing:
        print("\nMissing chunk_id:")
        for cid in missing[:50]:
            print(f"  - {cid}")
        if len(missing) > 50:
            print(f"  ... and {len(missing) - 50} more")

    if bad:
        print("\nBad chunk_id:")
        for cid in bad[:50]:
            print(f"  - {cid}")
        if len(bad) > 50:
            print(f"  ... and {len(bad) - 50} more")

    if extra:
        print("\nExtra chunk_id:")
        for cid in extra[:50]:
            print(f"  - {cid}")
        if len(extra) > 50:
            print(f"  ... and {len(extra) - 50} more")

    raise SystemExit(0 if (not missing and not bad) else 1)


if __name__ == "__main__":
    main()

