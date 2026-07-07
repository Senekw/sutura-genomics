# Sutura zero-shot generalization sweep — findings

**Branch:** `external-eval` · **Date:** 2026-07-07 · **Checkpoint:** `results/arca_cross.pt`
(the pretrained cross-slice model, trained on DLPFC donor **Br5292** = slices 151507/151508).
Diagnostic only — **no retraining**, no changes to `main`, the website, or the demo.

## TL;DR

**Sutura does not generalize zero-shot to any dataset we tested — not even to a
different human donor of the same tissue (DLPFC).** On its training donor it is
excellent (median registration error 0.76 spot-pitches, ~6× better than PASTE2).
On every other dataset it collapses to 15–20 pitches of error — the level you get
from predicting the tissue centroid, i.e. no correspondence signal at all — while
PASTE2 stays at 3–6 pitches everywhere and beats Sutura by 3–5×.

The failure is **not tissue-specific**. Cross-donor same-tissue DLPFC fails just as
hard as cross-species mouse brain or cross-tissue human breast cancer. The model is
bound to the specific training *instance*, not to a tissue type.

| Dataset | Kind | Sutura median (pitch) | PASTE2 median (pitch) | Winner |
|---|---|---:|---:|:--:|
| DLPFC **Br5292** (151507/08) | in-distribution (train donor) | **0.76** | 5.28 | **Sutura 6.9×** |
| DLPFC **Br5595** (151669/70) | cross-donor, same tissue | 16.32 | **4.35** | PASTE2 3.8× |
| DLPFC **Br8100** (151673/74) | cross-donor, same tissue | 18.98 | **3.46** | PASTE2 5.5× |
| **Mouse Brain** Sagittal Post. | cross-species, neural | 14.84 | **5.46** | PASTE2 2.7× |
| **Breast Cancer** Block A | cross-tissue, non-neural | 20.07 | **3.68** | PASTE2 5.5× |

(Median over the severity 0–8 grid; per-severity/seed values in
`results/generalization_sweep.csv`, figure in `results/generalization_sweep.png`.)

## What the numbers say

- **In-distribution, the internal headline reproduces.** On Br5292, Sutura holds
  ~0.72–0.86 pitch from severity 0 through 8 (robust to tears), versus PASTE2's
  4.8–6.1 pitch. This is the result the project was built on — and it is real, but
  it is a *single-donor* result.

- **Sutura's error is flat in severity and seed on every OOD dataset.** e.g. Br5595
  reads 16.3 pitch at severity 0 and 16.3–16.9 at severity 8, identical across
  seeds 0/1/2. A method that had *any* correspondence signal would start low at
  severity 0 (no deformation) and rise with the tear. Flatness at ~centroid
  distance means the model outputs the same near-centroid guess regardless of the
  input — it has no usable signal off its training donor.

- **PASTE2 degrades gracefully and is nearly warp-invariant.** Its median rises only
  gently with severity (e.g. Br5595: 3.84 → 4.17 → 5.05 pitch at sev 0/4/8) because
  with `alpha=0.1` the optimal transport is expression-dominated, and the synthetic
  warp leaves expression intact. This makes it a stable, tissue-agnostic baseline.

## Why Sutura fails (root cause)

Two compounding, independently-verified causes — **both of which any real zero-shot
user hits by construction**:

1. **The encoder is bound to a specific, non-canonical SVD feature basis.** Node
   features are a `TruncatedSVD` of log-normalized expression, *re-fit per dataset*.
   SVD components are only defined up to sign/rotation, so a fresh fit on any new
   gene set / spot set yields a different basis — and the trained encoder weights,
   tuned to the training basis, then see effectively scrambled inputs. This is not a
   subtle effect: re-fitting the SVD on *a subset of the training donor's own spots*
   already drives error from 0.7 to ~7–13 pitch. A new dataset (different genes,
   different cells) guarantees a different basis, so the encoder is broken before
   distribution shift is even considered.

2. **Donor / tissue distribution shift** on top of (1). The cross-attention and
   deformation head were fit to one donor's expression–geometry relationship.

The model also depends on **full native spot density** (its kNN graph and
pitch-normalization assume it); random subsampling or cropping degrades it further,
which is why the sweep is run at full resolution (see Adaptations).

