# Atlas sweep — findings

**Branch:** `atlas-sweep` (off `generalization-max`) · **Date:** 2026-07-09 · `main`, website, demo untouched.
Code: `src/atlas_sweep.py`, `src/plot_atlas_sweep.py`.
Outputs: `research/results/atlas_sweep.csv`, `research/results/atlas_sweep.png`,
`research/results/atlas_sweep_skipped.csv`, `research/results/atlas_sweep.log`.

## What ran

The orchestrator (distribution check → route → auto-adapt on off-dist → post-QC) was
run across **8 programmatically-downloaded Visium serial-section datasets** at a fixed
synthetic tear (severity 4.0, seed 0), recording per dataset: tissue/platform/spot
counts, gene-vocabulary overlap with the frozen DLPFC basis, Mahalanobis distance,
in-distribution confidence, the routed method, and — for direct comparison — standalone
**Sutura (zero-shot)**, **Sutura (auto-adapted)**, and **PASTE2** error. Error is the
median registration error in spot-pitch units against array-bridge ground truth (all 8
pairs shared the Visium array grid; GT coverage 0.85–0.99).

**Datasets swept:** 3 DLPFC donors (spatialLIBD: Br5292, Br5595, Br8100) + 5 10x serial
pairs (breast cancer Block A, mouse sagittal posterior/anterior, human cerebellum, mouse
coronal). The 3 new 10x pairs were downloaded live during the run without error.

**Sources skipped (8 classes, logged in `atlas_sweep_skipped.csv`):** single-section 10x
samples with no serial pair (Human Heart, Human Lymph Node, Mouse Kidney, Adult Mouse
Brain); Parent/Targeted pairs (same physical section, two gene panels — not adjacent
sections); Slide-seq / MERFISH / seqFISH / IMC (no Visium array grid, so no array-bridge
GT); and generic GEO spatial series (no standardized array-aligned serial pair via direct
download). The binding requirement is **two array-aligned serial sections** — most public
spatial data is single-section, which is why the usable pool is small.

## Results (median error, spot-pitches; lower is better)

| dataset | tissue | overlap | maha | conf | route | Sutura 0-shot | Sutura adapt | PASTE2 | chosen |
|---|---|--:|--:|--:|:--:|--:|--:|--:|:--:|
| DLPFC_Br5595 | human DLPFC | 1.00 | 1.02 | 0.90 | **sutura** | **1.19** | 9.19 | 5.60 | Sutura 1.19 |
| DLPFC_Br5292 | human DLPFC | 1.00 | 0.85 | 0.92 | **sutura** | **1.41** | 8.20 | 5.60 | Sutura 1.41 |
| DLPFC_Br8100 | human DLPFC | 1.00 | 4.77 | 0.03 | paste2 | 9.45 | 6.74 | **3.49** | PASTE2 3.49 |
| breast_block_a | human breast cancer | 0.95 | 20.4 | 0.00 | paste2 | 26.85 | 7.92 | **4.01** | PASTE2 4.01 |
| human_brain_cbl | human cerebellum | 0.95 | 9.33 | 0.00 | paste2 | 27.66 | 16.75 | **4.36** | PASTE2 4.36 |
| mouse_coronal | mouse brain | 0.001 | — | 0.02 | paste2 | 19.23 | n/a | **2.66** | PASTE2 2.66 |
| mouse_sagittal_ant | mouse brain | 0.001 | — | 0.02 | paste2 | 18.28 | n/a | **5.33** | PASTE2 5.33 |
| mouse_sagittal_post | mouse brain | 0.001 | — | 0.02 | paste2 | 20.85 | n/a | **6.04** | PASTE2 6.04 |

## Where Sutura wins vs where it routes away

- **In-distribution (2/8): Sutura wins decisively.** On the two *training* DLPFC donors,
  zero-shot Sutura is **1.2–1.4 pitch — ~4× better than PASTE2 (5.6)**. These are the only
  datasets the router sends to Sutura, and it is right to.
- **Off-distribution (6/8): routes to PASTE2, correctly.** Everything else — including the
  **held-out DLPFC donor Br8100** (same tissue, unseen donor) — is off-distribution. Sutura
  zero-shot collapses (9.4 on Br8100; 19–28 on cross-tissue/mouse) and the router sends all
  six to PASTE2, which lands at 2.7–6.0. On every off-dist dataset PASTE2 ≤ both Sutura
  variants, so the routing decision matches the true winner in **8/8** cases.
- **The router separates cleanly.** In-distribution Mahalanobis is ≤ 1.02; off-distribution
  is ≥ 4.77 — a wide, unambiguous gap around the 2.5 threshold. No dataset sat in a grey
  zone. Gene-vocabulary gate: human Visium overlaps the DLPFC panel at ~0.95; mouse at
  ~0.001 (different-species symbols), which correctly forces mouse off-dist and makes
  adaptation inapplicable.
- **Auto-adapt helps off-dist but never beats PASTE2.** It cut zero-shot error substantially
  where the panel is shared (breast 26.9→7.9, Br8100 9.4→6.7, cerebellum 27.7→16.7) but
  stayed above PASTE2 in all cases; on mouse (0% overlap) it is not applicable.

## In-distribution vs off-distribution split

**2 in-distribution, 6 off-distribution.** "In-distribution" today means *the specific
donors the shared basis was trained on* — not even the same tissue generalizes: a new DLPFC
donor is already off-distribution. This is the same cross-donor gap the generalization-max
study diagnosed, now confirmed to widen monotonically with tissue distance
(DLPFC-donor 4.8 → breast 20.4 → mouse ∞/gated on Mahalanobis).

## Candidate training data — ranked by value to ADD

The goal is diverse donors/tissues we don't currently cover, that are *usable* (alignable
serial pair + shared gene panel). Ranked:

1. **Human cerebellum** (`V1_Human_Brain_Section_1/2`) — overlap 0.95, clean serial pair, a
   genuinely novel brain region (non-cortical). Strong candidate: currently off-dist
   (maha 9.3) yet adaptable, so it directly tests cross-tissue transfer.
2. **Human breast cancer** (`V1_Breast_Cancer_Block_A`) — overlap 0.95, alignable, a very
   different tissue (epithelial tumor, maha 20.4). The most off-distribution human dataset,
   so the highest-information add for teaching tissue-agnostic deformation.
3. **More DLPFC donors beyond the 3 in spatialLIBD** — same-tissue diversity, the lever the
   earlier study wanted but the dataset can't supply; would need other cortical Visium
   cohorts (e.g. additional brain Visium studies) with array-aligned serial sections.
4. **Mouse brain (sagittal ant/post, coronal)** — *only* if we build a separate mouse basis
   or ortholog-map to the human panel. At 0.1% overlap they are useless to the current human
   shared basis and are excluded from any human-panel training.

Whether adding #1 and #2 (cross-tissue, high-overlap) actually moves held-out error toward
PASTE2 — or whether cross-tissue diversity behaves differently from the same-tissue donor
trend — is exactly the question the follow-up **`atlas-train`** experiment tests.

## Caveats

- Error is measured by recovering a *synthetic* tear applied to the moving section, scored
  against array-bridge GT; it is a controlled deformation-recovery metric, not a real
  serial-section registration with independent ground truth.
- PASTE2 was run at full resolution for the local pairs and subsampled to ≤1500 spots for
  the downloaded pairs to bound its O(n²) cost; pitch-normalized error makes these
  comparable, but the subsampled numbers carry more variance.
- "In-distribution" is defined by the frozen DLPFC basis + training-donor Mahalanobis
  distribution; a differently-trained basis would move the boundary.
