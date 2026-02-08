#!/usr/bin/env python3
"""
Hardcoded prompts for the Article Translator framework.

All prompts are defined here as constants or builder functions.
This avoids the .format() + LaTeX curly brace conflict that existed
when prompts were stored in config.yaml.
"""

from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# SYSTEM PROMPT: Translation Agent Identity
# ---------------------------------------------------------------------------

def build_system_prompt(
    target_language: str,
    enable_source_correction: bool = False,
    enable_math_fixing: bool = False,
    guidance_prompt: Optional[str] = None,
) -> str:
    """
    Build the complete system prompt for a sub-translator agent.

    This uses string concatenation (not .format()) to avoid LaTeX brace conflicts.
    """

    # Section 1: Agent Identity
    identity = (
        "You are a specialized academic paper translation agent. "
        "You are part of a high-concurrency translation pipeline that processes "
        "academic papers chunk by chunk. Each chunk is a single paragraph from "
        "a Markdown document.\\n\\n"
        "Your task: Translate the given paragraph from English to "
        + target_language + ".\\n\\n"
    )

    # Section 2: Output Format Instructions
    output_format = (
        "## OUTPUT FORMAT\\n\\n"
        "You MUST structure your response as follows:\\n\\n"
        "### Step 1: Analysis (think before translating)\\n"
        "Briefly analyze the content:\\n"
        "- What type of content is this? (prose, equation-heavy, figure reference, etc.)\\n"
        "- Are there any tricky elements? (formulas, links, technical terms)\\n"
        "- Any potential issues the validator might flag?\\n\\n"
        "### Step 2: Translation\\n"
        "Provide your translation inside a markdown code block:\\n\\n"
        "```markdown translated\\n"
        "Your translated text here\\n"
        "```\\n\\n"
    )

    # Section 2b: Source correction block (conditional)
    if enable_source_correction:
        output_format += (
            "### Step 2b: Source Correction (if needed)\\n"
            "If the source text has OCR errors, provide a corrected version:\\n\\n"
            "```markdown corrected\\n"
            "Corrected source text here\\n"
            "```\\n\\n"
            "Only include this block if you actually made corrections. "
            "If the source is fine, omit this block entirely.\\n\\n"
        )

    # Section 3: Meta-info
    meta_info = (
        "### Step 3: Meta-info\\n"
        "After the translation block(s), provide a brief summary:\\n\\n"
        "DIFFICULTY: [easy|medium|hard]\\n"
        "POTENTIAL_ISSUES: [none|list of potential validator issues]\\n"
        "CONFIDENCE: [high|medium|low]\\n"
        "CHECKER_BYPASS: [none|explain why checker might incorrectly flag this, if applicable]\\n"
        "NOTES: [any notes about translation choices, or 'none']\\n\\n"
    )

    # Section 4: Critical Rules
    rules = (
        "## CRITICAL RULES\\n\\n"
        "1. **LaTeX formulas**: "
    )

    if enable_math_fixing:
        rules += (
            "Fix obvious OCR formatting issues in formulas:\\n"
            "   - Remove extra spaces: `$ x ^ 2 $` becomes `$x^2$`\\n"
            "   - Use correct LaTeX commands: `\\\\int` not Unicode ∫, `\\\\times` not ×\\n"
            "   - Keep inline math with single `$` and display math with `$$`\\n"
            "   - Preserve the mathematical CONTENT even if you fix formatting\\n"
            "   Examples: `$x^2$`, `$\\\\int f(x)dx$`, `$$\\\\sum_{i=1}^n x_i$$`\\n\\n"
        )
    else:
        rules += (
            "Preserve ALL LaTeX formulas EXACTLY as they appear in the source.\\n"
            "   - Do not change spacing, delimiters, or commands\\n"
            "   - Copy `$...$` and `$$...$$` blocks character-for-character\\n\\n"
        )

    rules += (
        "2. **Links and images**: Preserve ALL URLs and link destinations exactly.\\n"
        "   - Only translate the display text: `[display text](url)` -> `[translated text](url)`\\n"
        "   - Never modify the URL part\\n"
        "   - Preserve HTML src/href attributes unchanged\\n\\n"
        "3. **No structural elements**: Do NOT introduce:\\n"
        "   - Blank lines (double newlines) within your translation\\n"
        "   - Heading markers (`#`, `##`, etc.)\\n"
        "   - Code fences (```) or math fences (`$$` on its own line)\\n"
        "   Your output must be a single paragraph block.\\n\\n"
        "4. **Translation quality**:\\n"
        "   - Translate naturally, not word-by-word\\n"
        "   - Maintain technical accuracy\\n"
        "   - Keep widely-known technical terms in English when appropriate\\n"
        "   - Preserve the academic tone and register\\n\\n"
    )

    # Section 5: Guidance (optional, from main agent)
    guidance_section = ""
    if guidance_prompt:
        guidance_section = (
            "## MAIN AGENT GUIDANCE\\n\\n"
            "The main translation agent has analyzed this paper and provides "
            "the following guidance for your translation:\\n\\n"
            + guidance_prompt + "\\n\\n"
            "Please follow this guidance carefully.\\n\\n"
        )

    return identity + output_format + meta_info + rules + guidance_section


# ---------------------------------------------------------------------------
# RETRY PROMPT: When validation fails
# ---------------------------------------------------------------------------

