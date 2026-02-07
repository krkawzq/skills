#!/usr/bin/env python3
"""
High-Concurrency Translation Script for Article Translator

This script replaces the subagent-based translation approach with direct
async API calls for much faster translation (5-10x speedup).

Usage:
    python translate_concurrent.py --chunks work/chunks.jsonl \\
                                   --output work/translations.jsonl \\
                                   --config config.yaml \\
                                   --resume

Features:
- 100 concurrent API requests (configurable)
- Automatic retry with exponential backoff
- Resume support (skip already-translated chunks)
- Real-time progress tracking
- Validation and append in real-time
- Works with any OpenAI-compatible API
"""

import asyncio
import aiohttp
import json
import os
import re
import sys
import argparse
import time
from pathlib import Path
from typing import Dict, List, Optional, Set
import yaml
from tqdm.asyncio import tqdm


class TranslationError(Exception):
    """Base exception for translation errors"""
    pass


class RateLimitError(TranslationError):
    """Raised when API rate limit is hit"""
    pass


class APIError(TranslationError):
    """Raised when API returns an error"""
    pass


class RetryExhausted(TranslationError):
    """Raised when API retries are exhausted"""
    pass


def load_config(config_path: str) -> Dict:
    """Load configuration from YAML file"""
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    # Override API key from environment if set
    env_key = os.environ.get('OPENAI_API_KEY')
    if env_key:
        config['api']['api_key'] = env_key

    # Validate required fields
    if not config['api']['api_key']:
        raise ValueError("API key not set. Set it in config.yaml or OPENAI_API_KEY environment variable")

    return config


def load_chunks(chunks_path: str) -> List[Dict]:
    """Load chunks from JSONL file"""
    chunks = []
    with open(chunks_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                chunks.append(json.loads(line))
    return chunks


def load_existing_translations(output_path: str) -> Set[str]:
    """Load already-translated chunk IDs from output file"""
    if not os.path.exists(output_path):
        return set()

    translated_ids = set()
    with open(output_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                entry = json.loads(line)
                translated_ids.add(entry['chunk_id'])

    return translated_ids


async def call_translation_api(
    session: aiohttp.ClientSession,
    chunk: Dict,
    config: Dict
) -> str:
    """Make async API call to translate one chunk"""
    url = f"{config['api']['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config['api']['api_key']}",
        "Content-Type": "application/json"
    }

    # Format system prompt with target language
    system_prompt = config['system_prompt'].format(
        target_language=config['translation']['target_language']
    )

    payload = {
        "model": config['api']['model'],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Translate this paragraph:\n\n{chunk['source_md']}"}
        ],
        "temperature": 0.3
    }

    timeout = aiohttp.ClientTimeout(total=config['translation']['timeout'])

    try:
        async with session.post(url, json=payload, headers=headers, timeout=timeout) as response:
            if response.status == 200:
                data = await response.json()
                return data['choices'][0]['message']['content'].strip()
            elif response.status == 429:
                # Rate limit - will be retried
                raise RateLimitError(f"Rate limit hit for chunk {chunk['chunk_id']}")
            else:
                error_text = await response.text()
                raise APIError(f"API error {response.status} for chunk {chunk['chunk_id']}: {error_text}")
    except asyncio.TimeoutError:
        raise APIError(f"Timeout for chunk {chunk['chunk_id']}")
    except aiohttp.ClientError as e:
        raise APIError(f"Network error for chunk {chunk['chunk_id']}: {str(e)}")


async def call_translation_api_with_custom_prompt(
    session: aiohttp.ClientSession,
    system_prompt: str,
    user_prompt: str,
    config: Dict
) -> str:
    """Make async API call with custom prompts (for retry with feedback)"""
    url = f"{config['api']['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config['api']['api_key']}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": config['api']['model'],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.3
    }

    timeout = aiohttp.ClientTimeout(total=config['translation']['timeout'])

    try:
        async with session.post(url, json=payload, headers=headers, timeout=timeout) as response:
            if response.status == 200:
                data = await response.json()
                return data['choices'][0]['message']['content'].strip()
            elif response.status == 429:
                raise RateLimitError("Rate limit hit")
            else:
                error_text = await response.text()
                raise APIError(f"API error {response.status}: {error_text}")
    except asyncio.TimeoutError:
        raise APIError("Timeout")
    except aiohttp.ClientError as e:
        raise APIError(f"Network error: {str(e)}")


