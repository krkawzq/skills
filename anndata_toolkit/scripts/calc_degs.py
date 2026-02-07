#!/usr/bin/env python3
"""
calc_degs.py - 使用 biosparse 高性能计算差异表达基因 (DEGs)

Computes differential expression for each perturbation vs control.
Outputs CSV with columns: perturbation, gene, p_value, fdr, log2fc

Usage:
    python calc_degs.py data.h5ad --pert-col gene --ctrl NT -o degs.csv
    python calc_degs.py data.h5ad --pert-col treatment --ctrl DMSO --method ttest -o degs.csv
"""

import anndata as ad
import numpy as np
import scipy.sparse as sp
import pandas as pd
import sys
import argparse

from biosparse import CSRF32, CSRF64
from biosparse.kernel import mwu_test, t_test


def benjamini_hochberg(p_values: np.ndarray) -> np.ndarray:
    """
    Benjamini-Hochberg FDR correction.
    
    Args:
        p_values: Array of p-values
    
    Returns:
        Array of FDR-adjusted p-values (q-values)
    """
    n = len(p_values)
    if n == 0:
        return np.array([])
    
    # Handle NaN values
    valid_mask = ~np.isnan(p_values)
    if not np.any(valid_mask):
        return np.full(n, np.nan)
    
    # Sort p-values
    sorted_indices = np.argsort(p_values)
    sorted_p = p_values[sorted_indices]
    
    # Compute adjusted p-values
    # q_i = min(p_i * n / rank, 1)
    ranks = np.arange(1, n + 1)
    adjusted = sorted_p * n / ranks
    
    # Ensure monotonicity (from largest to smallest rank)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    
    # Cap at 1.0
    adjusted = np.minimum(adjusted, 1.0)
    
    # Restore original order
    fdr = np.empty(n)
    fdr[sorted_indices] = adjusted
    
    return fdr


def load_expression_matrix(adata: ad.AnnData, layer: str = None):
    """Load expression matrix from AnnData."""
    if layer is not None:
        X = adata.layers[layer]
    else:
        X = adata.X
    
    # Ensure CSR format
    if sp.issparse(X):
        X = X.tocsr()
    else:
        X = sp.csr_matrix(X)
    
    return X


def to_biosparse_csr(X: sp.csr_matrix, transpose: bool = True):
    """Convert scipy CSR to biosparse CSR."""
    if transpose:
        X = X.T.tocsr()
    
    if X.dtype == np.float32:
        return CSRF32.from_scipy(X)
    else:
        X = X.astype(np.float64)
        return CSRF64.from_scipy(X)


