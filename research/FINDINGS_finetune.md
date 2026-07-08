# Does fine-tuning rescue Sutura's generalization to external tissue?

**Follow-up to `FINDINGS_external.md`.** That experiment showed the pretrained
checkpoint (`arca_cross.pt`) does not generalize zero-shot to external breast
tissue (~5,270 px, worse than no-op). Here we test whether **a small amount of
fine-tuning on the target tissue rescues it — enough to beat PASTE2** (the
"adapt-per-dataset" product direction).

## Bottom line (honest)

**No.** Fine-tuning **overfits to the section it is trained on and does not
transfer to a held-out section of the same tissue**, and it does not beat PASTE2:

- Fine-tuning **works where applied**: on its own section S1 the model drops from
  ~5,790 px (zero-shot) to **~225 px**. The architecture *can* learn breast tissue.
- But on the **held-out** section S2 it barely moves: **~5,790 → ~5,425 px**
  (~6% better, still ~20 spot pitches, still worse than doing nothing).
- On the real S2→S1 pair the mapping **stays collapsed** after fine-tuning
  (footprint coverage 0.11, vs PASTE2's 0.99).

So adaptation is **section-specific, not tissue-general**: you would have to
fine-tune on the *exact* sections you align, not "fine-tune once on the tissue
type and generalize." This is a limitation, reported plainly.

## Setup

- **Data:** external 10x Human Breast Cancer Block A, Sections 1 & 2 (the only
  external adjacent pair; no cross-section ground truth exists — see
  `FINDINGS_external.md`). 1,500 spots/section.
- **Split (no leakage):** fine-tune on **S1**, hold out **S2** entirely for test.
- **Fine-tuning signal:** synthetic self-warp supervision — warp a copy of S1,
  supervise `||pred - original||` (exact GT, no labels). This is the self-
  supervised signal an adapt-per-dataset product would actually use. Small budget:
  60 epochs × 8 steps, lr 5e-4, from `arca_cross.pt`. Loss fell 16.6 → ~1.1 pitch
  units (it fit S1 fine).
- **Test:** standard tear sweep on held-out S2 (sev 0–8, seeds {0,9999,10000}),
  median registration error. Conditions: (a) zero-shot pretrained, (b) fine-tuned,
  (c) PASTE2. Plus an **in-set** control (fine-tuned model back on S1) and the
  **native cross-mode proxy** (real S2→S1, where PASTE2 is non-trivial).
- Script: `research/validation/finetune_rescue.py`; CSV:
  `research/results/finetune_rescue.csv`; fine-tuned checkpoint:
  `research/results/arca_cross_breast_ft.pt`.

## Results

### 1. Held-out S2 tear sweep — median px (mean over 3 seeds)

| severity | Sutura zero-shot | Sutura fine-tuned | PASTE2 |
|---:|---:|---:|---:|
| 0 | 5,799 | 5,442 | 0.0* |
| 2 | 5,784 | 5,414 | 0.0* |
| 4 | 5,786 | 5,412 | 0.0* |
| 6 | 5,781 | 5,433 | 0.0* |
| 8 | 5,803 | 5,458 | 0.0* |

\* PASTE2's 0 is the self-consistency artifact (identical-expression copy), not
tear-handling — see §3 for the fair, non-trivial comparison. Fine-tuned Sutura on
held-out S2 stays flat ~5,425 px across severity (incl. sev 0, where the answer is
identity) — i.e. it is still not producing a real alignment on the held-out
section, and remains **worse than the no-op reference** (≤1,837 px at sev 8).

### 2. In-set control — fine-tuned model on its OWN section S1 (median px)

| severity | 0 | 2 | 4 | 6 | 8 |
|---|---:|---:|---:|---:|---:|
| fine-tuned (in-set) | 208 | 221 | 227 | 238 | 252 |

Fine-tuning fit S1 to ~225 px (from the ~5,790 px it would score zero-shot). So
the failure on S2 is **overfitting / no transfer**, not undertraining — the model
learns the *specific section it saw* but not a breast aligner that transfers.

### 3. Native cross-mode proxy — map real S2 → S1 (PASTE2 non-trivial here)

| method | spread | footprint coverage | expr-coherence |
|---|---:|---:|---:|
| Sutura zero-shot | 0.37 | 0.13 | 0.845 |
| Sutura fine-tuned | 0.40 | **0.11** | 0.859 |
| PASTE2 | 1.00 | **0.99** | 0.871 |

On the real pair, fine-tuning does **not** fix the collapse (coverage 0.11 ≈
zero-shot's 0.13; PASTE2 covers 0.99). **Fine-tuned Sutura does not beat, or even
approach, PASTE2** on external tissue.

## Interpretation

The model's expression features are a **per-section TruncatedSVD basis** (fit on
each pair independently). Fine-tuning on S1 teaches the encoder/attention S1's SVD
directions; S2's SVD basis is a *different* coordinate system, so the learned
mapping doesn't apply. Hence: excellent in-set fit (225 px), no held-out transfer
(5,425 px). PASTE2 re-solves optimal transport per pair with no learned weights,
so it has nothing to overfit and maps S2 across S1 sensibly.

## Answer to the product question

**Fine-tuning as a "train-on-tissue, generalize-to-new-sections" recipe does not
work here.** To make Sutura usable on a new dataset you would currently have to
fine-tune on the *exact* sections being aligned (no hold-out) — and even that only
demonstrates self-alignment with synthetic GT, not real cross-section registration
(for which external data has no ground truth). A genuine adapt-per-dataset product
would first need architectural changes so adaptation transfers across sections —
e.g. a **shared/anchored feature basis** across sections (so the encoder isn't
tied to a per-section SVD), and/or training on **many tissues** rather than one
pair. As-is, both the released checkpoint and its single-section fine-tune are
below PASTE2 on external tissue.

## Caveats
- One external pair (breast Block A); a second dataset/tissue would strengthen the
  claim, but the mechanism (per-section feature basis) is general.
- Self-warp supervision measures geometric tear-recovery, not real biological
  cross-section correspondence (which is unmeasurable on external data without a
  landmark/array bridge). The in-set 225 px and held-out 5,425 px are directly
  comparable to each other and to the zero-shot 5,790 px.

### Reproduce
```
C:/Users/karti/arca/.venv/Scripts/python.exe research/validation/finetune_rescue.py
```
Outputs `research/results/finetune_rescue.csv` + the in-set / cross-proxy tables above.
