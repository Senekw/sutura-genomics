# Sutura Genomics (model codename: Sutura) — resume checkpoint

> Rebranded: the product is **Sutura Genomics**. "Sutura" below is the internal
> model codename and is kept in code/checkpoint names for reproducibility.

================================================================================
## UPDATE 2026-06-22 (later) — 3-DONOR LEAVE-ONE-OUT — STILL NEGATIVE, deeper
================================================================================

Ran the full 3-donor leave-one-out to try to FIX the single-donor transfer
failure (section below). Trained the shared encoder on TWO donors and evaluated
on the held-out third, across all 3 folds, under two feature-standardization
modes. **Multi-donor training did NOT fix generalization, and neither did the
batch-correction variant.** But it changed the failure mechanism in an
informative way. Sutura still loses to PASTE2 on every unseen donor.

### Setup
- Downloaded subj3 pair 151673/151674 (so all 3 donors on disk now).
- One pair per donor: S1=151507/08, S2=151669/70, S3=151673/74.
- 3 folds (leave-out S1 / S2 / S3), each trains on the OTHER two donors' pairs;
  100 epochs x 24 steps (~1200 steps/pair, matches the single-pair supervision).
- Two feature modes (`--feature-mode`, src/train_cross_loo.py):
  * `global`   = standardize SVD embedding by TRAINING-pooled stats (control).
  * `perslice` = standardize each slice by its OWN stats (cheap batch correction,
    re-centers every slice incl. the unseen donor to zero-mean/unit-var).
- PASTE2 baselines on all 3 held-out pairs (subj3 sweep added this run).
- Orchestrated by run_loo_3donor.ps1 (ran as detached scheduled task Sutura_LOO3);
  finished 2026-06-22 16:05 UTC, 0 failures.

### Result — registration error MEDIAN (px), tear regime, sev0->8
| held-out | Sutura in-sample | Sutura held-out (global) | Sutura held-out (perslice) | PASTE2 held-out |
|----------|----------------|------------------------|--------------------------|-----------------|
|   S1     |   121 -> 148   |      1254 -> 1421       |       1082 -> 1242        |    658 -> 838   |
|   S2     |   110 -> 130   |      1164 -> 1289       |       1182 -> 1198        |    526 -> 691   |
|   S3     |    82 ->  98   |      1397 -> 1557       |       1259 -> 1380        |    407 -> 551   |
(figure: results/arca_loo3_summary.png — one panel per held-out donor)

### Verdict (three clean conclusions)
1. **In-sample is excellent, held-out is not.** Trained on 2 donors, Sutura stays
   SUB-PITCH on its training donors (82-148 px) but lands ~8-11 spot pitches out
   on the unseen donor (1080-1557 px) in EVERY fold. Adding a second training
   donor did NOT buy donor-invariance.
2. **Per-slice batch correction helps only marginally.** perslice beats global on
   2 of 3 folds (S1 -180px, S3 -140px) and is ~flat-but-equal on S2 — a real but
   small (~10-15%) gain that does not close the ~1000px gap.
3. **Sutura loses to PASTE2 on every unseen donor.** PASTE2 (unsupervised, no
   train/test gap) is 407-838 px held-out; Sutura is 2-3x worse on all 3 donors.
   Sutura's earlier "win" was entirely contingent on training on the test tissue.

### Mechanism CHANGED vs single-donor (diagnosed, fold S1, sev0)
- Single-donor run: attention near-UNIFORM (eff. support 2367/3661 A-spots) ->
  predictions blur to the tissue centroid -> ~1500px.
- 3-donor run: attention is now SHARP (eff. support 301 global / 404 perslice of
  4226) but matches held-out B spots to the WRONG A-locations -> still ~1250px.
  => Multi-donor training fixed the COLLAPSE (encoder is now discriminative) but
  the learned correspondences are CONFIDENT-BUT-WRONG on unseen tissue. The gap
  is in cross-donor correspondence alignment, not feature non-discrimination.

### What this means for next steps (the real fix is harder than batch-norming)
The problem is the learned matching does not transfer, even with discriminative
features. Promising directions, in rough priority:
(a) explicit correspondence supervision that is donor-invariant — e.g. a
    contrastive / InfoNCE loss tying B-spot embeddings to their array-bridge A
    partner, so the SIMILARITY GEOMETRY (not just per-spot features) transfers;
