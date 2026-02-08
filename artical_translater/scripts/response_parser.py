#!/usr/bin/env python3
"""
Response parser for structured AI translation output.

Extracts content from ```markdown translated``` and ```markdown corrected```
code blocks, plus meta-info fields from the AI response.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TranslationResponse:
    """Parsed structured response from a sub-translator agent."""

    # The translated text (extracted from ```markdown translated``` block)
    translated_md: Optional[str] = None

    # Corrected source text (extracted from ```markdown corrected``` block)
    corrected_source_md: Optional[str] = None

    # Analysis text (everything before the first code block)
    analysis: Optional[str] = None

    # Meta-info fields
    difficulty: Optional[str] = None       # easy, medium, hard
    potential_issues: Optional[str] = None
    confidence: Optional[str] = None       # high, medium, low
    checker_bypass: Optional[str] = None   # checker误报说明
    notes: Optional[str] = None

    # Whether the AI flagged a validator issue as not its fault
    blames_source: bool = False

    # Raw response (for debugging)
    raw_response: str = ""

    # Parse errors (if any)
    parse_errors: List[str] = field(default_factory=list)


# Regex patterns for extracting markdown code blocks
# Matches ```markdown translated ... ``` and ```markdown corrected ... ```
_BLOCK_RE = re.compile(
    r"```markdown\s+(translated|corrected)\s*\n(.*?)```",
    re.DOTALL
)

# Meta-info patterns
_DIFFICULTY_RE = re.compile(r"DIFFICULTY:\s*\[?(easy|medium|hard)\]?", re.IGNORECASE)
_CONFIDENCE_RE = re.compile(r"CONFIDENCE:\s*\[?(high|medium|low)\]?", re.IGNORECASE)
_ISSUES_RE = re.compile(r"POTENTIAL_ISSUES:\s*\[?(.*?)\]?\s*$", re.IGNORECASE | re.MULTILINE)
_BYPASS_RE = re.compile(r"CHECKER_BYPASS:\s*\[?(.*?)\]?\s*$", re.IGNORECASE | re.MULTILINE)
_NOTES_RE = re.compile(r"NOTES:\s*\[?(.*?)\]?\s*$", re.IGNORECASE | re.MULTILINE)


def parse_translation_response(raw: str) -> TranslationResponse:
    """
    Parse a structured AI response into a TranslationResponse object.

    Expected format:
        ### Analysis
        ... analysis text ...

        ```markdown translated
        ... translated text ...
        ```

        ```markdown corrected    (optional)
        ... corrected source ...
        ```

        DIFFICULTY: [easy|medium|hard]
        POTENTIAL_ISSUES: [...]
        CONFIDENCE: [high|medium|low]
        CHECKER_BYPASS: [...]
        NOTES: [...]
    """
    result = TranslationResponse(raw_response=raw)

    # Extract code blocks
    blocks = _BLOCK_RE.findall(raw)

    for block_type, content in blocks:
        content = content.strip()
        if block_type.lower() == "translated":
            result.translated_md = content
        elif block_type.lower() == "corrected":
            result.corrected_source_md = content

    # If no translated block found, record error (强制结构化格式)
    if result.translated_md is None:
        result.parse_errors.append(
            "No ```markdown translated``` block found in response"
        )

    # Extract analysis (text before first code block)
    first_block_match = _BLOCK_RE.search(raw)
    if first_block_match:
        result.analysis = raw[:first_block_match.start()].strip()

    # Extract meta-info
    m = _DIFFICULTY_RE.search(raw)
    if m:
        result.difficulty = m.group(1).lower()

    m = _CONFIDENCE_RE.search(raw)
    if m:
        result.confidence = m.group(1).lower()

    m = _ISSUES_RE.search(raw)
    if m:
        result.potential_issues = m.group(1).strip()

    m = _BYPASS_RE.search(raw)
    if m:
        result.checker_bypass = m.group(1).strip()
        # If bypass is not "none", set blames_source
        if result.checker_bypass and result.checker_bypass.lower() != "none":
            result.blames_source = True

    m = _NOTES_RE.search(raw)
    if m:
        result.notes = m.group(1).strip()

    # Check if AI blames source for issues (additional heuristic)
    if result.notes and any(
        phrase in result.notes.lower()
        for phrase in ["source has", "source issue", "not my fault", "source error",
                       "original has", "ocr error in source"]
    ):
        result.blames_source = True

    return result


def extract_translated_md(raw: str) -> Optional[str]:
    """
    Simple extraction: get just the translated markdown text.

    Returns None if no code block found (强制结构化格式).
    """
    parsed = parse_translation_response(raw)
    return parsed.translated_md