The upshot: the architecture as trained memorizes a single (donor, SVD-basis,
density) configuration. There is no mechanism that would let it transfer — no shared
gene embedding, no basis alignment, no multi-donor training. Zero-shot transfer was
never actually possible with this checkpoint; the sweep confirms it empirically.

## Datasets & method

All datasets use **cross-section mode**: reference = one real Visium section, moving
= a real *adjacent* section, warped by the repo's synthetic tear pipeline
(`src/warp_slice.apply_warp`, `tear=True`, severities 0,1,2,3,4,6,8). Ground truth
is the Visium **array-bridge** (a moving spot at array position (r,c) corresponds to
the reference spot at (r,c)); registration error is the pixel distance from the
predicted reference-frame location to that GT, reported in spot-pitches so it is
comparable across datasets. Both methods score the *same* warped slices. Harness:
`src/external_eval.py`; fetch: `src/fetch_external.py` + `src/prepare_data.py`.

**Why cross-section and not self-warp:** the model was trained to register a moving
slice into a *different* reference slice's frame. Feeding it a self-warp (moving ==
reference) is out of distribution and fails even on the training donor (~8 pitch at
severity 0), and it also lets expression-based PASTE2 cheat via an exact expression
key. Every dataset here therefore uses a genuine adjacent section, exactly like the
training regime. Array-bridge coverage was verified at 90–96% for all pairs.

**Dataset roster (adjacent-section pairs):**

- **DLPFC Br5595** (151669/151670) and **Br8100** (151673/151674) — other donors from
  the same spatialLIBD study as the training donor; same tissue (human DLPFC),
  different subjects. Cross-donor generalization.
- **Mouse Brain Sagittal Posterior** (`V1_Mouse_Brain_Sagittal_Posterior` +
  `_Section_2`) — 10x public. Cross-species, still neural.
- **Human Breast Cancer Block A** (`V1_Breast_Cancer_Block_A_Section_1` + `_2`) —
  10x public. Cross-tissue, non-neural.

**On the requested Human Kidney:** 10x's public Visium set has **no human-kidney
sample and no adjacent human-kidney sections**, so it could not be run as specified.
`V1_Mouse_Kidney` exists but is a **single section** — unusable with this
cross-section-only model (self-warp is OOD, as shown above). We therefore substituted
the human **Breast Cancer Block A** adjacent pair as the non-neural cross-tissue probe.
The mouse-kidney slice is fetched (`data/external/`) for reference but not scored.

## Adaptations (and why they don't change the conclusion)

- **Full resolution, no subsampling.** Because the model is SVD-basis- and
  density-sensitive, subsampling would *understate* its in-distribution baseline and
  muddy the diagnostic. Full slices (~1.4k–4.2k spots) are used throughout; the SVD is
  re-fit per dataset exactly as any zero-shot use requires.
- **PASTE2 dissimilarity = `pca`, not the headline `glmpca`.** `glmpca` is ~50× slower
  and the full-resolution GW-OT already costs ~60–370 s per slice-pair. The
  Sutura-vs-PASTE2 ordering is not close (3–5×), so this does not affect any
  conclusion; PASTE2 with `glmpca` would if anything be *better*, widening its lead.
- **PASTE2 on a coarse severity grid (0,4,8), one seed.** PASTE2 is nearly
  warp-invariant (see above), so a fine grid is unnecessary; Sutura, being a sub-second
  forward pass, is run on the full 7-severity × 3-seed grid.
- **10x datasets have no cortical-layer labels**, so only registration error is
  reported (no label-transfer accuracy).

## Honest bottom line

The tear-robustness advantage of Sutura over PASTE2 is **real but confined to the
training donor**. As a pretrained, zero-shot registration tool the current checkpoint
is not usable: it fails to transfer even across donors of the same tissue, and PASTE2
is the better choice on every dataset we do not train on. Making Sutura generalize
would require architectural changes it does not currently have — at minimum a
dataset-invariant gene/expression representation (shared embedding or aligned basis
instead of a per-dataset SVD) and multi-donor/multi-tissue training — not just more
data through the existing pipeline.
