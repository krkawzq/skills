#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from md_tokens import extract_math_segments, protected_tokens


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def acquire_lock(lock_path: str, timeout_s: float) -> None:
    start = time.time()
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(f"pid={os.getpid()}\n")
                f.write(f"acquired_at={utc_now_iso()}\n")
            return
        except FileExistsError:
            if time.time() - start >= timeout_s:
                raise TimeoutError(f"Timed out waiting for lock: {lock_path}")
            time.sleep(0.05)


def release_lock(lock_path: str) -> None:
    try:
        os.remove(lock_path)
    except FileNotFoundError:
        return


def parse_input(stdin_text: str) -> List[dict]:
    raw = stdin_text.strip()
    if not raw:
        raise ValueError("stdin is empty (expected JSON object / array / JSONL).")

    # 1) JSON array
    if raw.startswith("["):
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("JSON array input must be a list.")
        items = []
        for obj in data:
            if not isinstance(obj, dict):
                raise ValueError("JSON array input must contain objects.")
            items.append(obj)
        return items

    # 2) Single JSON object
    if raw.startswith("{"):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            obj = None
        else:
            if not isinstance(obj, dict):
                raise ValueError("JSON object input must be an object.")
            return [obj]

    # 3) JSONL
    items: List[dict] = []
    for i, line in enumerate(stdin_text.splitlines(), start=1):
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON on line {i}: {e}") from e
        if not isinstance(obj, dict):
            raise ValueError(f"JSONL line {i} must be an object.")
        items.append(obj)

    if not items:
        raise ValueError("No JSON objects found in stdin.")
    return items


def load_chunks_index(chunks_path: str) -> Dict[str, dict]:
    """
    Load chunks JSONL into a dict keyed by chunk_id.

    The chunks file should be produced by list_chunks.py without --no-text so that source_md
    is available for preservation checks.
    """
    index: Dict[str, dict] = {}
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in chunks file at line {line_no}: {e}") from e
            if not isinstance(obj, dict):
                continue
            cid = obj.get("chunk_id")
            if isinstance(cid, str) and cid.strip():
                index[cid.strip()] = obj
    if not index:
        raise ValueError("No chunk_id found in chunks file.")
    return index


