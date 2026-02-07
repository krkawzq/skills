#!/usr/bin/env python3
"""
Batch validate multiple translation entries
"""

import argparse
import sys
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Batch validate translation entries")
    parser.add_argument(
        "--dir", required=True, help="Directory containing entry_*.json files"
    )
    parser.add_argument("--chunks", required=True, help="Path to chunks.jsonl")
    parser.add_argument(
        "--pattern", default="entry_*.json", help="File pattern to match"
    )
    args = parser.parse_args()

    # Find all entry files
    entry_dir = Path(args.dir)
    entry_files = sorted(entry_dir.glob(args.pattern))

    if not entry_files:
        print(f"No files matching {args.pattern} found in {args.dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(entry_files)} entry files to validate", file=sys.stderr)

    passed = 0
    failed = 0
    errors = []

    for entry_file in entry_files:
        # Run check_translation_entry.py
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

        if result.returncode == 0:
            passed += 1
            print(f"✓ {entry_file.name}", file=sys.stderr)
        else:
            failed += 1
            errors.append(entry_file.name)
            if result.stderr:
                print(result.stderr.rstrip("\n"), file=sys.stderr)
            print(f"✗ {entry_file.name}", file=sys.stderr)

    print(f"\nValidation complete:", file=sys.stderr)
    print(f"  Passed: {passed}", file=sys.stderr)
    print(f"  Failed: {failed}", file=sys.stderr)

    if errors:
        print(f"\nFailed files:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        sys.exit(1)

    print("\nAll entries valid!", file=sys.stderr)


if __name__ == "__main__":
    main()
