"""
Fetch the external Visium datasets used by the zero-shot generalization sweep
(src/external_eval.py) into data/external/.

10x public datasets are pulled via scanpy.datasets.visium_sge (10x Genomics'
public space-ranger outputs). The DLPFC cross-donor slices (Br5595 = 151669/
151670, Br8100 = 151673/151674) are NOT fetched here — they come from
src/prepare_data.py (the same Figshare/spatialLIBD source as the training donor
Br5292 = 151507/151508):

    python src/prepare_data.py 151669 151670
    python src/prepare_data.py 151673 151674

Note on Human Kidney: the task asked for a human-kidney Visium pair, but 10x's
public Visium set has no human-kidney sample and no adjacent human-kidney
sections. V1_Mouse_Kidney (single section) is fetched for reference, but a single
section cannot be used with this cross-section model (self-warp is out of
distribution). The non-neural cross-tissue probe therefore uses the human
Breast Cancer Block A adjacent pair (Sections 1 & 2), which IS available.

Usage:
    python src/fetch_external.py
"""
from __future__ import annotations

from pathlib import Path

import scanpy as sc

EXT = Path(__file__).resolve().parent.parent / "data" / "external"

# 10x public Visium samples (adjacent pairs where a serial section exists).
SAMPLES = [
    "V1_Mouse_Brain_Sagittal_Posterior",
    "V1_Mouse_Brain_Sagittal_Posterior_Section_2",
    "V1_Breast_Cancer_Block_A_Section_1",
    "V1_Breast_Cancer_Block_A_Section_2",
    "V1_Mouse_Kidney",   # reference only (single section; not evaluable, see above)
]


def main() -> None:
    EXT.mkdir(parents=True, exist_ok=True)
    sc.settings.datasetdir = str(EXT / "_sge_cache")
    for sid in SAMPLES:
        out = EXT / f"{sid}.h5ad"
        if out.exists():
            print(f"[cache] {out.name}")
            continue
        print(f"[get]   {sid}")
        a = sc.datasets.visium_sge(sample_id=sid)
        a.var_names_make_unique()
        a.write_h5ad(out)
        print(f"        -> {out}  {a.n_obs} spots x {a.n_vars} genes")
    print("Done.")


if __name__ == "__main__":
    main()
