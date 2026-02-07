#!/usr/bin/env python3
"""
calc_hvgs.py - 使用 biosparse 高性能计算 Highly Variable Genes

Supported flavors:
    - seurat: Seurat flavor (binning + mean/std z-score)
    - cell_ranger: Cell Ranger flavor (percentile bins + median/MAD)
    - seurat_v3: Seurat V3 flavor (VST with LOESS regression)
    - pearson: Pearson residuals flavor

Usage:
    python calc_hvgs.py data.h5ad -n 2000 -o hvgs.json
    python calc_hvgs.py data.h5ad -n 2000 --flavor seurat_v3 --span 0.3
    python calc_hvgs.py data.h5ad -n 2000 --flavor pearson --theta 100
"""

import anndata as ad
import numpy as np
import scipy.sparse as sp
import json
import sys
import argparse

from biosparse import CSRF32, CSRF64
from biosparse.kernel import (
    hvg_seurat,
    hvg_cell_ranger,
    hvg_seurat_v3,
    hvg_pearson_residuals,
)


def load_expression_matrix(adata: ad.AnnData, layer: str = None, use_raw: bool = False):
    """
    Load expression matrix from AnnData.
    
    Returns:
        Tuple of (scipy sparse matrix in CSR format, gene_names)
    """
    if use_raw and adata.raw is not None:
        X = adata.raw.X
        gene_names = adata.raw.var_names.tolist()
    elif layer is not None:
        X = adata.layers[layer]
        gene_names = adata.var_names.tolist()
    else:
        X = adata.X
        gene_names = adata.var_names.tolist()
    
    # Ensure CSR format
    if sp.issparse(X):
        X = X.tocsr()
    else:
        X = sp.csr_matrix(X)
    
    return X, gene_names


def to_biosparse_csr(X: sp.csr_matrix, transpose: bool = True):
    """
    Convert scipy CSR to biosparse CSR.
    
    Args:
        X: scipy CSR matrix (cells x genes)
        transpose: If True, transpose to (genes x cells) for HVG computation
    
    Returns:
        biosparse CSR matrix
    """
    if transpose:
        # HVG functions expect genes x cells
        X = X.T.tocsr()
    
    # Choose precision based on dtype
    if X.dtype == np.float32:
        return CSRF32.from_scipy(X)
    else:
        # Convert to float64 if not float32
        X = X.astype(np.float64)
        return CSRF64.from_scipy(X)


def compute_hvgs(
    csr,
    gene_names: list,
    n_top_genes: int,
    flavor: str = "seurat",
    # Seurat params
    n_bins: int = 20,
    min_mean: float = 0.0125,
    max_mean: float = 3.0,
    min_disp: float = 0.5,
    max_disp: float = np.inf,
    # Seurat V3 params
    span: float = 0.3,
    # Pearson params
    theta: float = 100.0,
    clip: float = -1.0,
) -> dict:
    """
    Compute highly variable genes using biosparse.
    
    Returns:
        Dictionary with HVG results
    """
    n_genes = len(gene_names)
    
    if flavor == "seurat":
        indices, mask, means, dispersions, dispersions_norm = hvg_seurat(
            csr,
            n_top_genes=n_top_genes,
            n_bins=n_bins,
            min_mean=min_mean,
            max_mean=max_mean,
            min_disp=min_disp,
            max_disp=max_disp,
        )
        
        # Build result
        hvg_genes = [gene_names[i] for i in indices]
        
        result = {
            "flavor": flavor,
            "n_top_genes": n_top_genes,
            "highly_variable_genes": hvg_genes,
            "stats": {
                "means": {gene_names[i]: float(means[i]) for i in range(n_genes)},
                "dispersions": {gene_names[i]: float(dispersions[i]) for i in range(n_genes)},
                "dispersions_norm": {gene_names[i]: float(dispersions_norm[i]) for i in range(n_genes)},
            },
            "params": {
                "n_bins": n_bins,
                "min_mean": min_mean,
                "max_mean": max_mean,
                "min_disp": min_disp,
                "max_disp": max_disp if max_disp != np.inf else "inf",
            }
        }
        
    elif flavor == "cell_ranger":
        indices, mask, means, dispersions, dispersions_norm = hvg_cell_ranger(
            csr,
            n_top_genes=n_top_genes,
        )
        
        hvg_genes = [gene_names[i] for i in indices]
        
        result = {
            "flavor": flavor,
            "n_top_genes": n_top_genes,
            "highly_variable_genes": hvg_genes,
            "stats": {
                "means": {gene_names[i]: float(means[i]) for i in range(n_genes)},
                "dispersions": {gene_names[i]: float(dispersions[i]) for i in range(n_genes)},
                "dispersions_norm": {gene_names[i]: float(dispersions_norm[i]) for i in range(n_genes)},
            },
            "params": {}
        }
        
    elif flavor == "seurat_v3":
        indices, mask, means, variances, variances_norm = hvg_seurat_v3(
            csr,
            n_top_genes=n_top_genes,
            span=span,
        )
        
        hvg_genes = [gene_names[i] for i in indices]
        
        result = {
            "flavor": flavor,
            "n_top_genes": n_top_genes,
            "highly_variable_genes": hvg_genes,
            "stats": {
                "means": {gene_names[i]: float(means[i]) for i in range(n_genes)},
                "variances": {gene_names[i]: float(variances[i]) for i in range(n_genes)},
                "variances_norm": {gene_names[i]: float(variances_norm[i]) for i in range(n_genes)},
            },
            "params": {
                "span": span,
            }
        }
        
    elif flavor == "pearson":
        indices, mask, means, variances, residual_vars = hvg_pearson_residuals(
            csr,
            n_top_genes=n_top_genes,
            theta=theta,
            clip=clip,
        )
        
        hvg_genes = [gene_names[i] for i in indices]
        
        result = {
            "flavor": flavor,
            "n_top_genes": n_top_genes,
            "highly_variable_genes": hvg_genes,
            "stats": {
                "means": {gene_names[i]: float(means[i]) for i in range(n_genes)},
                "variances": {gene_names[i]: float(variances[i]) for i in range(n_genes)},
                "residual_variances": {gene_names[i]: float(residual_vars[i]) for i in range(n_genes)},
            },
            "params": {
                "theta": theta,
                "clip": clip if clip > 0 else "auto",
            }
        }
        
    else:
        raise ValueError(f"Unknown flavor: {flavor}. Choose from: seurat, cell_ranger, seurat_v3, pearson")
    
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Compute highly variable genes using biosparse",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Default seurat flavor
    python calc_hvgs.py data.h5ad -n 2000 -o hvgs.json
    
    # Seurat V3 (for raw counts)
    python calc_hvgs.py data.h5ad -n 2000 --flavor seurat_v3 --span 0.3 -o hvgs.json
    
    # Cell Ranger flavor
    python calc_hvgs.py data.h5ad -n 2000 --flavor cell_ranger -o hvgs.json
    
    # Pearson residuals
    python calc_hvgs.py data.h5ad -n 2000 --flavor pearson --theta 100 -o hvgs.json
    
    # Use specific layer
    python calc_hvgs.py data.h5ad -n 2000 --layer counts --flavor seurat_v3 -o hvgs.json
