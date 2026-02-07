---
name: anndata_toolkit
description: A set of CLI tools for inspecting and processing AnnData (.h5ad) files. Capabilities include viewing metadata structure, identifying cell type and perturbation columns via Claude subagent, computing highly variable genes (HVG), and performing differential expression (DE) analysis.
---

**Setup**

```bash
uv pip install -r requirements.txt
```

**Tools**

1. **anndata_info.py** - Inspect AnnData Metadata

Quickly inspect h5ad file structure: obs/var columns, X shape/dtype, layers, obsm/varm, obsp/varp, uns keys.

```bash
uv run scripts/anndata_info.py <h5ad_file>
uv run scripts/anndata_info.py <h5ad_file> "adata.obs.head()"  # custom expression
```

2. **guess_celltype_column.py** - Identify Cell Type Column

Uses Claude subagent to identify which obs column contains cell type annotations.

```bash
uv run scripts/guess_celltype_column.py <h5ad_file>
```

3. **guess_perturb_info.py** - Identify Perturbation Info

Two-stage Claude subagent analysis to find perturbation column and control labels.

```bash
uv run scripts/guess_perturb_info.py <h5ad_file> [options]
```

**Arguments:**
| Arg | Description |
|-----|-------------|
| `--pert-col` | Manually specify perturbation column (skip auto-detection) |
| `--model` | Claude model for analysis (default: haiku) |

**Examples:**
```bash
# Auto-detect perturbation column
uv run scripts/guess_perturb_info.py data.h5ad

# Manually specify perturbation column
uv run scripts/guess_perturb_info.py data.h5ad --pert-col gene
```

**Output (JSON):**
- `perturbation_column`: column name
- `ctrl_tags`: control group identifiers
- `unknown_tags`: ambiguous values
- `perturbation_type`: CRISPR/drug/etc.

4. **calc_hvgs.py** - Compute Highly Variable Genes

High-performance HVG selection using biosparse. Outputs JSON.

```bash
uv run scripts/calc_hvgs.py <h5ad_file> -n <n_top_genes> -o <output.json> [options]
```

**Arguments:**
| Arg | Description |
|-----|-------------|
| `-n, --n-top-genes` | Number of HVGs to select (default: 2000) |
| `-o, --output` | Output JSON path (default: stdout) |
| `--flavor` | `seurat` / `cell_ranger` / `seurat_v3` / `pearson` (default: seurat) |
| `--layer` | Use specific layer instead of X |
| `--use-raw` | Use adata.raw |
| `--exclude-col` | Obs column for cell filtering |
| `--exclude` | Values to exclude (space-separated) |
| `--no-stats` | Omit per-gene statistics |
| `-v, --verbose` | Show progress |

**Flavor-specific:**
- seurat: `--n-bins`, `--min-mean`, `--max-mean`, `--min-disp`, `--max-disp`
- seurat_v3: `--span` (LOESS, default: 0.3)
- pearson: `--theta`, `--clip`

**Example:**
```bash
uv run scripts/calc_hvgs.py data.h5ad -n 2000 --flavor seurat_v3 --exclude-col celltype --exclude Doublet -o hvgs.json
```

5. **calc_degs.py** - Compute Differential Expression

High-performance DE analysis (perturbation vs control). Outputs CSV.

```bash
uv run scripts/calc_degs.py <h5ad_file> --pert-col <col> --ctrl <ctrl_value> -o <output.csv> [options]
```

**Required Arguments:**
| Arg | Description |
|-----|-------------|
| `--pert-col` | Obs column containing perturbation labels |
| `--ctrl` | Control group value in pert-col |
| `-o, --output` | Output CSV path |

**Optional Arguments:**
| Arg | Description |
|-----|-------------|
| `--method` | `mwu` (Mann-Whitney U) / `ttest` (Welch's) (default: mwu) |
| `--layer` | Use specific layer |
| `--fdr` | FDR threshold filter |
| `--log2fc` | Absolute log2FC threshold filter |
| `--perturbations` | Only analyze these perturbations |
| `--exclude-col` | Obs column for cell filtering |
| `--exclude` | Values to exclude |
| `-v, --verbose` | Show progress |

**Output CSV columns:** `perturbation, gene, p_value, fdr, log2fc`

**Example:**
```bash
uv run scripts/calc_degs.py data.h5ad --pert-col gene --ctrl NT --method mwu --fdr 0.05 --exclude-col celltype --exclude Doublet -o degs.csv
```
