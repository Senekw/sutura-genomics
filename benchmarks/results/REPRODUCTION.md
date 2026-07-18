# Baseline reproduction

**Overall: PASS**


_Run through `sutura_bench` on 5 datasets, seeds [0, 1, 2]. PASTE2/gate cells derive from cached bases; Sutura is checkpoint inference (arca_cross.pt)._

## Cross-check vs prior authoritative run (hybrid_validate.csv)

- Max |delta| across all matched PASTE2/gate cells: **0.0001 pitch** (MATCH, tolerance 0.01).

## Headline aggregates vs published values

| quantity | published | reproduced | delta | verdict |
|---|---|---|---|---|
| paste2_lodo_7grid_seed0 | 4.28 | 4.276 | -0.004 | OK |
| gate_rigid_lodo_5grid_seed0 | 3.73 | 3.729 | -0.001 | OK |
| gate_affine_lodo_7grid_seed0 | 3.08 | 3.076 | -0.004 | OK |

## Sutura in-distribution (Br5292, checkpoint arca_cross.pt)

- Sutura sev-avg (7-grid, seed 0): **0.762 pitch**
- PASTE2 sev-avg (same grid): 5.304 pitch
- Sutura beats PASTE2 in-distribution (expected: it is trained on this donor).
