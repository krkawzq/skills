#!/usr/bin/env python3
"""
Batch append multiple translation entries to database
"""

import argparse
import sys
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Batch append translation entries to database"
    )
    parser.add_argument(
        "--dir", required=True, help="Directory containing entry_*.json files"
    )
    parser.add_argument(
        "--db", required=True, help="Path to translations.jsonl database"
    )
    parser.add_argument("--chunks", required=True, help="Path to chunks.jsonl")
    parser.add_argument(
        "--pattern", default="entry_*.json", help="File pattern to match"
    )
    parser.add_argument(
        "--validate", action="store_true", help="Validate before appending"
    )
    args = parser.parse_args()

    # Find all entry files
    entry_dir = Path(args.dir)
    entry_files = sorted(entry_dir.glob(args.pattern))

    if not entry_files:
        print(f"No files matching {args.pattern} found in {args.dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(entry_files)} entry files to append", file=sys.stderr)

    appended = 0
    failed = 0
    errors = []

    for entry_file in entry_files:
        # Validate first if requested
        if args.validate:
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/check_translation_entry.py",
                    "--in",
                    str(entry_file),
                    "--chunks",
                    args.chunks,
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                failed += 1
                errors.append((entry_file.name, "Validation failed"))
                if result.stderr:
                    print(result.stderr.rstrip("\n"), file=sys.stderr)
                print(f"✗ {entry_file.name} - validation failed", file=sys.stderr)
                continue

        # Append to database
        result = subprocess.run(
            [
                sys.executable,
                "scripts/append_translation.py",
                "--db",
                args.db,
                "--chunks",
                args.chunks,
                "--in",
                str(entry_file),
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            appended += 1
            print(f"✓ {entry_file.name}", file=sys.stderr)
        else:
            failed += 1
            errors.append((entry_file.name, "Append failed"))
            if result.stderr:
                print(result.stderr.rstrip("\n"), file=sys.stderr)
            print(f"✗ {entry_file.name} - append failed", file=sys.stderr)

    print(f"\nBatch append complete:", file=sys.stderr)
    print(f"  Appended: {appended}", file=sys.stderr)
    print(f"  Failed: {failed}", file=sys.stderr)

    if errors:
        print(f"\nFailed entries:", file=sys.stderr)
        for filename, reason in errors:
            print(f"  - {filename}: {reason}", file=sys.stderr)
        sys.exit(1)

    print("\nAll entries appended successfully!", file=sys.stderr)


if __name__ == "__main__":
    main()
