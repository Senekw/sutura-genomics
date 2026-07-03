# External generalization test — Sutura (`arca_cross.pt`), zero-shot

**Diagnostic question:** does the pretrained Sutura checkpoint, trained only on
DLPFC 151507→151508, generalize zero-shot to a spatial-transcriptomics dataset it
never saw? And how does it compare to PASTE2 there?

## Bottom line (honest)

**No — the released checkpoint does not generalize zero-shot.** On external human
breast tissue it produces a **degenerate, collapsed mapping** and a median
registration error of **~5,270 px (≈19 spot pitches), flat across all tear
severities including severity 0** — i.e. it fails even when there is nothing to
align, and it is **worse than doing nothing** (no-op ≤ 1,837 px). PASTE2, which is
re-optimized from scratch for each pair rather than learned, does not share this
failure. The checkpoint appears **specialized to its single training pair**: it
also fails in-distribution the moment it is taken off that exact pairing (DLPFC
self-mode 2,021 px vs cross-mode 99 px). This is a limitation of the released
checkpoint, reported plainly.

## Setup

- **Dataset:** 10x Genomics "Human Breast Cancer, Block A", Sections 1 & 2 — two
  adjacent serial Visium sections (S1: 3,798 spots, S2: 3,987 spots; 36,601
  genes; raw counts). Downloaded via `scanpy.datasets.visium_sge` into
  `research/data/external/` (gitignored). Fetch: `validation/_fetch_external.py`.
- **Checkpoint:** `research/results/arca_cross.pt`, used **as-is, no retraining.**
- **Benchmark:** our standard synthetic Gaussian-bump + tear field
  (`src/warp_slice.apply_warp`, `tear=True`), severities 0,1,2,3,4,6,8, seeds
  {0, 9999, 10000} (disjoint from training). Metric = median Euclidean
  registration error, `src/scoring.registration_error_stats` — identical to the
  main benchmark.
- **Methods:** Sutura (zero-shot, `train_cross.ARCACrossNet`) vs PASTE2
  (`partial_pairwise_align`, barycentric projection) vs a **No-op** reference
  (leave spots at their warped positions). Scripts:
  `validation/external_generalization.py` (self-warp) and
  `validation/external_cross_check.py` (native cross-mode).

## Adaptations required (external format ≠ DLPFC)

1. **Gene panel differs (36,601 vs 33,538 genes).** No problem: the model
   consumes a 50-dim shared TruncatedSVD of expression (`cross_features`), not
   raw genes, so it is gene-set agnostic. Cross-mode needed an explicit
   gene-name intersection before the shared SVD.
2. **No annotations / different obs keys.** External data has `obsm[spatial]`,
   `obs[array_row/array_col]`, raw counts — enough for warping, features, and
   scoring. Cortical-layer annotations (used only for the DLPFC label-transfer
   metric) are absent, so we report registration error only.
3. **No exact cross-section ground truth.** DLPFC's exact GT relies on the shared
   Visium **array bridge** across adjacent spatialLIBD slices (95% of spots match
   by array position). Two independently captured external sections do **not**
   share an array frame, so there is no exact per-spot correspondence to score a
   real cross alignment. We therefore use the **self-consistency tear mode** (the
   `self` mode our main benchmark already supports): warp a copy of one real
   section and score against its known original coordinates (exact GT).
4. **Subsampled to 1,200 spots** per section to keep PASTE2 tractable (applied to
   all methods equally). PASTE2 dissimilarity = `pca` (faster than glmpca; the
   registration/scoring methodology is identical).

## Results

### 1. Self-warp tear benchmark — external breast S1 (median px, mean over 3 seeds)

| severity | Sutura (zero-shot) | PASTE2 | No-op (unaligned) |
|---:|---:|---:|---:|
| 0 | 5,252 | 0.0 | 0 |
| 1 | 5,266 | 0.0 | 200 |
| 2 | 5,259 | 0.0 | 400 |
| 3 | 5,261 | 0.0 | 599 |
| 4 | 5,269 | 0.0 | 799 |
| 6 | 5,290 | 0.0 | 1,199 |
| 8 | 5,292 | 0.0 | 1,598 |

(pitch = 273 px. Full per-seed table: `results/external_generalization.csv`.)

Two things are immediately visible and **both are confounds that must be stated,
not hidden**:

