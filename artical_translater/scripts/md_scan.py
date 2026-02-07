#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

HEADER_RE = re.compile(r"^(?P<indent>\s*)(?P<hashes>#{1,6})\s+(?P<title>.*)$")


def fence_delim(line: str) -> Optional[str]:
    stripped = line.lstrip()
    if stripped.startswith("```"):
        return "```"
    if stripped.startswith("~~~"):
        return "~~~"
    return None


@dataclass(frozen=True)
class Section:
    section_id: int
    level: int
    title: str
    path_titles: Tuple[str, ...]
    path_ids: Tuple[int, ...]


class SectionTracker:
    def __init__(self) -> None:
        self._next_id = 1
        self._stack: List[Section] = [
            Section(
                section_id=0,
                level=0,
                title="[Document Root]",
                path_titles=(),
                path_ids=(),
            )
        ]

    def current(self) -> Section:
        return self._stack[-1]

    def push_heading(self, level: int, title: str) -> Section:
        while len(self._stack) > 1 and self._stack[-1].level >= level:
            self._stack.pop()

        parent = self._stack[-1]
        section_id = self._next_id
        self._next_id += 1

        section = Section(
            section_id=section_id,
            level=level,
            title=title,
            path_titles=parent.path_titles + (title,),
            path_ids=parent.path_ids + (section_id,),
        )
        self._stack.append(section)
        return section


def format_chunk_id(section_id: int, para_index_in_section: int) -> str:
    return f"s{section_id:04d}p{para_index_in_section:04d}"


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def iter_headings(lines: Iterable[str]) -> Iterator[dict]:
    """
    Yield headings in document order.

    Heading indices are 1-based.
    Line numbers are 1-based.
    """
    tracker = SectionTracker()
    in_fence = False
    fence = None
    heading_index = 0

    for line_no, line in enumerate(lines, start=1):
        delim = fence_delim(line)
        if delim:
            if not in_fence:
                in_fence = True
                fence = delim
            elif fence == delim:
                in_fence = False
                fence = None
            continue

        if in_fence:
            continue

        match = HEADER_RE.match(line)
        if not match:
            continue

        heading_index += 1
        level = len(match.group("hashes"))
        title = match.group("title").strip()

        section = tracker.push_heading(level=level, title=title)
        yield {
            "index": heading_index,
            "line": line_no,
            "level": level,
            "title": title,
            "section_id": section.section_id,
            "section_path": list(section.path_titles),
            "section_path_ids": list(section.path_ids),
        }


def iter_paragraph_chunks(lines: List[str]) -> Iterator[dict]:
    """
    Yield paragraph chunks with stable (section_id, para_index_in_section)-based IDs.

    Paragraph boundaries:
    - separated by blank lines
    - headings terminate current paragraph
    - code-fence blocks are excluded and terminate current paragraph

    Returned positions:
    - start_idx / end_idx_exclusive are 0-based line indices into `lines`
    """
    tracker = SectionTracker()
    in_fence = False
    fence = None

    per_section_para_count: Dict[int, int] = {}

    para_lines: List[str] = []
    para_start_idx: Optional[int] = None

    def flush(end_idx_exclusive: int) -> Optional[dict]:
        nonlocal para_lines, para_start_idx
        if not para_lines or para_start_idx is None:
            para_lines = []
            para_start_idx = None
            return None

        if not any(line.strip() for line in para_lines):
            para_lines = []
            para_start_idx = None
            return None

        section = tracker.current()
        per_section_para_count[section.section_id] = per_section_para_count.get(section.section_id, 0) + 1
        para_index = per_section_para_count[section.section_id]

        source_md = "".join(para_lines).rstrip("\n")
        chunk_id = format_chunk_id(section.section_id, para_index)

        payload = {
            "chunk_id": chunk_id,
            "section_id": section.section_id,
            "section_level": section.level,
            "section_title": section.title,
            "section_path": list(section.path_titles),
            "section_path_ids": list(section.path_ids),
            "para_index": para_index,
            "char_count": len(source_md),
            "source_md": source_md,
            "source_sha1": sha1_text(source_md),
            "start_idx": para_start_idx,
            "end_idx_exclusive": end_idx_exclusive,
        }

        para_lines = []
        para_start_idx = None
        return payload

    for idx, line in enumerate(lines):
        delim = fence_delim(line)
        if delim:
            if not in_fence:
                item = flush(end_idx_exclusive=idx)
                if item:
                    yield item
                in_fence = True
                fence = delim
            elif fence == delim:
                in_fence = False
                fence = None
            continue

        if in_fence:
            continue

        match = HEADER_RE.match(line)
        if match:
            item = flush(end_idx_exclusive=idx)
            if item:
                yield item

            level = len(match.group("hashes"))
            title = match.group("title").strip()
            tracker.push_heading(level=level, title=title)
            continue

        if line.strip() == "":
            item = flush(end_idx_exclusive=idx)
            if item:
                yield item
            continue

        if para_start_idx is None:
            para_start_idx = idx
        para_lines.append(line)

    item = flush(end_idx_exclusive=len(lines))
    if item:
        yield item

