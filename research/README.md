# Sutura Genomics — registration research

The model and experiments behind Sutura Genomics: **graph deep learning for
spatial-transcriptomics tissue registration**, built for the torn /
non-isometric warps optimal transport can't represent.

> **Naming.** The product is **Sutura Genomics**. `Sutura` is the internal codename
> for the registration model; it persists in code identifiers (`SuturaCrossNet`),
> checkpoint filenames (`arca_*.pt`), and the run scripts so trained artifacts
> stay loadable and results stay reproducible. Treat "Sutura" and "the Sutura
> model" as the same thing.

## What's here

- `src/` — model + experiment code (PyTorch / torch-geometric).
  - `train_cross.py` — two-slice cross deformation model (`SuturaCrossNet`).
  - `train_cross_loo.py` — leave-one-donor-out cross-sample training/eval.
  - `train_cross_contrastive.py` — LOO + donor-invariant contrastive
    correspondence loss (the current direction).
  - `sweep_deformation.py`, `baseline_paste.py` — PASTE2 (optimal-transport)
    baselines and the deformation sweeps.
  - `prepare_data.py`, `warp_slice.py`, `scoring.py`, `score_alignment.py`,
    overlay/figure scripts.
- `results/` — curves (`*.csv`), figures (`*.png`), and checkpoints (`*.pt`).
  Raw `.h5ad` data and the full-resolution transport matrices (`*.npy`, >100 MB)
  are gitignored and regenerable via the scripts.
- `run_*.ps1` — detached-safe orchestration scripts for the sweeps and the
  3-donor / contrastive matrices.
- `RESUME.md` — running research checkpoint log (most recent at top).

## Current status (honest)

1. **In-distribution head-to-head — strong.** Same-pair, torn regime: the Sutura
   model is 99 → 118 px (sev0 → sev8) vs PASTE2's 658 → 838 px — ~6.6–7× lower,
   sub-spot-pitch throughout. The error *tail* at the torn seam is the hard part
   (sev8 p90 ≈ 1205 px).
2. **Cross-donor generalization — open.** Leave-one-donor-out: excellent on
   training donors (82–148 px) but 1080–1557 px on the unseen donor, losing to
   PASTE2 (407–838 px). The in-distribution win does not yet transfer.
3. **Contrastive correspondence loss — closing the gap (in progress).** A
   donor-invariant InfoNCE-style match loss. Held-out fold S1: best config
   (attn, λ=0.5) reaches 834 → 994 px, roughly halving the cross-donor gap and
   nearly tying PASTE2 at high severity — not yet beating it. The full 3-fold ×
   {readout, λ} matrix is still running; resume via `run_ctr_matrix.ps1` (it skips
   already-completed runs).

## Environment

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONUTF8 = "1"
```

torch (CPU), paste-bio / paste2, scanpy, squidpy, torch-geometric.
