#!/usr/bin/env python3
import argparse
import json
import re
import sys
from typing import Any, Dict, Optional, Tuple

from md_tokens import extract_math_segments, protected_tokens


def load_json_object(raw: str) -> Dict[str, Any]:
    raw = raw.strip()
    if not raw:
        raise ValueError("empty input")

    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError(f"expected a JSON object, got {type(obj).__name__}")
    return obj


def find_chunk_record(chunks_path: str, chunk_id: str) -> Optional[dict]:
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except json.JSONDecodeError as e:
                raise ValueError(f"invalid JSON in chunks file at line {line_no}: {e}") from e
            if not isinstance(obj, dict):
                continue
            if obj.get("chunk_id") == chunk_id:
                return obj
    return None


def validate_entry(
    entry: dict,
    chunk: Optional[dict],
    *,
    require_target_md: bool,
    protect_links: bool,
    protect_math: bool,
    json_mode: bool = False,
) -> Tuple[list[str], list[str], list[dict], list[dict]]:
    """
    Validate a translation entry.

    Returns:
        (errors, warnings, structured_errors, structured_warnings)
        - errors: list of error strings (for text output)
        - warnings: list of warning strings (for text output)
        - structured_errors: list of error dicts (for JSON output)
        - structured_warnings: list of warning dicts (for JSON output)
    """
    errors: list[str] = []
    warnings: list[str] = []
    structured_errors: list[dict] = []
    structured_warnings: list[dict] = []

    chunk_id = entry.get("chunk_id")
    if not isinstance(chunk_id, str) or not chunk_id.strip():
        errors.append("missing/invalid field: chunk_id (non-empty string)")
        structured_errors.append({
            "type": "MISSING_FIELD",
            "field": "chunk_id",
            "severity": "error",
            "message": "missing/invalid field: chunk_id (non-empty string)",
            "suggestion": "Ensure chunk_id is a non-empty string"
        })

    target_md = entry.get("target_md")
    if require_target_md:
        if not isinstance(target_md, str) or not target_md.strip():
            errors.append("missing/invalid field: target_md (non-empty string)")
            structured_errors.append({
                "type": "MISSING_FIELD",
                "field": "target_md",
                "severity": "error",
                "message": "missing/invalid field: target_md (non-empty string)",
                "suggestion": "Ensure target_md is a non-empty string"
            })

    source_md = entry.get("source_md")
    if source_md is not None and (not isinstance(source_md, str) or not source_md.strip()):
        errors.append("field source_md must be a non-empty string when provided")
        structured_errors.append({
            "type": "MISSING_FIELD",
            "field": "source_md",
            "severity": "error",
            "message": "field source_md must be a non-empty string when provided",
            "suggestion": "Ensure source_md is a non-empty string when provided"
        })

    # Alignment rule: each chunk must stay a single paragraph (no blank-line separated blocks).
    blank_line_re = re.compile(r"\n\s*\n")
    heading_line_re = re.compile(r"^\s*#{1,6}\s+")

    def check_block_openers(field: str, text: str) -> None:
        for ln in text.replace("\r\n", "\n").split("\n"):
            stripped = ln.lstrip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                errors.append(f"{field} contains a code-fence line; chunks must not introduce code blocks")
                structured_errors.append({
                    "type": "BLOCK_STRUCTURE",
                    "field": field,
                    "severity": "error",
                    "message": f"{field} contains a code-fence line; chunks must not introduce code blocks",
                    "suggestion": "Remove code fences (```) from your translation"
                })
                return
            if ln.strip() in ("$$", r"\["):
                errors.append(f"{field} contains a math-fence line; chunks must not introduce math blocks")
                structured_errors.append({
                    "type": "BLOCK_STRUCTURE",
                    "field": field,
                    "severity": "error",
                    "message": f"{field} contains a math-fence line; chunks must not introduce math blocks",
                    "suggestion": "Remove math fences ($$) from your translation"
                })
                return
            if heading_line_re.match(ln):
                errors.append(f"{field} contains a heading line; chunks must not introduce headings")
                structured_errors.append({
                    "type": "BLOCK_STRUCTURE",
                    "field": field,
                    "severity": "error",
                    "message": f"{field} contains a heading line; chunks must not introduce headings",
                    "suggestion": "Remove heading markers (#) from your translation"
                })
                return

    if isinstance(target_md, str) and blank_line_re.search(target_md.replace("\r\n", "\n").strip()):
        errors.append("target_md contains blank lines; must be a single paragraph for alignment")
        structured_errors.append({
            "type": "BLANK_LINES",
            "field": "target_md",
            "severity": "error",
            "message": "target_md contains blank lines; must be a single paragraph",
            "suggestion": "Remove all blank lines (double newlines) from your translation"
        })
    if isinstance(target_md, str) and target_md.strip():
        check_block_openers("target_md", target_md)
    if isinstance(source_md, str) and blank_line_re.search(source_md.replace("\r\n", "\n").strip()):
        errors.append("source_md contains blank lines; must be a single paragraph for alignment")
        structured_errors.append({
            "type": "BLANK_LINES",
            "field": "source_md",
            "severity": "error",
            "message": "source_md contains blank lines; must be a single paragraph",
            "suggestion": "Remove all blank lines (double newlines) from source_md"
        })
    if isinstance(source_md, str) and source_md.strip():
        check_block_openers("source_md", source_md)

    if chunk is not None:
        orig_source = chunk.get("source_md")
        if not isinstance(orig_source, str) or not orig_source.strip():
            warnings.append("chunks record has no source_md; cannot validate link preservation")
            structured_warnings.append({
                "type": "CHUNK_VALIDATION",
                "field": "source_md",
                "severity": "warning",
                "message": "chunks record has no source_md; cannot validate link preservation"
            })
            orig_source = None

        if orig_source is not None:
            orig_tokens = protected_tokens(orig_source)

            if isinstance(source_md, str):
                if protect_links:
                    corr = protected_tokens(source_md)
                    if orig_tokens.md_dests != corr.md_dests:
                        errors.append(
                            "source_md changed Markdown link/image destinations; keep all link targets unchanged"
                        )
                        structured_errors.append({
                            "type": "LINK_PRESERVATION",
                            "field": "source_md",
                            "severity": "error",
                            "message": "source_md changed Markdown link/image destinations",
                            "original_links": list(orig_tokens.md_dests),
                            "modified_links": list(corr.md_dests),
                            "suggestion": "Keep all link destinations exactly as they appear in the original"
                        })
                    if orig_tokens.html_attrs != corr.html_attrs:
                        errors.append("source_md changed HTML src/href attributes; keep them unchanged")
                        structured_errors.append({
                            "type": "LINK_PRESERVATION",
                            "field": "source_md",
                            "severity": "error",
                            "message": "source_md changed HTML src/href attributes",
                            "original_links": list(orig_tokens.html_attrs),
                            "modified_links": list(corr.html_attrs),
                            "suggestion": "Keep all HTML src/href attributes unchanged"
                        })
                    if orig_tokens.raw_urls and orig_tokens.raw_urls != corr.raw_urls:
                        warnings.append(
                            "source_md changed raw http(s) URLs (not in Markdown links); verify this is intended"
                        )
                        structured_warnings.append({
                            "type": "LINK_PRESERVATION",
                            "field": "source_md",
                            "severity": "warning",
                            "message": "source_md changed raw http(s) URLs (not in Markdown links)"
                        })

                if protect_math:
                    orig_math = extract_math_segments(orig_source)
                    source_math = extract_math_segments(source_md)
                    if orig_math != source_math:
                        errors.append(
                            "source_md changed LaTeX/math segments; keep math unchanged in protect-math mode"
                        )
                        structured_errors.append({
                            "type": "MATH_PRESERVATION",
                            "field": "source_md",
                            "severity": "error",
                            "message": "source_md changed LaTeX/math segments",
                            "original_math": orig_math,
                            "modified_math": source_math,
                            "suggestion": "Keep all LaTeX formulas exactly as they appear in the original"
                        })
                else:
                    orig_math = extract_math_segments(orig_source)
                    source_math = extract_math_segments(source_md)
                    if orig_math != source_math:
                        warnings.append("source_md changed LaTeX/math segments; only do this for obvious OCR fixes")
                        structured_warnings.append({
                            "type": "MATH_CHANGED",
                            "field": "source_md",
                            "severity": "warning",
                            "message": "source_md changed LaTeX/math segments (OCR fix?)"
                        })

            if isinstance(target_md, str) and target_md.strip():
                if protect_links:
                    tgt = protected_tokens(target_md)
                    if orig_tokens.md_dests != tgt.md_dests:
                        errors.append(
                            "target_md changed Markdown link/image destinations; keep all link targets unchanged"
                        )
                        structured_errors.append({
                            "type": "LINK_PRESERVATION",
                            "field": "target_md",
                            "severity": "error",
                            "message": "target_md changed Markdown link/image destinations",
                            "original_links": list(orig_tokens.md_dests),
                            "modified_links": list(tgt.md_dests),
                            "suggestion": "Keep all URLs unchanged, only translate the link text"
                        })
                    if orig_tokens.html_attrs != tgt.html_attrs:
                        errors.append("target_md changed HTML src/href attributes; keep them unchanged")
                        structured_errors.append({
                            "type": "LINK_PRESERVATION",
                            "field": "target_md",
                            "severity": "error",
                            "message": "target_md changed HTML src/href attributes",
                            "original_links": list(orig_tokens.html_attrs),
                            "modified_links": list(tgt.html_attrs),
                            "suggestion": "Keep all HTML src/href attributes unchanged"
                        })
                    if orig_tokens.raw_urls and orig_tokens.raw_urls != tgt.raw_urls:
                        warnings.append(
                            "target_md changed raw http(s) URLs (not in Markdown links); verify this is intended"
                        )
                        structured_warnings.append({
                            "type": "LINK_PRESERVATION",
                            "field": "target_md",
                            "severity": "warning",
                            "message": "target_md changed raw http(s) URLs (not in Markdown links)"
                        })

                if protect_math:
                    orig_math = extract_math_segments(orig_source)
                    target_math = extract_math_segments(target_md)
                    if orig_math != target_math:
                        errors.append(
                            "target_md changed LaTeX/math segments; keep math unchanged in protect-math mode"
                        )
                        structured_errors.append({
                            "type": "MATH_PRESERVATION",
                            "field": "target_md",
                            "severity": "error",
                            "message": "target_md changed LaTeX/math segments",
                            "original_math": orig_math,
                            "modified_math": target_math,
                            "suggestion": "Keep all LaTeX formulas exactly as they appear in source_md"
                        })
                else:
                    orig_math = extract_math_segments(orig_source)
                    target_math = extract_math_segments(target_md)
                    if orig_math != target_math:
                        warnings.append("target_md changed LaTeX/math segments; only do this for obvious OCR fixes")
                        structured_warnings.append({
                            "type": "MATH_CHANGED",
                            "field": "target_md",
                            "severity": "warning",
                            "message": "target_md changed LaTeX/math segments (OCR fix?)"
                        })

    return errors, warnings, structured_errors, structured_warnings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a translation entry JSON object for the multi-agent workflow.",
    )
    parser.add_argument(
        "--in",
        dest="in_path",
        help="Path to a JSON file containing a single entry object. If omitted, read stdin.",
    )
    parser.add_argument(
        "--chunks",
        help="Path to chunks JSONL (from list_chunks.py) to validate chunk_id and preserve tokens for source_md.",
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
        help="Require math segments (source_md and target_md) to match the original exactly.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON format for AI consumption (instead of human-readable text).",
    )
    args = parser.parse_args()

    try:
        if args.in_path:
            raw = open(args.in_path, "r", encoding="utf-8").read()
        else:
            raw = sys.stdin.read()
        entry = load_json_object(raw)
    except Exception as e:
        print(f"Error: invalid entry input: {e}", file=sys.stderr)
        raise SystemExit(2)

    chunk = None
    if args.chunks:
        chunk_id = entry.get("chunk_id")
        if isinstance(chunk_id, str) and chunk_id.strip():
            try:
                chunk = find_chunk_record(args.chunks, chunk_id.strip())
            except Exception as e:
                print(f"Error: failed reading chunks file: {e}", file=sys.stderr)
                raise SystemExit(2)
        else:
            chunk = None

        if chunk is None:
            if args.json:
                # JSON output for chunk not found
                result = {
                    "status": "error",
                    "valid": False,
                    "errors": [{
                        "type": "CHUNK_NOT_FOUND",
                        "field": "chunk_id",
                        "severity": "error",
                        "message": "chunk_id not found in --chunks file",
                        "suggestion": "Verify the chunk_id exists in the chunks file"
                    }],
                    "warnings": []
                }
                print(json.dumps(result, ensure_ascii=False, indent=2))
                raise SystemExit(3)
            else:
                print("Error: chunk_id not found in --chunks file", file=sys.stderr)
                raise SystemExit(3)

    errors, warnings, structured_errors, structured_warnings = validate_entry(
        entry,
        chunk,
        require_target_md=not args.no_require_target_md,
        protect_links=not args.no_protect_links,
        protect_math=args.protect_math,
        json_mode=args.json,
    )

    # Output results
    if args.json:
        # JSON output mode
        result = {
            "status": "error" if errors else ("warning" if warnings else "success"),
            "valid": len(errors) == 0,
            "errors": structured_errors,
            "warnings": structured_warnings
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if errors:
            raise SystemExit(1)
    else:
        # Text output mode (backward compatible)
        for w in warnings:
            print(f"Warning: {w}", file=sys.stderr)

        if errors:
            for e in errors:
                print(f"Error: {e}", file=sys.stderr)
            raise SystemExit(1)

        print("OK")


if __name__ == "__main__":
    main()
