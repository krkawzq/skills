#!/usr/bin/env python3
"""
Shared utilities for the Article Translator framework.

Consolidates duplicated code from translate_concurrent.py and handle_failed_chunks.py.
"""

import json
import os
import re
from typing import Dict, List, Set
import yaml


def load_config(config_path: str) -> Dict:
    """Load configuration from YAML file."""
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    # Override API key from environment if set
    env_key = os.environ.get('OPENAI_API_KEY')
    if env_key:
        config['api']['api_key'] = env_key

    # Validate required fields
    if not config.get('api', {}).get('api_key'):
        raise ValueError(
            "API key not set. Set it in config.yaml or OPENAI_API_KEY environment variable"
        )

    return config


def source_md_is_safe(text: str) -> bool:
    """Check if source_md can be included without violating block rules."""
    if not isinstance(text, str):
        return False
    if re.search(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        return False
    heading_line_re = re.compile(r"^\s*#{1,6}\s+")
    for ln in text.replace("\r\n", "\n").split("\n"):
        stripped = ln.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            return False
        if ln.strip() in ("$$", r"\["):
            return False
        if heading_line_re.match(ln):
            return False
    return True


def load_chunks(chunks_path: str) -> List[Dict]:
    """Load chunks from JSONL file."""
    chunks = []
    with open(chunks_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                chunks.append(json.loads(line))
    return chunks


def load_existing_translations(output_path: str) -> Set[str]:
    """Load already-translated chunk IDs from output file."""
    if not os.path.exists(output_path):
        return set()

    translated_ids = set()
    with open(output_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                entry = json.loads(line)
                translated_ids.add(entry['chunk_id'])

    return translated_ids


def sanitize_target_md(text: str) -> str:
    """Remove block openers and blank lines to satisfy paragraph-only constraints."""
    lines = text.replace("\r\n", "\n").split("\n")
    cleaned: List[str] = []
    for ln in lines:
        stripped = ln.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            continue
        if ln.strip() in ("$$", r"\[", r"\]"):
            continue
        if stripped.startswith("#"):
            # heading marker
            continue
        if ln.strip() == "":
            continue
        cleaned.append(ln.strip())
    return "\n".join(cleaned).strip()