def build_retry_system_prompt(
    target_language: str,
    enable_source_correction: bool = False,
    enable_math_fixing: bool = False,
    guidance_prompt: Optional[str] = None,
) -> str:
    """Build system prompt for retry attempts (includes extra emphasis on errors)."""
    base = build_system_prompt(
        target_language=target_language,
        enable_source_correction=enable_source_correction,
        enable_math_fixing=enable_math_fixing,
        guidance_prompt=guidance_prompt,
    )

    retry_addendum = (
        "\\n## IMPORTANT: RETRY ATTEMPT\\n\\n"
        "Your previous translation FAILED validation. "
        "Pay extra attention to the specific errors listed in the user message. "
        "The most common failures are:\\n"
        "- Adding blank lines within the translation\\n"
        "- Modifying LaTeX formula content\\n"
        "- Changing link/image URLs\\n"
        "- Introducing code fences, math fences, or headings\\n\\n"
        "If you believe a validation error is NOT your fault (e.g., the source "
        "text itself has issues), explain this in your CHECKER_BYPASS field.\\n"
    )

    return base + retry_addendum


def format_errors_for_ai(errors: List[Dict]) -> str:
    """Format validation errors for AI consumption."""
    formatted = []
    for error in errors:
        error_type = error.get('type', 'UNKNOWN')

        if error_type == 'BLANK_LINES':
            formatted.append(
                "- ERROR: " + error['message'] + "\\n"
                "  Fix: " + error['suggestion']
            )
        elif error_type == 'MATH_PRESERVATION':
            formatted.append(
                "- ERROR: " + error['message'] + "\\n"
                "  Original LaTeX: " + str(error.get('original_math', [])) + "\\n"
                "  Your version: " + str(error.get('modified_math', [])) + "\\n"
                "  Fix: " + error['suggestion']
            )
        elif error_type == 'LINK_PRESERVATION':
            formatted.append(
                "- ERROR: " + error['message'] + "\\n"
                "  Original URLs: " + str(error.get('original_links', [])) + "\\n"
                "  Your URLs: " + str(error.get('modified_links', [])) + "\\n"
                "  Fix: " + error['suggestion']
            )
        elif error_type == 'BLOCK_STRUCTURE':
            formatted.append(
                "- ERROR: " + error['message'] + "\\n"
                "  Fix: " + error['suggestion']
            )
        else:
            # Generic error formatting
            formatted.append(
                "- ERROR: " + error.get('message', 'Unknown error') + "\\n"
                "  Fix: " + error.get('suggestion', 'Please correct this issue')
            )

    return "\\n".join(formatted)


def build_retry_user_prompt(
    source_md: str,
    previous_errors: List[Dict],
) -> str:
    """Build user prompt for retry with validation feedback."""
    error_summary = format_errors_for_ai(previous_errors)

    return (
        "Your previous translation had validation errors. Please fix them.\\n\\n"
        "ORIGINAL TEXT:\\n"
        + source_md + "\\n\\n"
        "VALIDATION ERRORS:\\n"
        + error_summary + "\\n\\n"
        "Please provide a corrected translation using the exact output format "
        "specified in your instructions (analysis, ```markdown translated``` block, meta-info).\\n"
    )


def build_user_prompt(source_md: str) -> str:
    """Build the initial user prompt for translation."""
    return (
        "Translate the following paragraph:\\n\\n"
        + source_md
    )


# ---------------------------------------------------------------------------
# FORMULA STANDARDIZATION PROMPT
# ---------------------------------------------------------------------------

def build_math_normalize_prompt() -> str:
    """System prompt for the AI formula standardization tool."""
    return (
        "You are a LaTeX formula standardization tool. "
        "Your job is to fix common OCR issues in LaTeX formulas within Markdown text.\\n\\n"
        "## RULES\\n\\n"
        "1. Fix extra spaces inside formulas:\\n"
        "   - `$ x ^ 2 $` -> `$x^2$`\\n"
        "   - `$ \\\\int _ { 0 } ^ { 1 } f ( x ) d x $` -> `$\\\\int_{0}^{1} f(x) dx$`\\n\\n"
        "2. Fix delimiter issues:\\n"
        "   - Ensure inline math uses single `$...$`\\n"
        "   - Ensure display math uses `$$...$$`\\n"
        "   - Convert `\\\\(...\\\\)` to `$...$` and `\\\\[...\\\\]` to `$$...$$` if desired\\n\\n"
        "3. Replace Unicode math symbols with LaTeX commands:\\n"
        "   - ∫ -> `\\\\int`\\n"
        "   - × -> `\\\\times`\\n"
        "   - ∑ -> `\\\\sum`\\n"
        "   - √ -> `\\\\sqrt`\\n"
        "   - ≤ -> `\\\\leq`\\n"
        "   - ≥ -> `\\\\geq`\\n"
        "   - ≠ -> `\\\\neq`\\n"
        "   - ∞ -> `\\\\infty`\\n\\n"
        "4. Preserve ALL non-formula text exactly as-is\\n"
        "5. Preserve ALL links and URLs exactly as-is\\n"
        "6. Do NOT translate anything\\n\\n"
        "## OUTPUT FORMAT\\n\\n"
        "Output the corrected text inside a markdown code block:\\n\\n"
        "```markdown corrected\\n"
        "The corrected text with fixed formulas\\n"
        "```\\n"
    )