(b) stronger expression integration BEFORE the encoder (Harmony/Scanorama across
    all training donors, projected onto the held-out donor) rather than the
    lightweight perslice z-score;
(c) more donors (the dataset has 12 slices / 6 pairs; we used 3 pairs) so the
    encoder sees more cross-donor variation;
(d) geometry-aware matching (optimal-transport head on embeddings, i.e. graft
    PASTE2's strength onto Sutura) since pure soft-attention mismatches across
    donors.
Honest read: Sutura as a learned registrar is NOT yet competitive with PASTE2
out-of-sample. The in-sample win is real but does not generalize; (a) is the
most direct test of whether the architecture can be salvaged.

### Artifacts (results/)
- arca_loo3_<mode>_test<S1|S2|S3>_{test,train}_curve.csv  (12 curves) + .pt (6).
- arca_loo3_summary.png — 3-panel figure (in-sample / global / perslice / PASTE2).
- sweep_deformation_cross_tear_subj3.csv — PASTE2 baseline on subj3 (new).
- loo3_run.log, loo3_DONE.txt — orchestration log + completion marker.
- Code: src/train_cross_loo.py (added --feature-mode), src/overlay_loo3.py (NEW),
  run_loo_3donor.ps1 (NEW orchestration).

================================================================================
## UPDATE 2026-06-22 — LEAVE-ONE-OUT GENERALIZATION TEST (caveat #2) — NEGATIVE
================================================================================

Ran the cross-sample generalization test that caveat #2 (below) demanded. The
result is a clean NEGATIVE: **Sutura's in-sample win does NOT transfer to an unseen
donor as currently built.** This is the honest answer, mechanistically diagnosed.

### Setup (`src/train_cross_loo.py`, NEW)
- Train on subject 1 pair 151507/151508; evaluate on the HELD-OUT subject 2 pair
  151669/151670 (downloaded this session, 96.1% array-bridge coverage, pitch 137).
- Two changes made cross-tissue eval valid: (1) TRANSFERABLE FEATURES — one
  TruncatedSVD basis fit on the TRAINING slices ONLY, then .transform applied to
  every slice (the held-out donor never touches the basis fit OR the weights);
  (2) the model is already pair-agnostic at inference (coarse = attn @ A_coords in
  whatever A frame is passed). Same loss/metric/eval grid as the headline.

### Result — registration error MEDIAN (px), tear regime
| severity | Sutura in-sample (subj1) | Sutura HELD-OUT (subj2) |
|----------|------------------------|-----------------------|
|    0     |          95            |        1508           |
|    8     |         118            |        1594           |
- In-sample REPRODUCES the original head-to-head (95->118px vs original 99->118),
  so the refactor is sound — the gap is real transfer failure, not a bug.
- Held-out median is ~1500px ≈ **11 spot pitches**, and FLAT across severity
  (1508->1594). The warp is irrelevant because correspondence is already lost.

### Mechanism (diagnosed, not guessed)
Cross-donor batch effect -> subj2 expression projects off-distribution in the
subj1-fit SVD basis -> the subj1-trained encoder produces NON-discriminative
embeddings on subj2 -> cross-attention collapses toward UNIFORM (median effective
support 2367 of 3661 A-spots) -> barycentric averaging shrinks predictions toward
the tissue centroid (pred std ~1134/1532 vs A's true ~2261/2209) -> ~1500px flat
error. The failure is in FEATURE/REPRESENTATION TRANSFER, not the deformation head.

### Honest framing (do not over-claim the negative either)
1. Single-donor training is the HARDEST possible generalization ask: the encoder
   never saw cross-donor variation, so it could not learn donor-invariance. The
   3-donor leave-one-out (not run) would be a fairer test (encoder trains on 2).
2. The deformation model is fine; it is being fed embeddings it cannot use.

### Next steps to actually achieve generalization
(a) batch-correct expression across donors (Harmony / Scanorama) BEFORE the SVD;
(b) train the encoder on MULTIPLE donors so it sees cross-donor variation;
(c) add a contrastive correspondence loss to sharpen cross-slice attention.

### Artifacts (results/)
- `arca_loo_test_curve.csv`  — held-out subj2 curve (the generalization result).
- `arca_loo_train_curve.csv` — in-sample subj1 curve (reproduces the headline).
- `arca_loo.pt`              — checkpoint (state_dict + args + per-pair pitch).
- `arca_loo_generalization.png` — 2-panel figure (gap; head-to-head on unseen
  tissue vs PASTE2 run on the same held-out pair: sweep_deformation_cross_tear_loo).

================================================================================
## UPDATE 2026-06-20 (late) — Sutura GRAPH MODEL TRAINED + HEAD-TO-HEAD DONE
================================================================================

Sutura's two-slice cross deformation model (`src/train_cross.py`, `SuturaCrossNet`)
was trained and evaluated head-to-head against PASTE2 on the SAME torn warps.
This is the first real Sutura-vs-PASTE2 result. **Sutura wins on both axes.**

### What ran
- Smoke run first (30 ep) — confirmed loss drops cleanly + correct tear ordering.
- Wired the eval grid to MATCH the PASTE2 tear sweep exactly:
  `apply_warp(B, sev, seed=0, tear=True)` for sev = 0,1,2,3,4,6,8, scored vs the
  array-bridge GT in 151507's pixel frame (same metric/axes as the headline).
  Eval seed 0 is disjoint from training seeds (`rng.integers(1,9999)`>=1) -> no
  warp-realization leakage. (Fixed a scaffold bug: sev0 in the tear regime DOES
  carry a tear because `apply_warp` uses `tear_offset_pitch * max(severity,1.0)`,
  so eval uses tear=True even at sev0.)
- Full run: 100 epochs x 12 steps, loss 22.4 -> 0.80 (pitch units), smooth
  descent to plateau. params=74178, hidden=64, 3 DeformConv layers, pca-dim=50.

### Final numbers — registration error MEDIAN (px), tear regime, same warps/GT
| severity | PASTE2 (GW/OT) | Sutura (GNN) |
|----------|----------------|------------|
|    0     |     658        |     99     |
|    1     |     655        |    100     |
|    2     |     689        |    100     |
|    3     |     716        |    102     |
|    4     |     729        |    103     |
|    6     |     773        |    109     |
|    8     |     838        |    118     |

- Sutura median is **~6.6-7.1x lower** than PASTE2 across the whole range and stays
  **below 1 spot pitch (137 px)** at every severity (sub-spot accuracy on torn
  tissue, where PASTE2 is 5-6 pitches off).
- Robustness (the headline claim): Sutura median rises only +19 px (99->118, +19%)
  from sev0->sev8; PASTE2 rises +180 px (658->838, +27%). Tearing — exactly what
  Sutura targets — is where it most outperforms GW/OT.
- PASTE2 label-transfer accuracy over the same sweep: 64.4% -> 57.5% (sev0->8).

### CAVEATS (state these before any paper claim — do NOT oversell)
1. **Sutura's error TAIL grows at the tear**, even though the median is flat:
   sev8 mean = 318.8 px, p90 = 1205.4 px (vs median 118). The torn-region spots
   (the genuine discontinuity) carry the error; the bulk of tissue stays
   sub-pitch. Correct framing: "most spots stay sub-pitch; the torn seam itself
   is the hard tail." See right panel of arca_vs_paste2_tear.png.
2. **Same-pair train/eval.** Sutura trained AND evaluated on the same 151507/151508
   pair (held-out warp seeds, same tissue). It learns this deformation
   distribution, not unseen tissue. A cross-sample / leave-one-out eval is the
   next rigor step before claiming generalization.
3. **Single eval seed (0).** Matches the sweep exactly but is one warp
   realization per severity. Multi-seed eval would give error bars.

### Exact artifacts on disk (results/)
- `arca_cross_curve.csv`  — final Sutura curve (severity, reg_err_median/mean/p90, n=4182).
- `arca_cross.pt`         — trained checkpoint (state_dict + args + pitch=137.0).
- `arca_vs_paste2_tear.png` — overlay figure (left: median head-to-head; right:
                              Sutura median/mean/p90 showing the tail).
- `arca_cross_smoke_loss.png`, `arca_cross_smoke_history.csv` — smoke-run loss curve.
- PASTE2 comparison source: `sweep_deformation_cross_tear.csv` (reg_err_median col).

### Code added/changed tonight
- `src/train_cross.py` — added `--eval-severities/--eval-seed/--eval-mode`,
  matched the eval grid to the tear sweep, fixed the sev0-tear bug. `--train` is
  now signed off and run.
- `src/overlay_arca.py` — NEW. Builds arca_vs_paste2_tear.png + prints the table.
- `src/_smoke_cross.py` — NEW. Per-epoch loss/val logging harness for sanity.

### Next steps (offered, not yet done)
(a) add Sutura curve into combined `headline_summary.png`;
(b) multi-seed eval for error bars; (c) leave-one-out cross-sample generalization test.

================================================================================
## (earlier) resume checkpoint (2026-06-17, ~23:35)
================================================================================

Terminal was killed by a lockdown browser mid-run. All completed work below is
persisted to disk; the virtualenv and installed packages are unaffected.

## Environment
- Python venv: `C:\Users\karti\arca\.venv` (Python 3.12; torch 2.12.1+cpu,
  paste-bio, paste2, scanpy, squidpy, torch_geometric — all installed).
- Activate-free invocation: `.\.venv\Scripts\python.exe`
- Set `$env:PYTHONUTF8=1` before runs (clean unicode in logs).

## DONE — verified on disk in `results/`
- **Baseline (PASTE2, full pair, pca, s=0.99):** 65.26% layer-transfer vs
  18.66% random floor (+46.6 pts). `paste2_transport_151507_to_151508.npy`
  (+ `_meta.npz`, `paste2_baseline_151507_to_151508.txt`).
- **Deformation sweep, 3 regimes (pca, s=0.99, alpha=0.1, sev 0,1,2,3,4,6,8):**
  - `sweep_deformation_cross.csv` (+png) — smooth: reg-err FLAT ~647px, acc ~65%.
  - `sweep_deformation_cross_tear.csv` (+png) — tear: reg-err 658->838px,
    acc 64.4->57.5% (THE HEADLINE: tear degrades where smooth stays flat).
  - `sweep_deformation_self.csv` (+png) — control: 0.0px all severities, 99% acc
    (validates setup).
  - NOTE: these 3 regimes ran before matrix-saving was added, so their per-sev
    transport matrices were NOT persisted (only the CSV summaries exist).
- **Argmax acceptance test (load-bearing) — PASSED:**
  `sweep_deformation_argmax_tear.csv` (+png) and matrices
  `pi_argmax_tear_sev0.npy`, `pi_argmax_tear_sev8.npy`.
  tear sev0->sev8 argmax median 728.6 -> 863.1px, acc 64.4 -> 57.5%.
  => tear degradation survives argmax (not a barycentric-smearing artifact).

## UPDATE 2026-06-18: argmax checks COMPLETED (job finished before lockdown)
- `sweep_deformation_argmax_smooth.csv`, `sweep_deformation_tear_a0p5.csv`,
  `sweep_deformation_argmax_tear.csv` all written (+ matrices, + plots).
- Combined headline figure: `results/headline_summary.png` (via src/make_headline.py).
- All acceptance tests passed (see report). Nothing below needs re-running.

## (historical) PENDING — interrupted, need re-run (each ~5-12 min, full spots, pca)
Run from `C:\Users\karti\arca` with `$env:PYTHONUTF8=1` set:

```powershell
# [2/3] floor check — cross-SMOOTH sev 0,8 @ alpha=0.1, argmax
.\.venv\Scripts\python.exe src\sweep_deformation.py --mode cross --severities 0,8 `
    --alpha 0.1 --dissimilarity pca --suffix argmax_smooth

# [3/3] confirmatory — cross-TEAR sev 0,8 @ alpha=0.5, argmax
.\.venv\Scripts\python.exe src\sweep_deformation.py --mode cross --tear --severities 0,8 `
    --alpha 0.5 --dissimilarity pca --suffix tear_a0p5
```

Or just re-run the whole driver (also redoes the already-done argmax_tear,
harmless — overwrites identical results):

```powershell
$env:PYTHONUTF8=1; .\run_argmax_checks.ps1
```

## After the two pending runs finish
Then ask for the **full three-regime report**. Expected reads:
- `sweep_deformation_argmax_smooth.csv` — confirm smooth floor flat under argmax.
- `sweep_deformation_tear_a0p5.csv` — confirm tear effect STRENGTHENS at alpha=0.5.

## Open scientific conclusion so far
PASTE2 (GW/OT) is robust to smooth (near-isometric) warps but degrades steadily
under tearing (non-isometric), even at default alpha=0.1 — the torn-tissue
failure mode Sutura targets. The alpha=0.5 confirmatory should sharpen this; the
full 28-run alpha sweep was deliberately SKIPPED (headline already at alpha=0.1).
Next project step after confirmatory: build Sutura's graph model and overlay its
curve on the tear axes.
