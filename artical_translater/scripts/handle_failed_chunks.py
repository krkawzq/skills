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
import sys
from pathlib import Path
from typing import Dict, List

# Import from shared modules
from shared import load_config, source_md_is_safe, sanitize_target_md
from prompts import build_retry_system_prompt, build_retry_user_prompt, format_errors_for_ai
from response_parser import parse_translation_response


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

    # Use prompts module to build prompts
    system_prompt = build_retry_system_prompt(
        target_language=config['translation']['target_language'],
        enable_source_correction=config.get('translation', {}).get('enable_source_correction', False),
        enable_math_fixing=config.get('translation', {}).get('enable_math_fixing', True),
        guidance_prompt=None,
    )

    user_prompt = build_retry_user_prompt(chunk['source_md'], all_errors)
    user_prompt += "\n\nVALIDATION HISTORY:\n" + format_validation_history(validation_history)
    user_prompt += "\n\nThis chunk has FAILED validation multiple times. Please analyze carefully."

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
            raw = data['choices'][0]['message']['content']
            # Parse response
            parsed = parse_translation_response(raw)
            if parsed.translated_md:
                return parsed.translated_md
            # Fallback to raw response
            return raw
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
                # Try sanitization
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
    parser.add_argument("--failed-chunks", required=True, help="Path to failed_chunks.json file")
    parser.add_argument("--chunks", required=True, help="Path to chunks.jsonl file")
    parser.add_argument("--output", required=True, help="Path to output translations.jsonl file")
    parser.add_argument("--config", required=True, help="Path to config.yaml file")

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


