#!/usr/bin/env python3
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple


INLINE_LINK_START_RE = re.compile(r"!?\[[^\]]*\]\(")

HTML_ATTR_RE = re.compile(
    r"""(?ix)
    \b(?P<attr>src|href)\s*=\s*
    (?P<quote>["'])(?P<value>.*?)(?P=quote)
    """
)


def _find_closing_paren(text: str, start: int) -> Optional[int]:
    """
    Find the index *after* the closing ')' that matches the '(' at `start-1`.

    This is a best-effort parser: handles nested parentheses and quoted titles.
    """
    depth = 0
    in_quote: Optional[str] = None
    i = start
    n = len(text)

    while i < n:
        c = text[i]
        if in_quote:
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == in_quote:
                in_quote = None
            i += 1
            continue

        if c in ("'", '"'):
            in_quote = c
            i += 1
            continue

        if c == "(":
            depth += 1
            i += 1
            continue

        if c == ")":
            if depth == 0:
                return i + 1
            depth -= 1
            i += 1
            continue

        i += 1

    return None


def _parse_link_destination(text: str, start: int) -> Tuple[Optional[str], Optional[int]]:
    """
    Parse a Markdown inline link destination starting at `start` (right after '(').

    Returns (destination, close_pos) where close_pos is the index after the matching ')'.
    """
    i = start
    n = len(text)

    while i < n and text[i].isspace():
        i += 1
    if i >= n:
        return None, None

    # <...> destination form
    if text[i] == "<":
        i += 1
        dest_start = i
        while i < n and text[i] != ">":
            if text[i] == "\\" and i + 1 < n:
                i += 2
                continue
            i += 1
        dest = text[dest_start:i]
        if i < n and text[i] == ">":
            i += 1
        close_pos = _find_closing_paren(text, i)
        return dest.strip(), close_pos

    # Unwrapped destination: parse until whitespace or ')' at depth 0
    dest_start = i
    inner_depth = 0
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            i += 2
            continue
        if c == "(":
            inner_depth += 1
            i += 1
            continue
        if c == ")":
            if inner_depth == 0:
                dest = text[dest_start:i]
                return dest.strip(), i + 1
            inner_depth -= 1
            i += 1
            continue
        if c.isspace() and inner_depth == 0:
            dest = text[dest_start:i]
            close_pos = _find_closing_paren(text, i)
            return dest.strip(), close_pos
        i += 1

    return text[dest_start:].strip(), None


def extract_markdown_link_destinations(md: str) -> List[str]:
    """
    Extract destinations from Markdown inline links and images: [text](dest) / ![alt](dest).

    This is best-effort (CommonMark-ish) and intended for preservation checks.
    """
    dests: List[str] = []

    for match in INLINE_LINK_START_RE.finditer(md):
        open_paren_pos = match.end() - 1  # points at '('
        dest, close_pos = _parse_link_destination(md, open_paren_pos + 1)
        if dest:
            dests.append(dest)

        if close_pos is None:
            continue

    return dests


def extract_html_src_href(md: str) -> List[str]:
    values: List[str] = []
    for m in HTML_ATTR_RE.finditer(md):
        val = m.group("value").strip()
        if val:
            values.append(val)
    return values


RAW_URL_RE = re.compile(r"(?i)\bhttps?://[^\s<>\"]+")


def extract_raw_urls(md: str) -> List[str]:
    return [m.group(0) for m in RAW_URL_RE.finditer(md)]


@dataclass(frozen=True)
class ProtectedTokens:
    md_dests: Counter
    html_attrs: Counter
    raw_urls: Counter


def protected_tokens(md: str) -> ProtectedTokens:
    return ProtectedTokens(
        md_dests=Counter(extract_markdown_link_destinations(md)),
        html_attrs=Counter(extract_html_src_href(md)),
        raw_urls=Counter(extract_raw_urls(md)),
    )


INLINE_MATH_RE = re.compile(r"(?s)(?<!\\)\$(?!\$)(.+?)(?<!\\)\$")
BLOCK_MATH_RE = re.compile(r"(?s)(?<!\\)\$\$(.+?)(?<!\\)\$\$")
PAREN_MATH_RE = re.compile(r"(?s)\\\((.+?)\\\)")
BRACK_MATH_RE = re.compile(r"(?s)\\\[(.+?)\\\]")


def extract_math_segments(md: str) -> List[str]:
    segs: List[str] = []
    for re_ in (BLOCK_MATH_RE, INLINE_MATH_RE, PAREN_MATH_RE, BRACK_MATH_RE):
        for m in re_.finditer(md):
            seg = m.group(1)
            if seg is not None:
                segs.append(seg)
    return segs

