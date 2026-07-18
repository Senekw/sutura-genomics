"""
The standardized dataset registry.

Every benchmarkable dataset is catalogued here with the metadata needed to keep
results comparable and to stop incomparable regimes from ever being averaged
together. The two regimes are load-bearing:

  * ``real_serial`` - two physically distinct adjacent sections that share the
    Visium array grid. Ground truth is the array bridge (matching spots by
    identical ``array_row``/``array_col``). This is the honest cross-section
    regime every headline number uses.
  * ``self_warp`` - a single section aligned against a synthetically warped copy
    of itself. Ground truth is the known warp field. DEGENERATE for refinement
    methods (an aligner that matches identical expression is near-exact), so
    these are reported separately and flagged, never pooled with real_serial.

A dataset is *available* iff its section file(s) resolve on disk. ``catalogue()``
introspects each available dataset's ``.h5ad`` (spot counts, gene count, whether
an array grid / layer labels are present) and caches the result to
``references/dataset_catalogue.json`` so ``sutura-bench list`` is instant.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from . import config


@dataclass(frozen=True)
class DatasetSpec:
    id: str
    tissue: str
    platform: str
    regime: str                 # "real_serial" | "self_warp"
    gt: str                     # "array_bridge" | "self_warp"
    ref: str                    # reference section file stem
    mov: str                    # moving section file stem (== ref for self_warp)
    donor: Optional[str] = None
    group: str = "other"        # "dlpfc" | "ood" | "self_warp"
    adjacency: str = ""         # human description of section relationship
    has_layers: bool = False    # cortical-layer annotations available
    notes: str = ""

    @property
    def degenerate(self) -> bool:
        return self.regime == "self_warp"


# --------------------------------------------------------------------------- #
# file resolution
# --------------------------------------------------------------------------- #
_SEARCH_DIRS = [config.DATA, config.EXTERNAL, config.ROOT / "research" / "data" / "atlas"]


def resolve_section(stem: str) -> Optional[Path]:
    """Return the .h5ad path for a section stem, searching data/, data/external/,
    and the atlas cache. None if not present on disk."""
    for d in _SEARCH_DIRS:
        p = d / f"{stem}.h5ad"
        if p.exists():
            return p
    return None


# --------------------------------------------------------------------------- #
# the registry (defined in code; the sole source of truth)
# --------------------------------------------------------------------------- #
def _dlpfc(donor, ref, mov, second=False):
    tag = donor + ("b" if second else "")
    which = "second" if second else "first"
    return DatasetSpec(
        id=tag, tissue="human DLPFC", platform="Visium", regime="real_serial",
        gt="array_bridge", ref=ref, mov=mov, donor=donor, group="dlpfc",
        adjacency=f"{which} adjacent serial pair (consecutive 10um sections)",
        has_layers=True,
        notes="spatialLIBD (Maynard 2021). In-distribution for Sutura.")


_REGISTRY: list[DatasetSpec] = [
    # --- DLPFC real serial cross pairs (3 donors x 2 pairs) ----------------- #
    _dlpfc("Br5292", "DLPFC_151507", "DLPFC_151508"),
    _dlpfc("Br5595", "DLPFC_151669", "DLPFC_151670"),
    _dlpfc("Br8100", "DLPFC_151673", "DLPFC_151674"),
    _dlpfc("Br5292", "DLPFC_151509", "DLPFC_151510", second=True),
    _dlpfc("Br5595", "DLPFC_151671", "DLPFC_151672", second=True),
    _dlpfc("Br8100", "DLPFC_151675", "DLPFC_151676", second=True),

    # --- off-distribution real serial pairs -------------------------------- #
    DatasetSpec(
        id="breast", tissue="human breast cancer", platform="Visium",
        regime="real_serial", gt="array_bridge",
        ref="V1_Breast_Cancer_Block_A_Section_1",
        mov="V1_Breast_Cancer_Block_A_Section_2",
        group="ood", adjacency="real serial pair (10x Block A s1/s2)",
        notes="Off-distribution. ~95% gene overlap with the DLPFC basis."),
    DatasetSpec(
        id="mousebrain", tissue="mouse brain", platform="Visium",
        regime="real_serial", gt="array_bridge",
        ref="V1_Mouse_Brain_Sagittal_Posterior",
        mov="V1_Mouse_Brain_Sagittal_Posterior_Section_2",
        group="ood", adjacency="real serial pair (sagittal posterior s1/s2)",
        notes="Off-distribution, cross-species. ~0% gene overlap; hardest OOD."),

    # --- self-warp degenerate datasets (reported separately) --------------- #
    DatasetSpec(
        id="mousekidney_self", tissue="mouse kidney", platform="Visium",
        regime="self_warp", gt="self_warp",
        ref="V1_Mouse_Kidney", mov="V1_Mouse_Kidney",
        group="self_warp", adjacency="single section warped against itself",
        notes="DEGENERATE self-alignment. Not a valid refinement test; the base "
              "aligner matches identical expression and is ~exact."),
]

# self-warp datasets available only from the atlas cache (single Visium sections).
# Registered so a self-warp sweep can include them when the cache is present.
_ATLAS_SELF = {
    "cerebellum_self": ("human cerebellum", "Parent_Visium_Human_Cerebellum"),
    "glioblastoma_self": ("human glioblastoma", "Parent_Visium_Human_Glioblastoma"),
    "ovarian_self": ("human ovarian cancer", "Parent_Visium_Human_OvarianCancer"),
    "colorectal_self": ("human colorectal cancer", "Parent_Visium_Human_ColorectalCancer"),
    "spinalcord_self": ("human spinal cord", "Parent_Visium_Human_SpinalCord"),
    "lymphnode_self": ("human lymph node", "V1_Human_Lymph_Node"),
    "heart_self": ("human heart", "V1_Human_Heart"),
}
for _id, (_tissue, _stem) in _ATLAS_SELF.items():
    _REGISTRY.append(DatasetSpec(
        id=_id, tissue=_tissue, platform="Visium", regime="self_warp",
        gt="self_warp", ref=_stem, mov=_stem, group="self_warp",
        adjacency="single section warped against itself",
        notes="DEGENERATE self-alignment (atlas cache). Reported separately."))


_BY_ID = {d.id: d for d in _REGISTRY}


# --------------------------------------------------------------------------- #
# public accessors
# --------------------------------------------------------------------------- #
def all_specs() -> list[DatasetSpec]:
    return list(_REGISTRY)


def get(dataset_id: str) -> DatasetSpec:
    if dataset_id not in _BY_ID:
        raise KeyError(f"unknown dataset '{dataset_id}'. Known: {sorted(_BY_ID)}")
    return _BY_ID[dataset_id]


def is_available(spec: DatasetSpec) -> bool:
    return resolve_section(spec.ref) is not None and resolve_section(spec.mov) is not None


def available_specs(group: Optional[str] = None, regime: Optional[str] = None) -> list[DatasetSpec]:
    out = [d for d in _REGISTRY if is_available(d)]
    if group:
        out = [d for d in out if d.group == group]
    if regime:
        out = [d for d in out if d.regime == regime]
    return out


def default_suite() -> list[DatasetSpec]:
    """The standard comparable suite: real-serial datasets only (DLPFC + OOD).
    Self-warp datasets are excluded by design - opt in with regime='self_warp'."""
    return available_specs(regime="real_serial")


# --------------------------------------------------------------------------- #
# introspection -> catalogue
# --------------------------------------------------------------------------- #
def introspect(spec: DatasetSpec) -> dict:
    """Read the section file(s) and record measured metadata (spot counts, gene
    count, array-grid presence, layer labels). Requires anndata (the venv)."""
    import anndata as ad
    import numpy as np

    rec = {**asdict(spec), "available": is_available(spec)}
    if not rec["available"]:
        return rec
    ref_p = resolve_section(spec.ref)
    A = ad.read_h5ad(ref_p)
    has_grid = "array_row" in A.obs and "array_col" in A.obs
    rec.update(n_spots_ref=int(A.n_obs), n_genes=int(A.n_vars),
               has_array_grid=bool(has_grid))
    if spec.regime == "real_serial":
        B = ad.read_h5ad(resolve_section(spec.mov))
        rec["n_spots_mov"] = int(B.n_obs)
        if has_grid and "array_row" in B.obs:
            key = {(int(r), int(c)) for r, c in zip(A.obs["array_row"], A.obs["array_col"])}
            bridged = sum((int(r), int(c)) in key
                          for r, c in zip(B.obs["array_row"], B.obs["array_col"]))
            rec["bridge_coverage"] = round(bridged / max(B.n_obs, 1), 4)
    else:
        rec["n_spots_mov"] = int(A.n_obs)
        rec["bridge_coverage"] = 1.0  # self-bridge is perfect by construction
    return rec


def catalogue(refresh: bool = False) -> list[dict]:
    """Return the introspected metadata for every registered dataset, cached to
    references/dataset_catalogue.json. Pass refresh=True to rebuild."""
    config.ensure_dirs()
    cache = config.DATASET_CATALOGUE
    if cache.exists() and not refresh:
        return json.loads(cache.read_text())
    recs = [introspect(d) for d in _REGISTRY]
    cache.write_text(json.dumps(recs, indent=2))
    return recs