async def call_translation_with_retries(
    session: aiohttp.ClientSession,
    chunk: Dict,
    config: Dict,
    *,
    system_prompt: Optional[str] = None,
    user_prompt: Optional[str] = None
) -> str:
    """Call translation API with retry + exponential backoff (config-driven)."""
    max_retries = config.get('translation', {}).get('max_retries', 3)
    retry_delay = config.get('translation', {}).get('retry_delay', 1)

    attempt = 0
    while True:
        try:
            if system_prompt is None or user_prompt is None:
                return await call_translation_api(session, chunk, config)
            return await call_translation_api_with_custom_prompt(
                session, system_prompt, user_prompt, config
            )
        except (RateLimitError, APIError) as e:
            attempt += 1
            if attempt >= max_retries:
                raise RetryExhausted(f"Failed after {max_retries} attempts: {e}") from e
            backoff = retry_delay * (2 ** (attempt - 1))
            await asyncio.sleep(backoff)


async def translate_chunk_with_validation_loop(
    session: aiohttp.ClientSession,
    chunk: Dict,
    config: Dict,
    semaphore: asyncio.Semaphore,
    chunks_path: str,
    scripts_dir: Path,
    max_iterations: int = 3
) -> tuple:
    """
    Translate a chunk with iterative validation-retry loop.

    Returns:
        (entry, validation_history) where:
        - entry: Final translation entry (None if all attempts failed)
        - validation_history: List of validation results for each attempt
    """
    validation_history = []
    previous_errors = []

    for iteration in range(1, max_iterations + 1):
        async with semaphore:
            try:
                # Attempt translation
                if iteration == 1:
                    # Initial translation
                    target_md = await call_translation_with_retries(session, chunk, config)
                else:
                    # Retry with validation feedback
                    system_prompt, user_prompt = create_retry_prompt(chunk, config, previous_errors)
                    target_md = await call_translation_with_retries(
                        session,
                        chunk,
                        config,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt
                    )

                # Create entry
                entry = {
                    "chunk_id": chunk['chunk_id'],
                    "target_md": target_md
                }
                if source_md_is_safe(chunk.get('source_md', '')):
                    entry["source_md"] = chunk['source_md']

                # Validate with JSON output
                validation_result = validate_entry_json(entry, scripts_dir, chunks_path)
                validation_history.append({
                    "iteration": iteration,
                    "result": validation_result
                })

                if validation_result['valid']:
                    # Success!
                    return (entry, validation_history)

                # Failed - prepare feedback for next iteration
                previous_errors = validation_result['errors']

            except RetryExhausted as e:
                # API error - record and continue to next iteration
                validation_history.append({
                    "iteration": iteration,
                    "result": {
                        "status": "error",
                        "valid": False,
                        "errors": [{
                            "type": "API_ERROR",
                            "message": str(e),
                            "suggestion": "Retry the translation"
                        }],
                        "warnings": []
                    }
                })
                # Don't update previous_errors for API errors
                continue

    # All iterations exhausted
    return (None, validation_history)


async def translate_chunk_with_retry(
    session: aiohttp.ClientSession,
    chunk: Dict,
    config: Dict,
    semaphore: asyncio.Semaphore
) -> Dict:
    """Translate a chunk with config-driven retry logic"""
    async with semaphore:
        target_md = await call_translation_with_retries(session, chunk, config)

    entry = {
        "chunk_id": chunk['chunk_id'],
        "target_md": target_md
    }
    if source_md_is_safe(chunk.get('source_md', '')):
        entry["source_md"] = chunk['source_md']

    return entry


