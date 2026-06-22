"""
ARCA — data preparation for the spatialLIBD DLPFC dataset.

Downloads two *adjacent* DLPFC Visium slices (default: 151507 & 151508, the
consecutive 10 um sections from subject 1) and exports them as .h5ad into
data/, preserving the manual cortical-layer annotations under a canonical
`obs["layer"]` column for downstream alignment evaluation.

Source: "Visium DLPFC preprocessed .h5ad" (CellCharter benchmark distribution),
Figshare article 22004273 (CC BY 4.0). These are the spatialLIBD samples from
Maynard et al., Nat Neurosci 2021.

Usage:
    python src/prepare_data.py                  # default pair 151507/151508
    python src/prepare_data.py 151509 151510    # another adjacent pair
"""

from __future__ import annotations

import sys
from pathlib import Path

import anndata as ad
import requests

# --- paths -----------------------------------------------------------------
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_DIR = DATA_DIR / "raw"

# --- Figshare file map: sample_id -> direct download URL -------------------
# (article 22004273, file ids resolved 2026-06)
FIGSHARE_URLS = {
    "151507": "https://ndownloader.figshare.com/files/39055556",
    "151508": "https://ndownloader.figshare.com/files/39055589",
    "151509": "https://ndownloader.figshare.com/files/39055586",
    "151510": "https://ndownloader.figshare.com/files/39055583",
    "151669": "https://ndownloader.figshare.com/files/39055580",
    "151670": "https://ndownloader.figshare.com/files/39055577",
    "151671": "https://ndownloader.figshare.com/files/39055574",
    "151672": "https://ndownloader.figshare.com/files/39055571",
    "151673": "https://ndownloader.figshare.com/files/39055568",
    "151674": "https://ndownloader.figshare.com/files/39055565",
    "151675": "https://ndownloader.figshare.com/files/39055562",
    "151676": "https://ndownloader.figshare.com/files/39055559",
}

DEFAULT_PAIR = ("151507", "151508")

# Candidate obs columns that may hold the manual layer annotation, in priority
# order. spatialLIBD distributions have used several names over time.
LAYER_COL_CANDIDATES = [
    "sce.layer_guess",  # CellCharter/spatialLIBD SCE->h5ad export uses this
    "layer_guess",
    "layer_guess_reordered",
    "Layer",
    "layer",
    "ground_truth",
    "spatialLIBD",
    "Region",
    "annotation",
]


def download(sample_id: str) -> Path:
    """Download one sample's .h5ad into data/raw/, skipping if already valid."""
    if sample_id not in FIGSHARE_URLS:
        raise KeyError(
            f"Unknown sample {sample_id!r}. Known: {sorted(FIGSHARE_URLS)}"
        )
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = RAW_DIR / f"{sample_id}.h5ad"

    if dest.exists() and dest.stat().st_size > 1_000_000:
        print(f"  [cache] {dest.name} already present "
              f"({dest.stat().st_size / 1e6:.1f} MB) — skipping download")
        return dest

    url = FIGSHARE_URLS[sample_id]
    print(f"  [get]   {sample_id}.h5ad  <-  {url}")
    tmp = dest.with_suffix(".h5ad.part")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
                done += len(chunk)
                if total:
                    pct = 100 * done / total
                    print(f"\r          {done/1e6:6.1f}/{total/1e6:.1f} MB "
                          f"({pct:4.1f}%)", end="", flush=True)
        print()
    tmp.replace(dest)
    return dest


def detect_layer_column(adata: ad.AnnData) -> str | None:
    """Return the first matching layer-annotation column, or None."""
    for col in LAYER_COL_CANDIDATES:
        if col in adata.obs.columns:
            return col
    return None


def standardize(sample_id: str, src: Path) -> ad.AnnData:
    """Load a raw slice, normalize the layer column, and tag the sample id."""
    adata = ad.read_h5ad(src)
    adata.var_names_make_unique()
    adata.obs["sample_id"] = sample_id

    print(f"  shape          : {adata.n_obs} spots x {adata.n_vars} genes")
    print(f"  obs columns    : {list(adata.obs.columns)}")
    print(f"  obsm keys      : {list(adata.obsm.keys())}")

    layer_col = detect_layer_column(adata)
    if layer_col is None:
        print("  !! WARNING: no recognized layer-annotation column found.")
        print("     Inspect the obs columns above and extend "
              "LAYER_COL_CANDIDATES.")
        return adata

    # Canonical, string-typed categorical; preserve NaN as the literal "NA".
    layer = adata.obs[layer_col].astype("object")
    layer = layer.where(layer.notna(), "NA").astype(str).astype("category")
    adata.obs["layer"] = layer

    n_labeled = int((adata.obs["layer"] != "NA").sum())
    print(f"  layer column   : '{layer_col}' -> obs['layer']")
    print(f"  labeled spots  : {n_labeled}/{adata.n_obs}")
    print("  layer counts   :")
    for lab, cnt in adata.obs["layer"].value_counts().sort_index().items():
        print(f"      {lab:>8} : {cnt}")
    return adata


def main(pair: tuple[str, str]) -> None:
    print(f"ARCA data prep — adjacent DLPFC pair: {pair[0]} & {pair[1]}\n")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    for sample_id in pair:
        print(f"[{sample_id}] downloading ...")
        raw = download(sample_id)
        print(f"[{sample_id}] standardizing ...")
        adata = standardize(sample_id, raw)
        out = DATA_DIR / f"DLPFC_{sample_id}.h5ad"
        adata.write_h5ad(out)
        print(f"[{sample_id}] wrote -> {out}\n")

    print("Done. Exported slices:")
    for sample_id in pair:
        out = DATA_DIR / f"DLPFC_{sample_id}.h5ad"
        print(f"  {out}  ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 2:
        pair = (args[0], args[1])
    elif not args:
        pair = DEFAULT_PAIR
    else:
        sys.exit("Usage: python src/prepare_data.py [SAMPLE_A SAMPLE_B]")
    main(pair)
