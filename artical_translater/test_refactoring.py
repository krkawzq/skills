#!/usr/bin/env python3
"""
Quick test script to verify the refactored modules work correctly.
"""

import sys
from pathlib import Path

# Add scripts directory to path
scripts_dir = Path(__file__).parent / "scripts"
sys.path.insert(0, str(scripts_dir))

def test_shared():
    """Test shared module"""
    print("Testing shared.py...")
    from shared import source_md_is_safe, sanitize_target_md

    # Test source_md_is_safe
    assert source_md_is_safe("This is a simple paragraph.") == True
    assert source_md_is_safe("Para 1\n\nPara 2") == False  # Has blank line
    assert source_md_is_safe("# Heading") == False  # Has heading
    print("  [OK] source_md_is_safe works")

    # Test sanitize_target_md
    result = sanitize_target_md("Line 1\n\nLine 2\n# Heading\n```code```")
    assert "\n\n" not in result
    assert "#" not in result
    assert "```" not in result
    print("  [OK] sanitize_target_md works")

def test_prompts():
    """Test prompts module"""
    print("\nTesting prompts.py...")
    from prompts import build_system_prompt, build_user_prompt

    # Test build_system_prompt
    prompt = build_system_prompt(
        target_language="Chinese",
        enable_source_correction=False,
        enable_math_fixing=True,
        guidance_prompt=None
    )
    assert "Chinese" in prompt
    assert "markdown translated" in prompt
    assert "DIFFICULTY" in prompt
    print("  [OK] build_system_prompt works")

    # Test build_user_prompt
    user_prompt = build_user_prompt("This is a test paragraph.")
    assert "test paragraph" in user_prompt
    print("  [OK] build_user_prompt works")

def test_response_parser():
    """Test response_parser module"""
    print("\nTesting response_parser.py...")
    from response_parser import parse_translation_response

    # Test parsing valid response
    response = """
### Analysis
This is a simple paragraph.

```markdown translated
这是一个简单的段落。
```

DIFFICULTY: easy
CONFIDENCE: high
CHECKER_BYPASS: none
NOTES: none
"""
    parsed = parse_translation_response(response)
    assert parsed.translated_md == "这是一个简单的段落。"
    assert parsed.difficulty == "easy"
    assert parsed.confidence == "high"
    print("  [OK] parse_translation_response works")

def test_normalize_math():
    """Test normalize_math module"""
    print("\nTesting normalize_math.py...")
    from normalize_math import rule_based_fix

    # Test rule-based fixes
    text = "The formula is $ x ^ 2 $ and ∫ f(x) dx."
    fixed = rule_based_fix(text)
    assert "$x^2$" in fixed
    assert "\\int" in fixed
    assert "∫" not in fixed
    print("  [OK] rule_based_fix works")

def main():
    print("="*60)
    print("REFACTORING VERIFICATION TEST")
    print("="*60)

    try:
        test_shared()
        test_prompts()
        test_response_parser()
        test_normalize_math()

        print("\n" + "="*60)
        print("ALL TESTS PASSED [OK]")
        print("="*60)
        print("\nThe refactored modules are working correctly!")
        return 0
    except Exception as e:
        print(f"\n[FAILED] TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
