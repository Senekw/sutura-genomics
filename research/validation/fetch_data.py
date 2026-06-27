"""Download + standardize the DLPFC slices needed for Sutura validation.

Mirrors src/prepare_data.py exactly (same Figshare article 22004273, same layer
standardization) so the data is bit-identical to what the original pipeline used.
Downloads the 6 slices that appear in the headline + LOO + 3-donor-LOO runs.
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import anndata as ad
import requests

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
RAW_DIR = DATA_DIR / "raw"

FIGSHARE_URLS = {
    "151507": "https://ndownloader.figshare.com/files/39055556",
    "151508": "https://ndownloader.figshare.com/files/39055589",
    "151669": "https://ndownloader.figshare.com/files/39055580",
    "151670": "https://ndownloader.figshare.com/files/39055577",
    "151673": "https://ndownloader.figshare.com/files/39055568",
    "151674": "https://ndownloader.figshare.com/files/39055565",
}
LAYER_COL_CANDIDATES = [
    "sce.layer_guess", "layer_guess", "layer_guess_reordered", "Layer",
    "layer", "ground_truth", "spatialLIBD", "Region", "annotation",
]

def download(sample_id: str) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = RAW_DIR / f"{sample_id}.h5ad"
    if dest.exists() and dest.stat().st_size > 1_000_000:
        print(f"  [cache] {dest.name} ({dest.stat().st_size/1e6:.1f} MB)")
        return dest
    url = FIGSHARE_URLS[sample_id]
    print(f"  [get]   {sample_id}.h5ad <- {url}")
    tmp = dest.with_suffix(".h5ad.part")
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 20):
                fh.write(chunk); done += len(chunk)
                if total:
                    print(f"\r          {done/1e6:6.1f}/{total/1e6:.1f} MB", end="", flush=True)
        print()
    tmp.replace(dest)
    return dest

def detect_layer_column(adata):
    for col in LAYER_COL_CANDIDATES:
        if col in adata.obs.columns:
            return col
    return None

def standardize(sample_id: str, src: Path):
    adata = ad.read_h5ad(src)
    adata.var_names_make_unique()
    adata.obs["sample_id"] = sample_id
    print(f"  shape {adata.n_obs} x {adata.n_vars}")
    col = detect_layer_column(adata)
    if col is None:
        print(f"  !! no layer column; obs cols = {list(adata.obs.columns)}")
        return adata
    layer = adata.obs[col].astype("object")
    layer = layer.where(layer.notna(), "NA").astype(str).astype("category")
    adata.obs["layer"] = layer
    n = int((adata.obs["layer"] != "NA").sum())
    print(f"  layer col '{col}' -> obs['layer'] ({n}/{adata.n_obs} labeled)")
    return adata

def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for sid in FIGSHARE_URLS:
        out = DATA_DIR / f"DLPFC_{sid}.h5ad"
        if out.exists() and out.stat().st_size > 1_000_000:
            print(f"[{sid}] already standardized -> {out.name}")
            continue
        print(f"[{sid}] downloading ...")
        raw = download(sid)
        print(f"[{sid}] standardizing ...")
        adata = standardize(sid, raw)
        adata.write_h5ad(out)
        print(f"[{sid}] wrote -> {out} ({out.stat().st_size/1e6:.1f} MB)\n")
    print("All slices ready:")
    for sid in FIGSHARE_URLS:
        out = DATA_DIR / f"DLPFC_{sid}.h5ad"
        print(f"  {out.name}: {out.stat().st_size/1e6:.1f} MB")

if __name__ == "__main__":
    main()