def validate_entry(entry: Dict, scripts_dir: Path, chunks_path: str) -> bool:
    """Validate translation entry using check_translation_entry.py"""
    import subprocess

    # Write entry to temp file
    temp_file = scripts_dir.parent / "work" / f"temp_{entry['chunk_id']}.json"
    temp_file.parent.mkdir(exist_ok=True)

    with open(temp_file, 'w', encoding='utf-8') as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)

    # Run validation script with chunks parameter
    check_script = scripts_dir / "check_translation_entry.py"
    result = subprocess.run(
        [sys.executable, str(check_script), "--in", str(temp_file), "--chunks", chunks_path],
        capture_output=True,
        text=True
    )

    # Clean up temp file
    temp_file.unlink(missing_ok=True)

    return result.returncode == 0


def validate_entry_json(entry: Dict, scripts_dir: Path, chunks_path: str) -> Dict:
    """Validate entry and return structured JSON result"""
    import subprocess

    # Write entry to temp file
    temp_file = scripts_dir.parent / "work" / f"temp_{entry['chunk_id']}.json"
    temp_file.parent.mkdir(exist_ok=True)

    with open(temp_file, 'w', encoding='utf-8') as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)

    # Run validation script with --json flag
    check_script = scripts_dir / "check_translation_entry.py"
    result = subprocess.run(
        [sys.executable, str(check_script), "--in", str(temp_file), "--chunks", chunks_path, "--json"],
        capture_output=True,
        text=True
    )

    # Clean up temp file
    temp_file.unlink(missing_ok=True)

    # Parse JSON output
    if result.stdout.strip():
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            # Fallback if JSON parsing fails
            return {
                "status": "error",
                "valid": False,
                "errors": [{
                    "type": "VALIDATION_ERROR",
                    "message": f"Failed to parse validation output: {result.stdout}",
                    "suggestion": "Check validation script output"
                }],
                "warnings": []
            }
    else:
        # No output means validation failed
        return {
            "status": "error",
            "valid": False,
            "errors": [{
                "type": "VALIDATION_ERROR",
                "message": f"Validation script failed: {result.stderr}",
                "suggestion": "Check validation script errors"
            }],
            "warnings": []
        }


def format_errors_for_ai(errors: List[Dict]) -> str:
    """Format validation errors for AI consumption"""
    formatted = []
    for error in errors:
        error_type = error.get('type', 'UNKNOWN')

        if error_type == 'BLANK_LINES':
            formatted.append(
                f"- ERROR: {error['message']}\n"
                f"  Fix: {error['suggestion']}"
            )
        elif error_type == 'MATH_PRESERVATION':
            formatted.append(
                f"- ERROR: {error['message']}\n"
                f"  Original LaTeX: {error.get('original_math', [])}\n"
                f"  Your version: {error.get('modified_math', [])}\n"
                f"  Fix: {error['suggestion']}"
            )
        elif error_type == 'LINK_PRESERVATION':
            formatted.append(
                f"- ERROR: {error['message']}\n"
                f"  Original URLs: {error.get('original_links', [])}\n"
                f"  Your URLs: {error.get('modified_links', [])}\n"
                f"  Fix: {error['suggestion']}"
            )
        elif error_type == 'BLOCK_STRUCTURE':
            formatted.append(
                f"- ERROR: {error['message']}\n"
                f"  Fix: {error['suggestion']}"
            )
        else:
            # Generic error formatting
            formatted.append(
                f"- ERROR: {error.get('message', 'Unknown error')}\n"
                f"  Fix: {error.get('suggestion', 'Please correct this issue')}"
            )

    return "\n".join(formatted)


