import anndata as ad
import pandas as pd
import subprocess
import sys

def load_obs(path: str) -> pd.DataFrame:
    adata = ad.read_h5ad(path, backed='r')
    return adata.obs

def extract_columns_info(obs: pd.DataFrame, limit: int = 20) -> str:
    """Extract column names and sample values from obs DataFrame."""
    lines = []
    for col in obs.columns:
        unique_vals = obs[col].dropna().unique()[:limit].tolist()
        # Format values nicely
        vals_str = ", ".join(repr(v) for v in unique_vals)
        if len(obs[col].dropna().unique()) > limit:
            vals_str += ", ..."
        lines.append(f"- {col}: [{vals_str}]")
    
    return f"""## AnnData obs columns ({len(obs.columns)} total)

{'\n'.join(lines)}
"""

def call_claude(question: str, information: str, model: str = "haiku") -> str:
    """Call Claude CLI as subagent."""
    prompt = f"""You are a single-cell genomics expert analyzing an AnnData object.

{information}

## Task
{question}

## Instructions
- Answer concisely with ONLY the column name
- If uncertain, say "UNKNOWN. " and briefly explain why
"""
    result = subprocess.run(
        ["claude", "-p", "--model", model],
        input=prompt,
        capture_output=True,
        text=True
    )
    return result.stdout.strip()


def main():
    if len(sys.argv) != 2:
        print("Usage: python guess_celltype_column.py <h5ad_file>")
        sys.exit(1)
    
    path = sys.argv[1]
    obs = load_obs(path)
    info = extract_columns_info(obs)
    
    question = """Which column most likely represents the **cell type annotation**?

Common patterns: 'celltype', 'cell_type', 'CellType', 'cluster', 'label', 'annotation', etc.
Look for columns with values like cell type names (e.g., 'T cell', 'B cell', 'Monocyte', 'Fibroblast')."""

    answer = call_claude(question, info)
    print(answer)


if __name__ == "__main__":
    main()
