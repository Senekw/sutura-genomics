"""
sutura_bench - the permanent, reusable evaluation infrastructure for spatial
transcriptomics alignment methods (Sutura, PASTE2, the gate, and future methods).

One harness runs any alignment method against a standard suite of datasets,
severities, and seeds, producing directly comparable median-registration-error
numbers. See benchmarks/README.md for the one-command entry points.

Design contract (the whole package hangs off this):
  A *method* takes a Task (reference AnnData A, moving AnnData B, the moving
  spots' possibly-warped coordinates, shared features, spot pitch, and - for
  refiners - a precomputed base alignment) and returns predicted A-frame
  coordinates, one (x, y) per moving spot, in A's pixel frame. It is scored by
  metrics.registration_error against the task's ground truth (array-bridge for
  real serial sections, warp-field for the self-warp degenerate case).

Nothing here reimplements alignment or metric math: the adapters and metrics
import the repo's canonical implementations (src/scoring.py, src/gate_refine.py,
src/train_cross.py, src/warp_slice.py, ...) so the benchmark measures exactly
what the research code produces.
"""

from __future__ import annotations

__version__ = "1.0.0"

__all__ = ["__version__"]