def compute_degs(
    csr,
    gene_names: list,
    group_ids: np.ndarray,
    perturbations: list,
    method: str = "mwu",
) -> pd.DataFrame:
    """
    Compute DEGs for all perturbations vs control (group 0).
    
    Args:
        csr: biosparse CSR matrix (genes x cells)
        gene_names: List of gene names
        group_ids: Group assignment (0=control, 1..n=perturbations)
        perturbations: List of perturbation names (excluding control)
        method: "mwu" for Mann-Whitney U, "ttest" for Welch's t-test
    
    Returns:
        DataFrame with columns: perturbation, gene, p_value, fdr, log2fc
    """
    n_genes = len(gene_names)
    n_targets = len(perturbations)
    
    # Compute differential expression
    if method == "mwu":
        u_stats, p_values, log2_fc, auroc = mwu_test(
            csr,
            group_ids,
            n_targets,
            alternative=0,  # two-sided
            use_continuity=True,
        )
    elif method == "ttest":
        t_stats, p_values, log2_fc = t_test(
            csr,
            group_ids,
            n_targets,
            use_welch=True,
        )
    else:
        raise ValueError(f"Unknown method: {method}. Choose from: mwu, ttest")
    
    # Build result DataFrame
    rows = []
    
    for target_idx, pert_name in enumerate(perturbations):
        # Get p-values and log2fc for this perturbation
        pvals = p_values[:, target_idx]
        lfc = log2_fc[:, target_idx]
        
        # Compute FDR
        fdr = benjamini_hochberg(pvals)
        
        # Add rows for each gene
        for gene_idx in range(n_genes):
            rows.append({
                "perturbation": pert_name,
                "gene": gene_names[gene_idx],
                "p_value": pvals[gene_idx],
                "fdr": fdr[gene_idx],
                "log2fc": lfc[gene_idx],
            })
    
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(
        description="Compute differential expression genes using biosparse",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Specify perturbation column and control value
    python calc_degs.py data.h5ad --pert-col gene --ctrl NT -o degs.csv
    
    # Use t-test instead of Mann-Whitney U
    python calc_degs.py data.h5ad --pert-col treatment --ctrl DMSO --method ttest -o degs.csv
    
    # Filter by FDR and log2fc
    python calc_degs.py data.h5ad --pert-col gene --ctrl NT --fdr 0.05 --log2fc 1.0 -o degs.csv
    
    # Use specific layer
    python calc_degs.py data.h5ad --pert-col gene --ctrl NT --layer counts -o degs.csv
"""
    )
    
    # Required arguments
    parser.add_argument("h5ad_file", help="Input h5ad file path")
    parser.add_argument("--pert-col", required=True,
                        help="Column name in obs containing perturbation labels")
    parser.add_argument("--ctrl", required=True,
                        help="Value in pert-col that represents control group")
    
    # Output
    parser.add_argument("-o", "--output", required=True,
                        help="Output CSV file path")
    
    # Method selection
    parser.add_argument("--method", choices=["mwu", "ttest"], default="mwu",
                        help="Statistical test method (default: mwu)")
    
    # Data source
    parser.add_argument("--layer", help="Use specific layer instead of X")
    
    # Filtering options
    parser.add_argument("--fdr", type=float, default=None,
                        help="Filter results by FDR threshold")
    parser.add_argument("--log2fc", type=float, default=None,
                        help="Filter results by absolute log2fc threshold")
    
    # Cell filtering
    parser.add_argument("--exclude-col", help="Column in obs to use for excluding cells")
    parser.add_argument("--exclude", nargs="+", default=[],
                        help="Values in exclude-col to exclude from analysis")
    
    # Other options
    parser.add_argument("--perturbations", nargs="+", default=None,
                        help="Only compute DEGs for these perturbations (default: all)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show progress messages")
    
    args = parser.parse_args()
    
    # Load AnnData
    if args.verbose:
        print(f"Loading {args.h5ad_file}...", file=sys.stderr)
    
    adata = ad.read_h5ad(args.h5ad_file)
    
    if args.verbose:
        print(f"  Shape: {adata.shape[0]} cells × {adata.shape[1]} genes", file=sys.stderr)
    
    # Exclude cells based on label
    if args.exclude_col and args.exclude:
        if args.exclude_col not in adata.obs.columns:
            print(f"Error: Column '{args.exclude_col}' not found in obs", file=sys.stderr)
            sys.exit(1)
        
        exclude_set = set(args.exclude)
        keep_mask = ~adata.obs[args.exclude_col].isin(exclude_set)
        n_excluded = (~keep_mask).sum()
        adata = adata[keep_mask].copy()
        
        if args.verbose:
            print(f"  Excluded {n_excluded} cells with {args.exclude_col} in {args.exclude}", file=sys.stderr)
            print(f"  Remaining: {adata.shape[0]} cells", file=sys.stderr)
    
    # Check perturbation column
    if args.pert_col not in adata.obs.columns:
        print(f"Error: Column '{args.pert_col}' not found in obs", file=sys.stderr)
        print(f"Available columns: {list(adata.obs.columns)}", file=sys.stderr)
        sys.exit(1)
    
    pert_values = adata.obs[args.pert_col].values
    unique_perts = list(set(pert_values))
    
    # Check control value
    if args.ctrl not in unique_perts:
        print(f"Error: Control value '{args.ctrl}' not found in column '{args.pert_col}'", file=sys.stderr)
        print(f"Available values: {unique_perts}", file=sys.stderr)
        sys.exit(1)
    
    # Get perturbations to analyze
    if args.perturbations:
        perturbations = [p for p in args.perturbations if p in unique_perts and p != args.ctrl]
    else:
        perturbations = [p for p in unique_perts if p != args.ctrl]
    
    if args.verbose:
        print(f"  Control: {args.ctrl}", file=sys.stderr)
        print(f"  Perturbations: {len(perturbations)}", file=sys.stderr)
    
    # Build group_ids: 0 = control, 1..n = perturbations
    pert_to_group = {args.ctrl: 0}
    for i, p in enumerate(perturbations, start=1):
        pert_to_group[p] = i
    
    # Assign group IDs to cells
    group_ids = np.array([pert_to_group.get(p, -1) for p in pert_values], dtype=np.int64)
    
    # Filter cells with valid group assignment
    valid_mask = group_ids >= 0
    adata = adata[valid_mask].copy()
    group_ids = group_ids[valid_mask]
    
    if args.verbose:
        print(f"  Valid cells: {len(group_ids)}", file=sys.stderr)
        for i, p in enumerate([args.ctrl] + perturbations):
            n_cells = np.sum(group_ids == i)
            print(f"    Group {i} ({p}): {n_cells} cells", file=sys.stderr)
    
    # Load expression matrix
    if args.verbose:
        layer_info = f"layer={args.layer}" if args.layer else "X"
        print(f"Loading expression matrix ({layer_info})...", file=sys.stderr)
    
    X = load_expression_matrix(adata, layer=args.layer)
    gene_names = adata.var_names.tolist()
    
    # Convert to biosparse (transpose to genes x cells)
    if args.verbose:
        print(f"Converting to biosparse CSR (genes × cells)...", file=sys.stderr)
    
    csr = to_biosparse_csr(X, transpose=True)
    
    if args.verbose:
        print(f"  CSR shape: {csr.nrows} genes × {csr.ncols} cells", file=sys.stderr)
    
    # Compute DEGs
    if args.verbose:
        print(f"Computing DEGs (method={args.method})...", file=sys.stderr)
    
    df = compute_degs(
        csr,
        gene_names,
        group_ids,
        perturbations,
        method=args.method,
    )
    
    if args.verbose:
        print(f"  Total results: {len(df)} rows", file=sys.stderr)
    
    # Apply filters
    if args.fdr is not None:
        df = df[df["fdr"] <= args.fdr]
        if args.verbose:
            print(f"  After FDR filter (<= {args.fdr}): {len(df)} rows", file=sys.stderr)
    
    if args.log2fc is not None:
        df = df[df["log2fc"].abs() >= args.log2fc]
        if args.verbose:
            print(f"  After log2fc filter (|lfc| >= {args.log2fc}): {len(df)} rows", file=sys.stderr)
    
    # Sort by perturbation, then by FDR
    df = df.sort_values(["perturbation", "fdr"])
    
    # Save to CSV
    df.to_csv(args.output, index=False)
    
    if args.verbose:
        print(f"Results saved to {args.output}", file=sys.stderr)
        print(f"Done!", file=sys.stderr)


if __name__ == "__main__":
    main()
