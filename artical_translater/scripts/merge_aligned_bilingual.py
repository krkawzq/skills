#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

from md_tokens import extract_math_segments, protected_tokens


HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.*)$")
IMG_MD_RE = re.compile(r"^\s*!\[[^\]]*\]\(([^)]+)\)\s*$")
IMG_HTML_RE = re.compile(r"""(?ix)^\s*<img\b[^>]*\bsrc\s*=\s*(["'])(.*?)\1[^>]*>\s*$""")


def fence_delim(line: str) -> Optional[str]:
    stripped = line.lstrip()
    if stripped.startswith("```"):
        return "```"
    if stripped.startswith("~~~"):
        return "~~~"
    return None


@dataclass(frozen=True)
class Block:
    kind: str  # heading|paragraph|code|math
    text: str


def parse_blocks(lines: List[str]) -> List[Block]:
    blocks: List[Block] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        if line.strip() == "":
            i += 1
            continue

        delim = fence_delim(line)
        if delim:
            start = i
            i += 1
            while i < n:
                if lines[i].lstrip().startswith(delim):
                    i += 1
                    break
                i += 1
            blocks.append(Block(kind="code", text="".join(lines[start:i])))
            continue

        if line.strip() == "$$":
            start = i
            i += 1
            while i < n and lines[i].strip() != "$$":
                i += 1
            if i < n and lines[i].strip() == "$$":
                i += 1
                blocks.append(Block(kind="math", text="".join(lines[start:i])))
                continue
            # Unclosed math fence; treat as paragraph fallback.
            i = start

        if line.strip() == r"\[":
            start = i
            i += 1
            while i < n and lines[i].strip() != r"\]":
                i += 1
            if i < n and lines[i].strip() == r"\]":
                i += 1
                blocks.append(Block(kind="math", text="".join(lines[start:i])))
                continue
            i = start

        m = HEADING_RE.match(line)
        if m:
            blocks.append(Block(kind="heading", text=line))
            i += 1
            continue

        # Paragraph: until blank line or start of protected block.
        start = i
        i += 1
        while i < n:
            if lines[i].strip() == "":
                break
            if fence_delim(lines[i]) is not None:
                break
            if lines[i].strip() in ("$$", r"\["):
                break
            if HEADING_RE.match(lines[i]) is not None:
                break
            i += 1

        blocks.append(Block(kind="paragraph", text="".join(lines[start:i])))

    return blocks


def normalize_text(text: str) -> str:
    return "\n".join([ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]).strip()


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


def heading_title(line: str) -> Optional[str]:
    m = HEADING_RE.match(line)
    if not m:
        return None
    return m.group(2).strip()


def single_image_dest(paragraph_text: str) -> Optional[str]:
    lines = [ln for ln in paragraph_text.replace("\r\n", "\n").split("\n") if ln.strip()]
    if len(lines) != 1:
        return None
    line = lines[0]
    m = IMG_MD_RE.match(line)
    if m:
        return m.group(1).strip()
    m = IMG_HTML_RE.match(line)
    if m:
        return m.group(2).strip()
    return None