def create_retry_prompt(chunk: Dict, config: Dict, previous_errors: List[Dict]) -> tuple:
    """Create prompt for retry with validation error feedback"""
    error_summary = format_errors_for_ai(previous_errors)

    system_prompt = config['system_prompt'].format(
        target_language=config['translation']['target_language']
    )

    user_prompt = f"""Your previous translation had validation errors. Please fix them.

ORIGINAL TEXT:
{chunk['source_md']}

VALIDATION ERRORS:
{error_summary}

Please provide a corrected translation that addresses all the errors above.
Remember:
- Keep LaTeX formulas EXACTLY as they appear (don't modify $...$ or $$...$$)
- Keep all URLs and link destinations unchanged
- Don't add blank lines within the paragraph
- Don't introduce headings (#), code fences (```), or math fences ($$)
"""

    return (system_prompt, user_prompt)


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


def append_entry(entry: Dict, output_path: str, chunks_path: str, scripts_dir: Path) -> bool:
    """Append validated entry to translations.jsonl using append_translation.py"""
    import subprocess

    # Write entry to temp file
    temp_file = scripts_dir.parent / "work" / f"temp_{entry['chunk_id']}.json"
    temp_file.parent.mkdir(exist_ok=True)

    with open(temp_file, 'w', encoding='utf-8') as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)

    # Run append script with correct arguments
    append_script = scripts_dir / "append_translation.py"
    result = subprocess.run(
        [sys.executable, str(append_script), "--db", output_path, "--in", str(temp_file), "--chunks", chunks_path],
        capture_output=True,
        text=True
    )

    # Clean up temp file
    temp_file.unlink(missing_ok=True)

    if result.returncode != 0:
        print(f"Warning: Failed to append {entry['chunk_id']}: {result.stderr}", file=sys.stderr)
        return False

    return True


async def process_chunk(
    session: aiohttp.ClientSession,
    chunk: Dict,
    config: Dict,
    semaphore: asyncio.Semaphore,
    output_path: str,
    chunks_path: str,
    scripts_dir: Path,
    stats: Dict,
    max_iterations: int = 3
) -> Optional[Dict]:
    """Process a single chunk with iterative validation-retry loop"""
    try:
        # Check if iterative validation is enabled
        enable_iterative = config.get('translation', {}).get('enable_iterative_validation', True)

        if enable_iterative:
            # New: Iterative translation with validation feedback
            entry, validation_history = await translate_chunk_with_validation_loop(
                session, chunk, config, semaphore, chunks_path, scripts_dir, max_iterations
            )

            if entry is not None:
                # Success after 1-N iterations
                iterations_used = len(validation_history)
                stats['success'] += 1
                stats[f'success_iteration_{iterations_used}'] = stats.get(f'success_iteration_{iterations_used}', 0) + 1

                # Append to database
                if not append_entry(entry, output_path, chunks_path, scripts_dir):
                    stats['append_failed'] += 1
                    return None

                return entry
            else:
                # Failed after all iterations
                stats['validation_failed'] += 1
                if 'failed_chunks' not in stats:
                    stats['failed_chunks'] = []
                stats['failed_chunks'].append({
                    'chunk_id': chunk['chunk_id'],
                    'validation_history': validation_history
                })
                return None
        else:
            # Old behavior: single-pass translation (backward compatible)
            entry = await translate_chunk_with_retry(session, chunk, config, semaphore)

            # Validate
            if not validate_entry(entry, scripts_dir, chunks_path):
                stats['validation_failed'] += 1
                print(f"Validation failed for {chunk['chunk_id']}", file=sys.stderr)
                return None

            # Append to database
            if not append_entry(entry, output_path, chunks_path, scripts_dir):
                stats['append_failed'] += 1
                return None

            stats['success'] += 1
            return entry

    except RetryExhausted as e:
        # All retries exhausted
        stats['failed'] += 1
        print(f"Failed after retries: {chunk['chunk_id']}: {str(e)}", file=sys.stderr)
        return None

    except Exception as e:
        # Unexpected error
        stats['failed'] += 1
        print(f"Unexpected error for {chunk['chunk_id']}: {str(e)}", file=sys.stderr)
        return None


