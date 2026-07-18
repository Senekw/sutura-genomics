"""
Paths and global constants for the benchmark harness.

Everything is resolved relative to the repo root so the package works no matter
where it is invoked from. Importing this module also makes the repo's ``src/``
directory importable (the adapters and metric-parity tests import the canonical
research implementations from there).
"""

from __future__ import annotations

import sys
from pathlib import Path

# repo layout ---------------------------------------------------------------- #
BENCH_DIR = Path(__file__).resolve().parent.parent          # benchmarks/
ROOT = BENCH_DIR.parent                                       # repo root
SRC = ROOT / "src"
DATA = ROOT / "data"
EXTERNAL = DATA / "external"
RESULTS = ROOT / "results"                                   # legacy research CSVs
RESEARCH_RESULTS = ROOT / "research" / "results"
PASTE2_CACHE = RESEARCH_RESULTS / "paste2_cache"            # reuse existing bases

# benchmark-owned output locations (never write outside benchmarks/) --------- #
BENCH_RESULTS = BENCH_DIR / "results"
BENCH_CACHE = BENCH_DIR / "cache" / "paste2"                # our own base cache
REFERENCE_DIR = BENCH_DIR / "references"
REFERENCE_RESULTS = REFERENCE_DIR / "reference_results.json"
DATASET_CATALOGUE = REFERENCE_DIR / "dataset_catalogue.json"

# make the research code importable ------------------------------------------ #
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# standard evaluation grid (matches src/generalization_max.py::EVAL_SEVS and
# src/hybrid_validate.py). Severity is dimensionless, measured in spot-pitches;
# severity 0 = identity. Holding the seed fixed scales magnitude only.
DLPFC_SEVERITIES = [0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0]
OOD_SEVERITIES = [0.0, 2.0, 4.0, 6.0, 8.0]
# the 5-severity grid the headline gate number (3.73) was reported on
HEADLINE_SEVERITIES = [0.0, 2.0, 4.0, 6.0, 8.0]
DEFAULT_SEEDS = [0, 1, 2]

# PASTE2 wall-clock watchdog (seconds) - a torn high-spot-count pair can hang.
PASTE2_TIMEOUT = 900

# shared model/feature hyperparameters (match src/generalization_max.py::HP)
PCA_DIM = 50
KNN = 6


def ensure_dirs() -> None:
    """Create the benchmark-owned output directories (idempotent)."""
    for d in (BENCH_RESULTS, BENCH_CACHE, REFERENCE_DIR):
        d.mkdir(parents=True, exist_ok=True)
