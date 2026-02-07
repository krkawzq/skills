#!/usr/bin/env python3
"""
anndata_info.py - 快速查看 AnnData 文件的元信息

Usage:
    python anndata_info.py <h5ad_file>                    # 显示基本信息
    python anndata_info.py <h5ad_file> "print(adata.obs)" # 执行自定义语句
    python anndata_info.py <h5ad_file> "adata.obs.head()" # 支持表达式
"""

import anndata as ad
import numpy as np
import scipy.sparse as sp
import sys


def get_type_name(obj) -> str:
    """Get a readable type name for an object.
    
    Prioritizes isinstance checks for common matrix types to avoid
    h5py.Dataset being shown when using backed mode.
    """
    # Check sparse matrix types first
    if sp.issparse(obj):
        if sp.isspmatrix_csr(obj):
            return "scipy.sparse.csr_matrix"
        elif sp.isspmatrix_csc(obj):
            return "scipy.sparse.csc_matrix"
        elif sp.isspmatrix_coo(obj):
            return "scipy.sparse.coo_matrix"
        else:
            return f"scipy.sparse.{type(obj).__name__}"
    
    # Check numpy array
    if isinstance(obj, np.ndarray):
        return "numpy.ndarray"
    
    # Fallback to type name
    t = type(obj)
    module = t.__module__
    name = t.__name__
    if module == 'builtins':
        return name
    return f"{module}.{name}"


def format_dict_types(d: dict, max_items: int = 20) -> list[str]:
    """Format dictionary keys with their value types."""
    items = list(d.items())[:max_items]
    lines = []
    for k, v in items:
        lines.append(f"    - '{k}': {get_type_name(v)}")
    if len(d) > max_items:
        lines.append(f"    ... and {len(d) - max_items} more")
    return lines


def print_info(adata: ad.AnnData):
    """Print comprehensive AnnData metadata."""
    
    print("=" * 60)
    print(f"AnnData Info")
    print("=" * 60)
    
    # Basic shape
    print(f"\n## Shape")
    print(f"  n_obs × n_vars = {adata.n_obs} × {adata.n_vars}")
    
    # X matrix
    print(f"\n## X (expression matrix)")
    if adata.X is not None:
        print(f"  type:  {get_type_name(adata.X)}")
        print(f"  shape: {adata.X.shape}")
        print(f"  dtype: {adata.X.dtype}")
    else:
        print("  X is None")
    
    # obs (cell metadata)
    print(f"\n## obs (cell metadata) - {len(adata.obs.columns)} columns")
    for col in adata.obs.columns:
        dtype = adata.obs[col].dtype
        n_unique = adata.obs[col].nunique()
        print(f"    - '{col}': {dtype} ({n_unique} unique)")
    
    # var (gene metadata)
    print(f"\n## var (gene/feature metadata) - {len(adata.var.columns)} columns")
    for col in adata.var.columns:
        dtype = adata.var[col].dtype
        n_unique = adata.var[col].nunique()
        print(f"    - '{col}': {dtype} ({n_unique} unique)")
    
    # obsm (cell embeddings)
    print(f"\n## obsm (cell embeddings) - {len(adata.obsm)} items")
    for key in adata.obsm.keys():
        arr = adata.obsm[key]
        print(f"    - '{key}': {get_type_name(arr)}, shape={arr.shape}, dtype={arr.dtype}")
    
    # varm (gene embeddings)
    print(f"\n## varm (gene embeddings) - {len(adata.varm)} items")
    for key in adata.varm.keys():
        arr = adata.varm[key]
        print(f"    - '{key}': {get_type_name(arr)}, shape={arr.shape}, dtype={arr.dtype}")
    
    # obsp (cell-cell graphs)
    print(f"\n## obsp (cell-cell graphs) - {len(adata.obsp)} items")
    for key in adata.obsp.keys():
        arr = adata.obsp[key]
        print(f"    - '{key}': {get_type_name(arr)}, shape={arr.shape}, dtype={arr.dtype}")
    
    # varp (gene-gene graphs)
    print(f"\n## varp (gene-gene graphs) - {len(adata.varp)} items")
    for key in adata.varp.keys():
        arr = adata.varp[key]
        print(f"    - '{key}': {get_type_name(arr)}, shape={arr.shape}, dtype={arr.dtype}")
    
    # layers
    print(f"\n## layers - {len(adata.layers)} items")
    for key in adata.layers.keys():
        arr = adata.layers[key]
        print(f"    - '{key}': {get_type_name(arr)}, shape={arr.shape}, dtype={arr.dtype}")
    
    # uns (unstructured metadata)
    print(f"\n## uns (unstructured metadata) - {len(adata.uns)} keys")
    for line in format_dict_types(adata.uns):
        print(line)
    
    print("\n" + "=" * 60)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    path = sys.argv[1]
    
    # Load AnnData
    adata = ad.read_h5ad(path, backed='r')
    
    if len(sys.argv) == 2:
        # No extra arguments - print info
        print_info(adata)
    else:
        # Extra arguments - execute as Python code
        # Join all remaining arguments as code
        code = " ".join(sys.argv[2:])
        
        # Create a namespace with adata available
        namespace = {
            'adata': adata,
            'ad': ad,
            'print': print,
        }
        
        # Try eval first (for expressions), then exec (for statements)
        try:
            result = eval(code, namespace)
            if result is not None:
                print(result)
        except SyntaxError:
            # Not an expression, try as statement
            exec(code, namespace)


if __name__ == "__main__":
    main()