"""
    )
    
    # Required arguments
    parser.add_argument("h5ad_file", help="Input h5ad file path")
    parser.add_argument("-n", "--n-top-genes", type=int, default=2000,
                        help="Number of highly variable genes to select (default: 2000)")
    
    # Output
    parser.add_argument("-o", "--output", help="Output JSON file path (default: stdout)")
    
    # Flavor selection
    parser.add_argument("--flavor", choices=["seurat", "cell_ranger", "seurat_v3", "pearson"],
                        default="seurat", help="HVG selection flavor (default: seurat)")
    
    # Data source
    parser.add_argument("--layer", help="Use specific layer instead of X")
    parser.add_argument("--use-raw", action="store_true", help="Use adata.raw")
    
    # Cell filtering
    parser.add_argument("--exclude-col", help="Column in obs to use for excluding cells")
    parser.add_argument("--exclude", nargs="+", default=[],
                        help="Values in exclude-col to exclude from analysis")
    
    # Seurat params
    parser.add_argument("--n-bins", type=int, default=20,
                        help="Number of bins for seurat flavor (default: 20)")
    parser.add_argument("--min-mean", type=float, default=0.0125,
                        help="Min mean cutoff for seurat flavor (default: 0.0125)")
    parser.add_argument("--max-mean", type=float, default=3.0,
                        help="Max mean cutoff for seurat flavor (default: 3.0)")
    parser.add_argument("--min-disp", type=float, default=0.5,
                        help="Min dispersion cutoff for seurat flavor (default: 0.5)")
    parser.add_argument("--max-disp", type=float, default=np.inf,
                        help="Max dispersion cutoff for seurat flavor (default: inf)")
    
    # Seurat V3 params
    parser.add_argument("--span", type=float, default=0.3,
                        help="LOESS span for seurat_v3 flavor (default: 0.3)")
    
    # Pearson params
    parser.add_argument("--theta", type=float, default=100.0,
                        help="Theta parameter for pearson flavor (default: 100.0)")
    parser.add_argument("--clip", type=float, default=-1.0,
                        help="Clipping value for pearson flavor (default: auto = sqrt(n_cells))")
    
    # Output options
    parser.add_argument("--no-stats", action="store_true",
                        help="Don't include per-gene statistics in output (smaller file)")
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
    
    # Load expression matrix
    if args.verbose:
        layer_info = f"layer={args.layer}" if args.layer else ("raw" if args.use_raw else "X")
        print(f"Loading expression matrix ({layer_info})...", file=sys.stderr)
    
    X, gene_names = load_expression_matrix(adata, layer=args.layer, use_raw=args.use_raw)
    
    # Convert to biosparse
    if args.verbose:
        print(f"Converting to biosparse CSR (genes × cells)...", file=sys.stderr)
    
    csr = to_biosparse_csr(X, transpose=True)
    
    if args.verbose:
        print(f"  CSR shape: {csr.nrows} genes × {csr.ncols} cells", file=sys.stderr)
        print(f"  NNZ: {csr.nnz}, density: {csr.nnz / (csr.nrows * csr.ncols):.4f}", file=sys.stderr)
    
    # Compute HVGs
    if args.verbose:
        print(f"Computing HVGs (flavor={args.flavor}, n_top={args.n_top_genes})...", file=sys.stderr)
    
    result = compute_hvgs(
        csr,
        gene_names,
        n_top_genes=args.n_top_genes,
        flavor=args.flavor,
        # Seurat params
        n_bins=args.n_bins,
        min_mean=args.min_mean,
        max_mean=args.max_mean,
        min_disp=args.min_disp,
        max_disp=args.max_disp,
        # Seurat V3 params
        span=args.span,
        # Pearson params
        theta=args.theta,
        clip=args.clip,
    )
    
    # Remove stats if requested
    if args.no_stats:
        del result["stats"]
    
    # Output
    output_json = json.dumps(result, indent=2, ensure_ascii=False)
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(output_json)
        if args.verbose:
            print(f"Results saved to {args.output}", file=sys.stderr)
    else:
        print(output_json)
    
    if args.verbose:
        print(f"Done! Selected {len(result['highly_variable_genes'])} HVGs.", file=sys.stderr)


if __name__ == "__main__":
    main()