def strip_image_lines(text: str, dest: str) -> str:
    out_lines: List[str] = []
    for ln in text.replace("\r\n", "\n").split("\n"):
        m = IMG_MD_RE.match(ln)
        if m and m.group(1).strip() == dest:
            continue
        m = IMG_HTML_RE.match(ln)
        if m and m.group(2).strip() == dest:
            continue
        out_lines.append(ln)
    # Trim leading/trailing blank lines after stripping.
    while out_lines and out_lines[0].strip() == "":
        out_lines.pop(0)
    while out_lines and out_lines[-1].strip() == "":
        out_lines.pop()
    return "\n".join(out_lines).strip()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge two aligned Markdown files into a bilingual (source + blockquoted target) document.",
    )
    parser.add_argument("--source", required=True, help="Corrected source Markdown path (English).")
    parser.add_argument("--target", required=True, help="Target-language Markdown path (Chinese).")
    parser.add_argument("--out", "-o", required=True, help="Output bilingual Markdown path, or '-' for stdout.")
    parser.add_argument(
        "--no-strict",
        action="store_true",
        help="Do not fail if protected blocks differ; keep source blocks and warn instead.",
    )
    parser.add_argument(
        "--no-protect-links",
        action="store_true",
        help="Disable link/image destination equality checks between source and target blocks.",
    )
    parser.add_argument(
        "--protect-math",
        action="store_true",
        help="Require math segments inside paragraph blocks to match exactly between source and target.",
    )
    args = parser.parse_args()

    strict = not args.no_strict
    protect_links = not args.no_protect_links

    try:
        source_lines = open(args.source, "r", encoding="utf-8").readlines()
    except FileNotFoundError:
        print(f"Error: file not found: {args.source}", file=sys.stderr)
        raise SystemExit(1)

    try:
        target_lines = open(args.target, "r", encoding="utf-8").readlines()
    except FileNotFoundError:
        print(f"Error: file not found: {args.target}", file=sys.stderr)
        raise SystemExit(1)

    src_blocks = parse_blocks(source_lines)
    tgt_blocks = parse_blocks(target_lines)

    if len(src_blocks) != len(tgt_blocks):
        msg = f"Error: block count mismatch (source={len(src_blocks)}, target={len(tgt_blocks)}). Files may not be aligned."
        print(msg, file=sys.stderr)
        raise SystemExit(2)

    out_lines: List[str] = []
    for idx, (sb, tb) in enumerate(zip(src_blocks, tgt_blocks), start=1):
        if sb.kind != tb.kind:
            print(
                f"Error: block kind mismatch at #{idx} (source={sb.kind}, target={tb.kind}).",
                file=sys.stderr,
            )
            raise SystemExit(2)

        s_norm = normalize_text(sb.text)
        t_norm = normalize_text(tb.text)

        if sb.kind in ("code", "math"):
            if s_norm != t_norm:
                msg = f"Protected block differs at #{idx} ({sb.kind}). Keeping source."
                if strict:
                    print(f"Error: {msg}", file=sys.stderr)
                    raise SystemExit(3)
                print(f"Warning: {msg}", file=sys.stderr)

            out_lines.append(sb.text if sb.text.endswith("\n") else sb.text + "\n")
            if not out_lines[-1].endswith("\n\n"):
                out_lines.append("\n")
            continue

        if sb.kind == "heading":
            out_lines.append(sb.text if sb.text.endswith("\n") else sb.text + "\n")
            if s_norm != t_norm:
                title = heading_title(tb.text) or t_norm
                out_lines.extend(to_blockquote(title))
            out_lines.append("\n")
            continue

        # paragraph
        if s_norm == t_norm:
            out_lines.append(sb.text if sb.text.endswith("\n") else sb.text + "\n")
            out_lines.append("\n")
            continue

        if protect_links:
            s_tok = protected_tokens(sb.text)
            t_tok = protected_tokens(tb.text)
            if s_tok.md_dests != t_tok.md_dests:
                msg = f"link/image destinations differ at paragraph block #{idx}"
                if strict:
                    print(f"Error: {msg}", file=sys.stderr)
                    raise SystemExit(3)
                print(f"Warning: {msg}", file=sys.stderr)
            if s_tok.html_attrs != t_tok.html_attrs:
                msg = f"HTML src/href attributes differ at paragraph block #{idx}"
                if strict:
                    print(f"Error: {msg}", file=sys.stderr)
                    raise SystemExit(3)
                print(f"Warning: {msg}", file=sys.stderr)

        if args.protect_math:
            if extract_math_segments(sb.text) != extract_math_segments(tb.text):
                msg = f"math segments differ at paragraph block #{idx}"
                if strict:
                    print(f"Error: {msg}", file=sys.stderr)
                    raise SystemExit(3)
                print(f"Warning: {msg}", file=sys.stderr)

        out_lines.append(sb.text if sb.text.endswith("\n") else sb.text + "\n")

        # Special handling: single-image paragraph should not duplicate the image line.
        img_dest = single_image_dest(sb.text)
        if img_dest:
            stripped = strip_image_lines(tb.text, img_dest)
            if stripped:
                out_lines.append("\n")
                out_lines.extend(to_blockquote(stripped))
                out_lines.append("\n")
            else:
                out_lines.append("\n")
            continue

        out_lines.append("\n")
        out_lines.extend(to_blockquote(tb.text.rstrip("\n")))
        out_lines.append("\n")

    output = "".join(out_lines)
    if args.out == "-":
        sys.stdout.write(output)
        return

    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(output)


if __name__ == "__main__":
    main()
