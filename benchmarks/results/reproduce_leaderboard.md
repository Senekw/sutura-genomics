# Benchmark: baseline reproduction

_Source: `reproduce.csv` | severity-averaged median registration error (spot-pitches), lower = better. `+/- std` is across seeds._

## DLPFC leave-one-donor-out (real serial, array-bridge GT)

| method | LODO-mean error (pitch) | seeds |
|---|---|---|
| gate_affine | 3.10 +/- 0.05 | 3 |
| gate_rigid | 3.42 +/- 0.16 | 3 |
| paste2 | 4.26 +/- 0.04 | 3 |
| sutura | 12.02 +/- 0.04 | 3 |

## Per-dataset (real serial sections, array-bridge GT)

| method | Br5292 | Br5595 | Br8100 | breast | mousebrain |
|---|---|---|---|---|---|
| sutura | 0.75 +/- 0.03 | 16.32 +/- 0.08 | 18.98 +/- 0.03 | 20.07 +/- 0.03 | 14.85 +/- 0.04 |
| gate_affine | 4.11 +/- 0.03 | 2.84 +/- 0.10 | 2.35 +/- 0.05 | 3.21 +/- 0.04 | 5.26 +/- 0.29 |
| gate_rigid | 4.40 +/- 0.12 | 3.19 +/- 0.21 | 2.66 +/- 0.16 | 3.32 +/- 0.19 | 5.35 +/- 0.34 |
| paste2 | 5.29 +/- 0.03 | 4.27 +/- 0.07 | 3.21 +/- 0.11 | 3.67 +/- 0.15 | 5.57 +/- 0.13 |

## Caveats

- 5 datasets, 3 seed(s), severities [0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0].
- Ground truth is the Visium array bridge (real serial) or the known synthetic warp field (self-warp). All GT is Visium-array-specific.
- Synthetic tears model tissue damage; real tears may differ. The gate is a refinement of a base aligner (PASTE2), not a standalone aligner.
