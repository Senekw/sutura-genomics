"""Fetch a public 10x Visium dataset with adjacent serial sections for the
zero-shot external-generalization test, and save clean .h5ad copies into
research/data/external/.

Primary: 10x "Human Breast Cancer (Block A)" — Section 1 & Section 2 are two
adjacent serial sections of the same tissue block, both distributed by scanpy's
visium_sge() downloader.

Run: C:/Users/karti/arca/.venv/Scripts/python.exe research/validation/_fetch_external.py
"""
from pathlib import Path
import numpy as np
import scanpy as sc

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "data" / "external"
EXT.mkdir(parents=True, exist_ok=True)
sc.settings.datasetdir = EXT / "_cache"

SAMPLES = {
    "breast_A_S1": "V1_Breast_Cancer_Block_A_Section_1",
    "breast_A_S2": "V1_Breast_Cancer_Block_A_Section_2",
}

for tag, sample_id in SAMPLES.items():
    print(f"\n=== {tag} ({sample_id}) ===")
    a = sc.datasets.visium_sge(sample_id=sample_id)
    a.var_names_make_unique()
    print("  shape:", a.shape)
    print("  obsm keys:", list(a.obsm.keys()))
    print("  obs cols:", [c for c in a.obs.columns][:12])
    print("  X dtype/min/max:", a.X.dtype,
          float(a.X.min()), float(a.X.max()))
    has_arr = "array_row" in a.obs.columns and "array_col" in a.obs.columns
    print("  has array_row/col:", has_arr)
    if "spatial" in a.obsm:
        sp = np.asarray(a.obsm["spatial"])[:3]
        print("  spatial sample:\n", sp)
    out = EXT / f"{tag}.h5ad"
    a.write_h5ad(out)
    print(f"  wrote -> {out}  ({out.stat().st_size/1e6:.0f} MB)")

print("\nDONE.")