def validate_items(
    items: Iterable[dict],
    *,
    require_target_md: bool,
    chunks_index: Optional[Dict[str, dict]],
    protect_links: bool,
    protect_math: bool,
) -> Tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    blank_line_re = re.compile(r"\n\s*\n")
    heading_line_re = re.compile(r"^\s*#{1,6}\s+")

    def has_block_openers(text: str) -> bool:
        for ln in text.replace("\r\n", "\n").split("\n"):
            stripped = ln.lstrip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                return True
            if ln.strip() in ("$$", r"\["):
                return True
            if heading_line_re.match(ln):
                return True
        return False

    for item in items:
        chunk_id = item.get("chunk_id")
        if not isinstance(chunk_id, str) or not chunk_id.strip():
            errors.append("Each item must include non-empty string field: chunk_id")
            continue

        cid = chunk_id.strip()
        target_md = item.get("target_md")
        if require_target_md:
            if not isinstance(target_md, str) or not target_md.strip():
                errors.append(f"{cid}: missing/invalid field target_md (non-empty string required)")
        if isinstance(target_md, str) and blank_line_re.search(target_md.replace("\r\n", "\n").strip()):
            errors.append(f"{cid}: target_md contains blank lines; must be a single paragraph for alignment")
        if isinstance(target_md, str) and target_md.strip() and has_block_openers(target_md):
            errors.append(f"{cid}: target_md contains code/math/heading block openers; keep it as a paragraph chunk")

        if chunks_index is not None and cid not in chunks_index:
            errors.append(f"{cid}: chunk_id not found in --chunks file")
            continue

        source_md = item.get("source_md")
        if source_md is not None and (not isinstance(source_md, str) or not source_md.strip()):
            errors.append(f"{cid}: source_md must be a non-empty string when provided")
            continue
        if isinstance(source_md, str) and blank_line_re.search(source_md.replace("\r\n", "\n").strip()):
            errors.append(f"{cid}: source_md contains blank lines; must be a single paragraph for alignment")
            continue
        if isinstance(source_md, str) and source_md.strip() and has_block_openers(source_md):
            errors.append(f"{cid}: source_md contains code/math/heading block openers; keep it as a paragraph chunk")
            continue

        if chunks_index is None:
            continue

        orig_source = chunks_index[cid].get("source_md")
        if not isinstance(orig_source, str) or not orig_source.strip():
            warnings.append(f"{cid}: chunks record has no source_md; cannot validate preservation for source_md")
            continue

        orig_tokens = protected_tokens(orig_source)
        if protect_links:
            if isinstance(source_md, str):
                corr = protected_tokens(source_md)
                if orig_tokens.md_dests != corr.md_dests:
                    errors.append(f"{cid}: source_md changed Markdown link/image destinations")
                if orig_tokens.html_attrs != corr.html_attrs:
                    errors.append(f"{cid}: source_md changed HTML src/href attributes")
                if orig_tokens.raw_urls and orig_tokens.raw_urls != corr.raw_urls:
                    warnings.append(f"{cid}: source_md changed raw http(s) URLs; verify this is intended")

            if isinstance(target_md, str) and target_md.strip():
                tgt = protected_tokens(target_md)
                if orig_tokens.md_dests != tgt.md_dests:
                    errors.append(f"{cid}: target_md changed Markdown link/image destinations")
                if orig_tokens.html_attrs != tgt.html_attrs:
                    errors.append(f"{cid}: target_md changed HTML src/href attributes")
                if orig_tokens.raw_urls and orig_tokens.raw_urls != tgt.raw_urls:
                    warnings.append(f"{cid}: target_md changed raw http(s) URLs; verify this is intended")

        if protect_math:
            if isinstance(source_md, str) and extract_math_segments(orig_source) != extract_math_segments(source_md):
                errors.append(f"{cid}: source_md changed LaTeX/math segments (protect-math enabled)")
            if isinstance(target_md, str) and extract_math_segments(orig_source) != extract_math_segments(target_md):
                errors.append(f"{cid}: target_md changed LaTeX/math segments (protect-math enabled)")
        else:
            if isinstance(source_md, str) and extract_math_segments(orig_source) != extract_math_segments(source_md):
                warnings.append(f"{cid}: source_md changed LaTeX/math segments; only do this for obvious OCR fixes")
            if isinstance(target_md, str) and extract_math_segments(orig_source) != extract_math_segments(target_md):
                warnings.append(f"{cid}: target_md changed LaTeX/math segments; only do this for obvious OCR fixes")

    return errors, warnings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Append translation entries (JSON/JSONL via stdin) into a JSONL DB with a lock.",
    )
    parser.add_argument("--db", required=True, help="Path to translations JSONL DB.")
    parser.add_argument(
        "--in",
        dest="in_path",
        help="Read JSON/JSONL from this file instead of stdin.",
    )
    parser.add_argument(
        "--chunks",
        help="Chunks JSONL (from list_chunks.py). When provided, validates chunk_id existence and preserves link targets if source_md is present.",
    )
    parser.add_argument(
        "--no-require-target-md",
        action="store_true",
        help="Allow missing/empty target_md (default: require).",
    )
    parser.add_argument(
        "--no-protect-links",
        action="store_true",
        help="Disable link/image destination preservation checks (source_md and target_md).",
    )
    parser.add_argument(
        "--protect-math",
        action="store_true",
        help="Require math segments in source_md to match the original exactly.",
    )
    parser.add_argument(
        "--lock",
        help="Lock file path (default: <db>.lock).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Lock acquire timeout in seconds (default: 30).",
    )
    args = parser.parse_args()

    lock_path = args.lock or f"{args.db}.lock"

    try:
        if args.in_path:
            with open(args.in_path, "r", encoding="utf-8") as f:
                raw_input = f.read()
        else:
            raw_input = sys.stdin.read()

        items = parse_input(raw_input)
        chunks_index = load_chunks_index(args.chunks) if args.chunks else None
        errors, warnings = validate_items(
            items,
            require_target_md=not args.no_require_target_md,
            chunks_index=chunks_index,
            protect_links=not args.no_protect_links,
            protect_math=args.protect_math,
        )
        for w in warnings:
            print(f"Warning: {w}", file=sys.stderr)
        if errors:
            raise ValueError("; ".join(errors))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(2)

    lock_acquired = False
    try:
        acquire_lock(lock_path=lock_path, timeout_s=args.timeout)
        lock_acquired = True
        os.makedirs(os.path.dirname(os.path.abspath(args.db)) or ".", exist_ok=True)
        with open(args.db, "a", encoding="utf-8", newline="\n") as f:
            for item in items:
                enriched = dict(item)
                enriched.setdefault("appended_at", utc_now_iso())
                f.write(json.dumps(enriched, ensure_ascii=False) + "\n")
    except TimeoutError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(3)
    finally:
        if lock_acquired:
            release_lock(lock_path)


if __name__ == "__main__":
    main()