- **PASTE2 = 0.0 everywhere is an artifact, not a result.** In self-consistency
  mode the moving section is an exact **expression copy** of the reference, so
  PASTE2's optimal-transport plan trivially matches each spot to its own twin by
  expression. This is a lower bound of the setup, **not** evidence that PASTE2
  handles tears — it never has to.
- **Sutura's ~5,270 px is flat across severity, including severity 0.** A working
  aligner returns ~0 px at severity 0 (identity — nothing is warped). Sutura
  returns 5,252 px there and essentially the same value at every severity. It is
  **not responding to the tear at all**; it emits a near-fixed, wrong mapping.

### 2. Native cross-mode reality check — map real S2 → S1 (the model's trained regime)

Because self-mode is not this checkpoint's regime (see §3), we also ran the model
in the two-different-section configuration it was trained for, on the two **real**
breast sections. No exact GT exists, so we report method-neutral proxies:
`spread` (mapped extent ÷ reference extent; →0 = collapse), `coverage` (fraction
of reference footprint within 1 pitch of a mapped spot), `expr-coherence` (median
cosine similarity of each mapped spot to its reference neighbors).

| method | spread | coverage | expr-coherence |
|---|---:|---:|---:|
| **Sutura** (zero-shot) | 0.46 | **0.17** | 0.830 |
| PASTE2 | 1.00 | 0.99 | 0.869 |
| A-self (upper bound) | 1.00 | 1.00 | 0.919 |

Sutura's mapping **collapses**: it compresses S2 into ~half the spatial extent and
covers only **17%** of the reference footprint. PASTE2 spreads S2 across the full
reference (coverage 0.99) with coherence (0.869) close to the self upper bound
(0.919). So even in its native regime, Sutura does not produce a usable alignment
on external tissue, while PASTE2 does.

### 3. In-distribution controls (calibration)

Run through the same harness on DLPFC (the training data):

| configuration | sev 0 | sev 4 | sev 8 |
|---|---:|---:|---:|
| DLPFC **cross** (151507→151508, in-sample) | 99 px | 103 px | 118 px |
| DLPFC **self** (151508 ↔ warped-151508) | 2,021 px | 2,037 px | 2,103 px |

The cross-mode row reproduces the paper's headline exactly, confirming the harness
is correct. The self-mode row shows the checkpoint fails by ~2,000 px **even on
its own training tissue** the moment the reference and moving section are the same
slice — direct evidence that `arca_cross.pt` learned the specific 151507→151508
mapping (including that pair's absolute coordinate frames) rather than a general
"align B into A" operator.

## Interpretation

The model's coarse prediction is an attention-weighted average of reference
coordinates; the learned query/key projections were fit on the 151507/151508
feature manifold and frames. Fed out-of-distribution expression (a new tissue) or
a configuration it wasn't trained on (self-mode), the cross-attention no longer
resolves confident correspondences, so predictions collapse toward a fixed region
— hence the flat ~5,270 px on external self-warp and the 17%-coverage collapse in
external cross-mode. PASTE2 has no learned weights to transfer, so it "generalizes"
trivially: it just re-solves the OT problem per pair.

## Honest conclusion & caveats

- **No evidence of zero-shot generalization** for this checkpoint beyond its
  training pair. On external breast tissue it is worse than no alignment at all.
- The self-warp Sutura-vs-PASTE2 comparison is **not a clean tear-handling
  contest**: PASTE2's 0 px is a self-consistency artifact, and Sutura's number is
  dominated by an out-of-distribution collapse. The native cross-mode proxies are
  the more meaningful signal, and they point the same way.
- **What a fair external test would need:** either (a) an external dataset with a
  real cross-section correspondence (shared array frame or manual landmark
  annotations) to compute exact registration error in the model's native regime,
  or (b) **re-training / fine-tuning** Sutura on multi-tissue data — the current
  checkpoint is effectively a single-pair fit and should not be expected to
  transfer as-is.
- Scope note: this used the breast Block A pair; results may differ on other
  tissues, but the in-distribution self-mode failure (2,021 px) already shows the
  limitation is about the checkpoint, not the specific external dataset.

### Reproduce

```
py=C:/Users/karti/arca/.venv/Scripts/python.exe
$py research/validation/_fetch_external.py               # download S1/S2
$py research/validation/external_generalization.py       # self-warp CSV
$py research/validation/external_cross_check.py           # native cross-mode proxies
```
Outputs: `research/results/external_generalization.csv`, and the printed control /
cross-mode tables above.
