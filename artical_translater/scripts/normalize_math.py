#!/usr/bin/env python3
"""
AI-powered LaTeX formula standardization tool.

Preprocesses Markdown files to fix common OCR issues in LaTeX formulas:
- Extra spaces inside formulas
- Wrong delimiters
- Unicode math symbols that should be LaTeX commands

Usage:
    python normalize_math.py --input paper.md --output paper.fixed.md

    python normalize_math.py --chunks work/chunks.jsonl --output work/chunks.fixed.jsonl

    python normalize_math.py --chunks work/chunks.jsonl --output work/chunks.fixed.jsonl \\
        --config config.yaml --ai --concurrency 50
"""

import argparse
import asyncio
import aiohttp
import json
import re
import sys
from pathlib import Path
from typing import Dict, List
import yaml
from tqdm.asyncio import tqdm

from shared import load_config
from prompts import build_math_normalize_prompt
from response_parser import parse_translation_response


# ---------------------------------------------------------------------------
# Rule-based pre-pass (fast, no API needed)
# ---------------------------------------------------------------------------

# Unicode -> LaTeX mapping
UNICODE_TO_LATEX = {
    '\u222b': '\\int',      # ∫
    '\u00d7': '\\times',    # ×
    '\u2211': '\\sum',      # ∑
    '\u220f': '\\prod',     # ∏
    '\u221a': '\\sqrt',     # √
    '\u2264': '\\leq',      # ≤
    '\u2265': '\\geq',      # ≥
    '\u2260': '\\neq',      # ≠
    '\u221e': '\\infty',    # ∞
    '\u2208': '\\in',       # ∈
    '\u2209': '\\notin',    # ∉
    '\u2282': '\\subset',   # ⊂
    '\u2283': '\\supset',   # ⊃
    '\u222a': '\\cup',      # ∪
    '\u2229': '\\cap',      # ∩
    '\u2192': '\\rightarrow',  # →
    '\u2190': '\\leftarrow',   # ←
    '\u21d2': '\\Rightarrow',  # ⇒
    '\u21d0': '\\Leftarrow',   # ⇐
    '\u2203': '\\exists',   # ∃
    '\u2200': '\\forall',   # ∀
    '\u03b1': '\\alpha',    # α
    '\u03b2': '\\beta',     # β
    '\u03b3': '\\gamma',    # γ
    '\u03b4': '\\delta',    # δ
    '\u03b5': '\\epsilon',  # ε
    '\u03b8': '\\theta',    # θ
    '\u03bb': '\\lambda',   # λ
    '\u03bc': '\\mu',       # μ
    '\u03c0': '\\pi',       # π
    '\u03c3': '\\sigma',    # σ
    '\u03c6': '\\phi',      # φ
    '\u03c9': '\\omega',    # ω
}

# Regex for inline and display math
INLINE_MATH_RE = re.compile(r'(?<!\$)\$(?!\$)(.*?)(?<!\$)\$(?!\$)', re.DOTALL)
DISPLAY_MATH_RE = re.compile(r'\$\$(.*?)\$\$', re.DOTALL)


def rule_based_fix(text: str) -> str:
    """
    Apply deterministic rule-based fixes to math formulas.
    This is fast and does not require API calls.
    """
    # Replace Unicode math symbols globally
    for unicode_char, latex_cmd in UNICODE_TO_LATEX.items():
        text = text.replace(unicode_char, latex_cmd)

    # Fix spacing inside inline math: $ x ^ 2 $ -> $x^2$
    def fix_inline_spacing(match):
        inner = match.group(1)
        # Remove spaces around ^, _, {, }
        inner = re.sub(r'\s*\^\s*', '^', inner)
        inner = re.sub(r'\s*_\s*', '_', inner)
        inner = re.sub(r'\s*\{\s*', '{', inner)
        inner = re.sub(r'\s*\}\s*', '}', inner)
        # Remove leading/trailing spaces
        inner = inner.strip()
        return '$' + inner + '$'

    def fix_display_spacing(match):
        inner = match.group(1)
        inner = re.sub(r'\s*\^\s*', '^', inner)
        inner = re.sub(r'\s*_\s*', '_', inner)
        inner = re.sub(r'\s*\{\s*', '{', inner)
        inner = re.sub(r'\s*\}\s*', '}', inner)
        inner = inner.strip()
        return '$$' + inner + '$$'

    text = DISPLAY_MATH_RE.sub(fix_display_spacing, text)
    text = INLINE_MATH_RE.sub(fix_inline_spacing, text)

    return text


