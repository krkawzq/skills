#!/usr/bin/env python3
"""
Failed Chunks Handler for Article Translator

This script handles chunks that failed all validation iterations by using
more detailed prompts and main agent analysis.

Usage:
    python handle_failed_chunks.py \\
        --failed-chunks work/failed_chunks.json \\
        --chunks work/chunks.jsonl \\
        --output work/translations.jsonl \\
        --config config.yaml
"""

import argparse
import asyncio
import aiohttp
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List
import yaml


def load_config(config_path: str) -> Dict:
    """Load configuration from YAML file"""
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    env_key = os.environ.get('OPENAI_API_KEY')
    if env_key:
        config['api']['api_key'] = env_key
    if not config['api'].get('api_key'):
        raise ValueError("API key not set. Set it in config.yaml or OPENAI_API_KEY environment variable")
    return config


def load_failed_chunks(failed_chunks_path: str) -> List[Dict]:
    """Load failed chunks with validation history"""
    with open(failed_chunks_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_chunk_by_id(chunks_path: str, chunk_id: str) -> Dict:
    """Load a specific chunk from chunks.jsonl"""
    with open(chunks_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                chunk = json.loads(line)
                if chunk['chunk_id'] == chunk_id:
                    return chunk
    raise ValueError(f"Chunk {chunk_id} not found in {chunks_path}")


def format_validation_history(history: List[Dict]) -> str:
    """Format validation history for display"""
    lines = []
    for entry in history:
        iteration = entry['iteration']
        result = entry['result']
        lines.append(f"\nAttempt {iteration}:")
        lines.append(f"  Status: {result['status']}")
        if result.get('errors'):
            lines.append("  Errors:")
            for error in result['errors']:
                lines.append(f"    - {error.get('type', 'UNKNOWN')}: {error.get('message', 'No message')}")
    return "\n".join(lines)


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


def source_md_is_safe(text: str) -> bool:
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


async def translate_with_detailed_prompt(
    session: aiohttp.ClientSession,
    chunk: Dict,
    validation_history: List[Dict],
    config: Dict
) -> str:
    """Translate chunk with detailed prompt including full validation history"""
    url = f"{config['api']['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config['api']['api_key']}",
        "Content-Type": "application/json"
    }

    # Build comprehensive error summary
    all_errors = []
    for entry in validation_history:
        if entry['result'].get('errors'):
            all_errors.extend(entry['result']['errors'])

    # Deduplicate errors by type
    error_types = {}
    for error in all_errors:
        error_type = error.get('type', 'UNKNOWN')
        if error_type not in error_types:
            error_types[error_type] = error

    error_summary = []
    for error_type, error in error_types.items():
        error_summary.append(f"- {error_type}: {error.get('message', 'No message')}")
        if error.get('suggestion'):
            error_summary.append(f"  Suggestion: {error['suggestion']}")
        if error.get('original_math'):
            error_summary.append(f"  Original math: {error['original_math']}")
        if error.get('original_links'):
            error_summary.append(f"  Original links: {error['original_links']}")

    system_prompt = f"""You are translating an academic paper from English to {config['translation']['target_language']}.

This chunk has FAILED validation {len(validation_history)} times. Please analyze the errors carefully and provide a correct translation.

CRITICAL RULES:
1. Preserve ALL LaTeX formulas EXACTLY as-is (e.g., $x^2$, $$\\int f(x)dx$$)
2. Preserve ALL code blocks EXACTLY as-is
3. Preserve ALL links and URLs EXACTLY as-is (only translate link text, not destinations)
4. Do NOT add blank lines within paragraphs
5. Do NOT introduce headings (#), code fences (```), or math fences ($$)
6. Translate naturally while maintaining technical accuracy

Output ONLY the translated text, nothing else."""

    user_prompt = f"""ORIGINAL TEXT:
{chunk['source_md']}

PREVIOUS VALIDATION ERRORS:
{chr(10).join(error_summary)}

VALIDATION HISTORY:
{format_validation_history(validation_history)}

Please provide a corrected translation that addresses ALL the errors above."""

    payload = {
        "model": config['api']['model'],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.1  # Lower temperature for more careful translation
    }

    timeout = aiohttp.ClientTimeout(total=config['translation']['timeout'])

    async with session.post(url, json=payload, headers=headers, timeout=timeout) as response:
        if response.status == 200:
            data = await response.json()
            return data['choices'][0]['message']['content'].strip()
        else:
            error_text = await response.text()
            raise Exception(f"API error {response.status}: {error_text}")


async def process_failed_chunk(
    session: aiohttp.ClientSession,
    failed_chunk: Dict,
    chunks_path: str,
    output_path: str,
    config: Dict,
    scripts_dir: Path
) -> Dict:
    """Process a single failed chunk with detailed prompt"""
    chunk_id = failed_chunk['chunk_id']
    validation_history = failed_chunk['validation_history']

    print(f"\nProcessing failed chunk: {chunk_id}")
    print(f"Previous attempts: {len(validation_history)}")

    # Load original chunk
    chunk = load_chunk_by_id(chunks_path, chunk_id)

    # Translate with detailed prompt
    try:
        target_md = await translate_with_detailed_prompt(
            session, chunk, validation_history, config
        )

        # Create entry
        entry = {
            "chunk_id": chunk_id,
            "target_md": target_md
        }
        if source_md_is_safe(chunk.get('source_md', '')):
            entry["source_md"] = chunk['source_md']

        # Validate
        from translate_concurrent import validate_entry_json, append_entry

        validation_result = validate_entry_json(entry, scripts_dir, chunks_path)

        if validation_result['valid']:
            # Success! Append to database
            if append_entry(entry, output_path, chunks_path, scripts_dir):
                print(f"[SUCCESS] Successfully translated and validated {chunk_id}")
                return {"status": "success", "chunk_id": chunk_id}
            else:
                print(f"[FAILED] Validation passed but append failed for {chunk_id}")
                return {"status": "append_failed", "chunk_id": chunk_id}
        else:
            error_types = [e.get('type') for e in validation_result.get('errors', [])]
            if any(t in ("BLOCK_STRUCTURE", "BLANK_LINES") for t in error_types):
                # Try a sanitization pass to remove disallowed block openers/blank lines.
                entry["target_md"] = sanitize_target_md(entry["target_md"])
                validation_result = validate_entry_json(entry, scripts_dir, chunks_path)
                if validation_result['valid']:
                    if append_entry(entry, output_path, chunks_path, scripts_dir):
                        print(f"[SUCCESS] Sanitized and validated {chunk_id}")
                        return {"status": "success", "chunk_id": chunk_id}
                    else:
                        print(f"[FAILED] Validation passed but append failed for {chunk_id}")
                        return {"status": "append_failed", "chunk_id": chunk_id}

            print(f"[FAILED] Still failing validation for {chunk_id}")
            print(f"  Errors: {error_types}")
            return {
                "status": "validation_failed",
                "chunk_id": chunk_id,
                "errors": validation_result['errors']
            }

    except Exception as e:
        print(f"[ERROR] Error processing {chunk_id}: {str(e)}")
        return {"status": "error", "chunk_id": chunk_id, "error": str(e)}


async def process_all_failed_chunks(
    failed_chunks: List[Dict],
    chunks_path: str,
    output_path: str,
    config: Dict,
    scripts_dir: Path
) -> Dict:
    """Process all failed chunks"""
    results = {
        "success": 0,
        "validation_failed": 0,
        "append_failed": 0,
        "error": 0,
        "still_failing": []
    }

    async with aiohttp.ClientSession() as session:
        for failed_chunk in failed_chunks:
            result = await process_failed_chunk(
                session, failed_chunk, chunks_path, output_path, config, scripts_dir
            )

            if result['status'] == 'success':
                results['success'] += 1
            elif result['status'] == 'validation_failed':
                results['validation_failed'] += 1
                results['still_failing'].append(result)
            elif result['status'] == 'append_failed':
                results['append_failed'] += 1
            else:
                results['error'] += 1

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Handle chunks that failed all validation iterations"
    )
    parser.add_argument(
        "--failed-chunks",
        required=True,
        help="Path to failed_chunks.json file"
    )
    parser.add_argument(
        "--chunks",
        required=True,
        help="Path to chunks.jsonl file"
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to output translations.jsonl file"
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to config.yaml file"
    )

    args = parser.parse_args()

    # Load configuration
    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"Error loading config: {e}", file=sys.stderr)
        sys.exit(1)

    # Load failed chunks
    try:
        failed_chunks = load_failed_chunks(args.failed_chunks)
        print(f"Loaded {len(failed_chunks)} failed chunks")
    except Exception as e:
        print(f"Error loading failed chunks: {e}", file=sys.stderr)
        sys.exit(1)

    if not failed_chunks:
        print("No failed chunks to process!")
        sys.exit(0)

    # Get scripts directory
    scripts_dir = Path(__file__).parent

    # Process failed chunks
    print("\n" + "="*60)
    print("PROCESSING FAILED CHUNKS WITH DETAILED PROMPTS")
    print("="*60)

    try:
        results = asyncio.run(process_all_failed_chunks(
            failed_chunks,
            args.chunks,
            args.output,
            config,
            scripts_dir
        ))
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)

    # Print summary
    print("\n" + "="*60)
    print("FAILED CHUNKS PROCESSING COMPLETE")
    print("="*60)
    print(f"Total failed chunks:  {len(failed_chunks)}")
    print(f"Successfully fixed:   {results['success']}")
    print(f"Still failing:        {results['validation_failed']}")
    print(f"Append failed:        {results['append_failed']}")
    print(f"Errors:               {results['error']}")
    print("="*60)

    # Save still-failing chunks
    if results['still_failing']:
        still_failing_path = Path(args.failed_chunks).parent / "still_failing_chunks.json"
        with open(still_failing_path, 'w', encoding='utf-8') as f:
            json.dump(results['still_failing'], f, ensure_ascii=False, indent=2)
        print(f"\nChunks still failing saved to: {still_failing_path}")
        print("These may require manual review and translation.")

    if results['validation_failed'] > 0 or results['error'] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
