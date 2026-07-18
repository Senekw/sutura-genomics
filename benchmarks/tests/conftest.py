"""Make the benchmarks package importable and expose data-availability helpers."""
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
if str(BENCH) not in sys.path:
    sys.path.insert(0, str(BENCH))

import pytest  # noqa: E402
from sutura_bench import datasets  # noqa: E402


def has_data(dataset_id: str) -> bool:
    try:
        return datasets.is_available(datasets.get(dataset_id))
    except Exception:
        return False


requires_dlpfc = pytest.mark.skipif(
    not has_data("Br8100"), reason="DLPFC data not on disk")
requires_cache = pytest.mark.skipif(
    not (BENCH.parent / "research" / "results" / "paste2_cache").exists(),
    reason="PASTE2 cache not present")