async def translate_all_chunks(
    chunks: List[Dict],
    config: Dict,
    output_path: str,
    chunks_path: str,
    scripts_dir: Path
) -> Dict:
    """Translate all chunks with high concurrency"""
    stats = {
        'success': 0,
        'failed': 0,
        'validation_failed': 0,
        'append_failed': 0,
        'success_iteration_1': 0,
        'success_iteration_2': 0,
        'success_iteration_3': 0,
        'failed_chunks': []
    }

    # Get max iterations from config
    max_iterations = config.get('translation', {}).get('max_validation_iterations', 3)

    semaphore = asyncio.Semaphore(config['translation']['concurrency'])

    async with aiohttp.ClientSession() as session:
        # Create tasks for all chunks
        tasks = [
            process_chunk(session, chunk, config, semaphore, output_path, chunks_path, scripts_dir, stats, max_iterations)
            for chunk in chunks
        ]

        # Process with progress bar
        print(f"Translating {len(chunks)} chunks with {config['translation']['concurrency']} concurrent requests...")

        for coro in tqdm.as_completed(tasks, total=len(tasks), desc="Translating"):
            await coro

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="High-concurrency translation script for article translator"
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
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip already-translated chunks (resume mode)"
    )

    args = parser.parse_args()

    # Load configuration
    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"Error loading config: {e}", file=sys.stderr)
        sys.exit(1)

    # Load chunks
    try:
        all_chunks = load_chunks(args.chunks)
        print(f"Loaded {len(all_chunks)} chunks from {args.chunks}")
    except Exception as e:
        print(f"Error loading chunks: {e}", file=sys.stderr)
        sys.exit(1)

    # Filter out already-translated chunks if resume mode
    if args.resume:
        existing = load_existing_translations(args.output)
        chunks_to_translate = [c for c in all_chunks if c['chunk_id'] not in existing]
        print(f"Resume mode: {len(existing)} already translated, {len(chunks_to_translate)} remaining")
    else:
        chunks_to_translate = all_chunks

    if not chunks_to_translate:
        print("No chunks to translate!")
        sys.exit(0)

    # Get scripts directory
    scripts_dir = Path(__file__).parent

    # Run translation
    start_time = time.time()

    try:
        stats = asyncio.run(translate_all_chunks(
            chunks_to_translate,
            config,
            args.output,
            args.chunks,
            scripts_dir
        ))
    except KeyboardInterrupt:
        print("\nInterrupted by user. Progress has been saved.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)

    elapsed = time.time() - start_time

    # Print summary
    print("\n" + "="*60)
    print("TRANSLATION COMPLETE")
    print("="*60)
    print(f"Total chunks:        {len(chunks_to_translate)}")
    print(f"Successful:          {stats['success']}")

    # Show iteration breakdown if iterative validation is enabled
    if config.get('translation', {}).get('enable_iterative_validation', True):
        print(f"  - 1st attempt:     {stats.get('success_iteration_1', 0)}")
        print(f"  - 2nd attempt:     {stats.get('success_iteration_2', 0)}")
        print(f"  - 3rd attempt:     {stats.get('success_iteration_3', 0)}")

    print(f"Failed:              {stats['failed']}")
    print(f"Validation failed:   {stats['validation_failed']}")
    print(f"Append failed:       {stats['append_failed']}")
    print(f"Time elapsed:        {elapsed:.1f} seconds")
    print(f"Average per chunk:   {elapsed/len(chunks_to_translate):.2f} seconds")
    print("="*60)

    # Save failed chunks to file if any
    if stats['validation_failed'] > 0 and stats.get('failed_chunks'):
        failed_chunks_path = Path(args.output).parent / "failed_chunks.json"
        with open(failed_chunks_path, 'w', encoding='utf-8') as f:
            json.dump(stats['failed_chunks'], f, ensure_ascii=False, indent=2)
        print(f"\nFailed chunks saved to: {failed_chunks_path}")
        print(f"Use handle_failed_chunks.py to process them with more detailed prompts.")

    if stats['failed'] > 0 or stats['validation_failed'] > 0 or stats['append_failed'] > 0:
        print("\nSome chunks failed. Re-run with --resume to retry failed chunks.")
        sys.exit(1)


if __name__ == "__main__":
    main()
