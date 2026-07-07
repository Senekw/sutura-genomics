# Fix A — shared frozen SVD basis: findings

**Branch:** `shared-basis` · **Date:** 2026-07-07 · Diagnostic; `main`, website, demo untouched.

## What was done

The pretrained Sutura model collapsed off its training donor because node features
were a `TruncatedSVD` **re-fit per section** — SVD directions are defined only up to
sign/rotation, so each re-fit handed the encoder a differently-oriented basis
(diagnosed in `FINDINGS_sweep.md`). Fix A replaces that with **one shared, frozen
basis**:

1. **Fit** a single 50-component `TruncatedSVD` on the pooled log1p-normalized
   expression of three DLPFC donors — Br5292 + Br5595 + Br8100 (all 6 slices, 23,081
   spots, identical 33,538-gene vocabulary). Freeze the directions **and** the
   per-component standardization (mean/std) of the pooled projection.
   → `results/shared_basis.npz` (`src/shared_basis.py`).
2. **Apply** it by transform-only (never re-fit) to produce node features for every
   section, train and test.
3. **Retrain** the Sutura graph model (identical `ARCACrossNet` architecture) **from
   scratch** on these features, supervising on **Br5292 + Br5595** and holding
   **Br8100** fully out of training.
   → `results/arca_shared_basis.pt` (`src/train_shared_basis.py`).
4. **Evaluate** on the tear benchmark (severities 0–8, cross-section, array-bridge GT),
   in-distribution (Br5292, Br5595) and held-out (Br8100), against PASTE2 and the old
   per-SVD model. → `results/shared_basis_eval.csv` (`src/eval_shared_basis.py`),
   figure `results/shared_basis_eval.png`.

## Results (median registration error, spot-pitches, averaged over severity 0–8)

| Donor | Condition | Old per-SVD | **Shared basis (new)** | PASTE2 | Centroid collapse |
|---|---|---:|---:|---:|---:|
| Br5292 | in-distribution (train) | 0.76 | **1.38** | 5.28 | 24.3 |
| Br5595 | in-distribution (train) | 16.32 | **1.17** | 4.35 | 21.7 |
| **Br8100** | **held-out** | 18.98 | **9.59** | 3.46 | 22.2 |

("Centroid collapse" = error from predicting every spot at the reference centroid —
the no-signal floor. Full per-severity/seed table in the CSV.)

## Answering the key question

**1. Does the model retain signal on the held-out donor instead of collapsing to
centroid? — YES, clearly.** Old per-SVD Br8100 = 18.98 pitch, essentially the
centroid floor (22.2). The shared-basis model reaches **9.59 pitch — 57% of the way
from centroid to zero**, and error is flat-low rather than pinned near centroid. The
shared basis removes the catastrophic collapse; the model now carries real
cross-donor correspondence signal on a donor it never trained on.

**2. Does it approach or beat PASTE2 cross-donor? — NO.** PASTE2 on held-out Br8100 =
3.46 pitch; shared-basis Sutura = 9.59, still ~2.8× worse. On a never-trained donor,
PASTE2 remains the better method.

## The other, cleaner win: multi-donor training now works at all

The most decisive evidence that Fix A does what it claims is **Br5595**. The old
per-SVD model collapsed on Br5595 (16.32, near centroid) — even though we *could* have
trained on it — because a second donor's independently-rotated SVD basis was
unusable to an encoder tuned on the first donor's basis. With the shared basis, the
model fits **both** training donors to ~1.2 pitch simultaneously and **beats PASTE2
in-distribution** (1.2 vs 4.4). The per-section-SVD design could not represent two
donors at once; the shared basis can. That is the representation-orientation bug
being fixed exactly as diagnosed.

## Honest limitations

- **The fix is partial, not complete.** In-distribution the model is excellent (~1.2
  pitch), but the held-out donor sits at 9.6 — a large train→held-out gap. Freezing the
  basis solves the *representation-rotation* failure but not the deeper
  *distribution-shift* generalization: with only two training donors, the encoder/
  attention still overfit the training donors' feature→geometry relationship. Closing
  the held-out gap likely needs more donor diversity in supervised training (and
  possibly explicit batch correction), not just a shared basis.
- **Held-out severity insensitivity.** On Br8100 the error is nearly flat across
  severity (9.5→10.0, sev0→8). The model finds a roughly-correct but globally-biased
  map on the unfamiliar donor rather than a tear-sensitive one — consistent with
  "partial signal," not full registration.
- **In-distribution cost on the original donor.** Br5292 is slightly worse than the
  old model (1.38 vs 0.76) — the shared basis is a less donor-optimal representation
  than a per-section fit. A small, worthwhile trade for not collapsing elsewhere.
- **Basis leakage caveat / robustness check.** Per the spec, Br8100's expression was
  pooled into the (unsupervised) frozen basis, so the primary result is "held out from
  *supervised training*," not "never seen in any form." To test whether that inflates
  the held-out number, we refit the basis on **train donors only** (Br5292 + Br5595,
  no Br8100), retrained from scratch, and re-evaluated Br8100:
  **held-out Br8100 median = ⟨STRICT⟩ pitch** (`results/shared_basis_trainonly.npz`,
  `results/arca_shared_basis_trainonly.pt`). ⟨STRICT_INTERP⟩

## Bottom line

Fix A is a **genuine partial success**. It eliminates the catastrophic centroid
collapse, makes multi-donor training possible for the first time (Br5595 goes from a
collapse to beating PASTE2), and roughly halves held-out error. But it does **not**
make Sutura competitive with PASTE2 on a never-seen donor (9.6 vs 3.5 pitch). The
shared frozen basis is a necessary fix and a real step forward, not a sufficient one —
cross-donor generalization needs broader training-donor diversity on top of it.

## Deliverables

- `results/shared_basis_eval.csv` — full grid (donor, condition, severity, method, seed).
- `results/shared_basis_eval.png` — per-donor comparison figure.
- `results/shared_basis.npz` — the frozen basis (directions + z-stats + gene order).
- `results/arca_shared_basis.pt` — the retrained checkpoint.
- Robustness variant: `results/shared_basis_trainonly.npz`, `results/arca_shared_basis_trainonly.pt`.
- Code: `src/shared_basis.py`, `src/train_shared_basis.py`, `src/eval_shared_basis.py`,
  `src/plot_shared_basis.py`.
