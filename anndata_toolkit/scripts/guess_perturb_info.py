import anndata as ad
import pandas as pd
import subprocess
import sys
import re
import json
import argparse

def load_obs(path: str) -> pd.DataFrame:
    adata = ad.read_h5ad(path, backed='r')
    return adata.obs

def extract_columns_info(obs: pd.DataFrame, limit: int = 20) -> str:
    """Extract column names and sample values from obs DataFrame."""
    lines = []
    for col in obs.columns:
        unique_vals = obs[col].dropna().unique()[:limit].tolist()
        vals_str = ", ".join(repr(v) for v in unique_vals)
        if len(obs[col].dropna().unique()) > limit:
            vals_str += ", ..."
        lines.append(f"- {col}: [{vals_str}]")
    
    return f"""## AnnData obs columns ({len(obs.columns)} total)

{'\n'.join(lines)}
"""

def call_claude(prompt: str, model: str = "haiku") -> str:
    """Call Claude CLI as subagent."""
    result = subprocess.run(
        ["claude", "-p", "--model", model],
        input=prompt,
        capture_output=True,
        text=True
    )
    return result.stdout.strip()

def parse_answer_tag(response: str) -> str:
    """Extract content from <answer> tag."""
    match = re.search(r'<answer>(.*?)</answer>', response, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None

def parse_explanation_tag(response: str) -> str:
    """Extract content from <explanation> tag."""
    match = re.search(r'<explanation>(.*?)</explanation>', response, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None

def parse_json_block(response: str) -> dict:
    """Extract JSON from response (handles ```json blocks)."""
    # Try to find ```json block first
    match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Try to find raw JSON object
    match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    
    return None


# ============ Stage 1: Find perturbation column ============

def stage1_find_perturbation_column(obs: pd.DataFrame, model: str = "haiku") -> tuple[str, str]:
    """
    Stage 1: Identify which column contains perturbation information.
    
    Returns:
        (column_name, explanation) - column_name is None if not found
    """
    info = extract_columns_info(obs)
    
    prompt = f"""You are a single-cell genomics expert analyzing a perturbation experiment dataset.

{info}

## Task
Which column contains the **perturbation/treatment labels** (the actual perturbation targets)?

Common patterns: 'perturbation', 'gene', 'target', 'guide', 'sgRNA', 'condition', 'target_gene', etc.
Look for columns with values like gene names (TP53, BRCA1) or containing control indicators (ctrl, NT, DMSO).

## Response Format
- If found: <answer>column_name</answer>
- If not found: <answer>UNKNOWN</answer><explanation>reason</explanation>
"""
    
    response = call_claude(prompt, model)
    
    answer = parse_answer_tag(response)
    explanation = parse_explanation_tag(response)
    
    if answer and answer.upper() != "UNKNOWN":
        return (answer, None)
    else:
        return (None, explanation or "Could not identify perturbation column")


# ============ Stage 2: Analyze perturbation values ============

def stage2_analyze_perturbations(obs: pd.DataFrame, pert_column: str, model: str = "haiku") -> dict:
    """
    Stage 2: Analyze all unique values in perturbation column to identify controls.
    
    Returns:
        dict with keys: ctrl_tags, unknown_tags, explanation, perturbation_type
    """
    unique_values = obs[pert_column].dropna().unique().tolist()
    
    prompt = f"""You are a single-cell genomics expert analyzing perturbation experiment data.

## Perturbation Column: `{pert_column}`

## All Unique Values ({len(unique_values)} total):
{json.dumps(unique_values, ensure_ascii=False, indent=2)}

## Task
Analyze these perturbation values and identify:

1. **Control tags**: Which values represent control/negative control samples?
   Common patterns: 'control', 'ctrl', 'NT', 'non-targeting', 'negative', 'NTC', 'DMSO', 'vehicle', 'scramble', 'mock', 'untreated', 'WT', 'wildtype'

2. **Unknown tags**: Values that are ambiguous or cannot be classified (e.g., unclear if control or real perturbation)

3. **Perturbation type**: What kind of perturbation is this?
   - CRISPR knockout/knockdown (gene names as targets)
   - Drug/compound treatment
   - Small molecule perturbation  
   - Overexpression
   - Multiple/combined perturbations
   - Other (describe)

## Response Format
Return a JSON block:
```json
{{
    "ctrl_tags": ["list of control identifiers"],
    "unknown_tags": ["ambiguous values if any"],
    "explanation": "explanation if ctrl not found or for unknown tags",
    "perturbation_type": "natural language description of perturbation type"
}}
```
"""
    
    response = call_claude(prompt, model)
    
    result = parse_json_block(response)
    
    if result is None:
        return {
            "ctrl_tags": [],
            "unknown_tags": [],
            "explanation": f"Failed to parse response: {response}",
            "perturbation_type": "unknown"
        }
    
    # Ensure all expected keys exist
    result.setdefault("ctrl_tags", [])
    result.setdefault("unknown_tags", [])
    result.setdefault("explanation", "")
    result.setdefault("perturbation_type", "unknown")
    
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Identify perturbation column and analyze control labels in AnnData files"
    )
    parser.add_argument("h5ad_file", help="Path to the h5ad file")
    parser.add_argument(
        "--pert-col", 
        dest="pert_col",
        help="Manually specify the perturbation column name (skip auto-detection)"
    )
    parser.add_argument(
        "--model",
        default="haiku",
        help="Claude model to use for analysis (default: haiku)"
    )
    
    args = parser.parse_args()
    
    obs = load_obs(args.h5ad_file)
    
    # Stage 1: Find perturbation column (skip if manually specified)
    if args.pert_col:
        # Validate that the column exists
        if args.pert_col not in obs.columns:
            print(json.dumps({
                "perturbation_column": None,
                "error": f"Specified column '{args.pert_col}' not found in obs. Available columns: {list(obs.columns)}"
            }, ensure_ascii=False, indent=2))
            sys.exit(1)
        pert_column = args.pert_col
        print(f"Using manually specified perturbation column: {pert_column}", file=sys.stderr)
    else:
        print("=== Stage 1: Finding perturbation column ===", file=sys.stderr)
        pert_column, explanation = stage1_find_perturbation_column(obs, args.model)
        
        if pert_column is None:
            print(json.dumps({
                "perturbation_column": None,
                "error": explanation
            }, ensure_ascii=False, indent=2))
            sys.exit(1)
        
        print(f"Found perturbation column: {pert_column}", file=sys.stderr)
    
    # Stage 2: Analyze perturbation values
    print("=== Stage 2: Analyzing perturbation values ===", file=sys.stderr)
    result = stage2_analyze_perturbations(obs, pert_column, args.model)
    
    # Add column info to result
    result["perturbation_column"] = pert_column
    
    # Output final result
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