# ---------------------------------------------------------------------------
# AI-based pass (for complex cases)
# ---------------------------------------------------------------------------

async def ai_normalize_chunk(
    session: aiohttp.ClientSession,
    text: str,
    config: Dict,
    semaphore: asyncio.Semaphore,
) -> str:
    """Use AI to normalize formulas in a text chunk."""
    async with semaphore:
        url = config['api']['base_url'] + '/chat/completions'
        headers = {
            "Authorization": "Bearer " + config['api']['api_key'],
            "Content-Type": "application/json"
        }

        system_prompt = build_math_normalize_prompt()

        payload = {
            "model": config['api']['model'],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Fix the formulas in this text:\\n\\n" + text}
            ],
            "temperature": 0.1
        }

        timeout = aiohttp.ClientTimeout(total=config['translation']['timeout'])

        try:
            async with session.post(url, json=payload, headers=headers, timeout=timeout) as response:
                if response.status == 200:
                    data = await response.json()
                    raw = data['choices'][0]['message']['content'].strip()
                    parsed = parse_translation_response(raw)
                    if parsed.corrected_source_md:
                        return parsed.corrected_source_md
                    # Fallback: return raw
                    return raw
                else:
                    # On error, return original text unchanged
                    return text
        except Exception:
            # On any error, return original text
            return text


# ---------------------------------------------------------------------------
# Processing modes
# ---------------------------------------------------------------------------

def process_markdown_file(input_path: str) -> str:
    """Process a full markdown file with rule-based fixes."""
    with open(input_path, 'r', encoding='utf-8') as f:
        text = f.read()
    return rule_based_fix(text)


async def process_chunks_jsonl(
    input_path: str,
    config: Dict,
    use_ai: bool = False,
    concurrency: int = 50,
) -> List[Dict]:
    """Process chunks JSONL, fixing formulas in each chunk's source_md."""
    chunks = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                chunks.append(json.loads(line))

    if not use_ai:
        # Rule-based only
        for chunk in chunks:
            if 'source_md' in chunk:
                chunk['source_md'] = rule_based_fix(chunk['source_md'])
        return chunks

    # AI-based processing
    semaphore = asyncio.Semaphore(concurrency)
    async with aiohttp.ClientSession() as session:
        tasks = []
        for chunk in chunks:
            if 'source_md' in chunk:
                tasks.append(
                    ai_normalize_chunk(session, chunk['source_md'], config, semaphore)
                )

        results = []
        for coro in tqdm.as_completed(tasks, total=len(tasks), desc="Normalizing"):
            results.append(await coro)

        for chunk, result in zip(chunks, results):
            if 'source_md' in chunk:
                chunk['source_md'] = result

    return chunks


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="AI-powered LaTeX formula standardization tool"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", help="Input Markdown file")
    group.add_argument("--chunks", help="Input chunks JSONL file")

    parser.add_argument("--output", required=True, help="Output file path")
    parser.add_argument("--config", help="Config YAML (required for AI mode)")
    parser.add_argument(
        "--ai", action="store_true",
        help="Use AI for complex formula fixes (requires --config)"
    )
    parser.add_argument(
        "--concurrency", type=int, default=50,
        help="Concurrency for AI mode (default: 50)"
    )

    args = parser.parse_args()

    if args.ai and not args.config:
        print("Error: --config required for AI mode", file=sys.stderr)
        sys.exit(1)

    config = None
    if args.config:
        config = load_config(args.config)

    if args.input:
        # Process markdown file (rule-based only for full files)
        result = process_markdown_file(args.input)
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(result)
        print("Done: " + args.output)

    elif args.chunks:
        # Process chunks JSONL
        chunks = asyncio.run(
            process_chunks_jsonl(args.chunks, config, use_ai=args.ai, concurrency=args.concurrency)
        )
        with open(args.output, 'w', encoding='utf-8') as f:
            for chunk in chunks:
                f.write(json.dumps(chunk, ensure_ascii=False) + '\n')
        print("Done: " + str(len(chunks)) + " chunks -> " + args.output)


if __name__ == "__main__":
    main()



