# 2-pairs-per-donor LODO — findings

**Date:** 2026-07-01
**Verdict:** PARTIAL (consistent across all 3 folds)

## Question
Does giving each *training* donor a **second adjacent slice-pair** close the
cross-donor generalization gap (RESUME.md lever c)? The original 3-donor
leave-one-donor-out (`arca_loo3_*`) trained on ONE pair per donor and stayed
1080–1557 px on the unseen donor (1.9–3.0× PASTE2).

## Method
- 3 folds (hold out S1/S2/S3) × 2 feature modes (`global`, `perslice`). Each fold
  trains on **both** adjacent pairs of the two non-held-out donors (4 training
  pairs) and is tested on the held-out donor's canonical first pair.
- **Controlled comparison:** per-pair supervision held constant vs the 1-pair run
  — 100 epochs × 48 steps = 4800 steps / 4 pairs ≈ 1200 steps/pair (the 1-pair run
  used 24 steps / 2 pairs). So a change in the held-out curve reflects *more pairs*,
  not more gradient.
- 5-seed eval (warp seeds 0, 9999, 10000–10002) → 95% CIs. `run_lodo_2pair.ps1`
  (+ `run_lodo2_phase2.ps1`, which recovered `global_heldS3` after it hit the
  90-min watchdog). Threads pinned to 6.
- Result: `sutura_multiseed_lodo_2pair.csv`. Primary readout = `perslice`
  (batch-robust); `global` = control.

## Result (perslice, median px, 5-seed 95% CI)
`f` = fraction of the OT gap closed = (m1 − m2) / (m1 − PASTE2).

| Fold | 1-pair m1 (sev0→8) | 2-pair m2 (sev0→8) | PASTE2 (sev0→8) | f (sev0→8) | m2 vs OT |
|------|--------------------|--------------------|-----------------|------------|----------|
| S1   | 1082 → 1242        | **875 → 929**      | 658 → 838       | 0.49 → 0.77 | 1.3→1.1× |
| S2   | 1182 → 1198        | **783 → 843**      | 526 → 691       | 0.61 → 0.70 | 1.5→1.2× |
| S3   | 1259 → 1380        | **973 → 1040**     | 407 → 551       | 0.34 → 0.41 | 2.4→1.9× |

CIs are 3–53 px (< the 200–400 px improvement over 1-pair), so the improvement is
highly significant on every fold.

## Interpretation
- **All 3 folds = PARTIAL:** m2 is significantly **below** the 1-pair baseline AND
  significantly **above** PASTE2 (0.15 < f < 1.0). More pairs/donor is a real,
  significant lever — it closes ⅓–¾ of the OT gap and cuts held-out error 25–34% —
  **but Sutura still loses to PASTE2 on every unseen donor (1.1–2.4× OT).**
- **No OT parity, even in the torn regime:** at sev8 the m2 CI never dips below
  PASTE2 on any fold (closest: S1 929±53 → [876, 982] vs 838).
- `global` control also improved (1071–1230 px) but stayed worse than `perslice`
  everywhere — consistent with the batch-robustness story.

## Decision
Positive **scaling evidence**, not a headline change: the paper's honest claim
stands (Sutura is not yet competitive with OT out-of-sample). Doubling *pairs*
plateaued short of parity, so the next lever is **more distinct donors** (and/or
stacking the contrastive correspondence loss), not more pairs of the same donors.
