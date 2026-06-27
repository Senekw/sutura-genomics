# Sutura Genomics — Abstract v3 (error bars + 3-fold generalization + magnitude control)

v3 folds in the four follow-up experiments (items 1–4) plus **held-out multi-seed error bars on folds S2/S3**
(ms-lodo). Every number now has a seed/fold basis and traces to `results/*.csv` (provenance:
`results/v3_aggregates.txt`, `results/sutura_multiseed_tear.csv`, `results/sutura_multiseed_lodo.csv`,
`results/ms_lodo_summary.txt`). This is the strongest *honest* version: the benchmark claim is multi-seed **and**
magnitude-controlled, and the negative generalization result is confirmed across **all three** donors — with
5-seed 95% CIs on two of them.

---

## Title

**Tissue tearing degrades optimal-transport registration of spatial transcriptomics beyond displacement
magnitude: a multi-seed deformation benchmark and a supervised graph cross-attention proof-of-concept**

---

## Abstract (≈300 words)

**Background.** Three-dimensional reconstruction from serial spatial-transcriptomics (ST) sections requires
registering adjacent slices, but physical sectioning introduces *tears* — discontinuous, non-isometric
deformations. Leading methods rely on priors that tears strain: PASTE/PASTE2 use Fused Gromov-Wasserstein
optimal transport (OT), which assumes near-isometric preservation of within-slice distances, and STalign uses
diffeomorphic (LDDMM) mapping, which cannot change tissue topology. Learned-deformation ST methods are emerging
(STaCker, INST-Align), but OT/diffeomorphic behaviour under tearing has not been systematically characterised.

**Methods.** On the spatialLIBD human DLPFC Visium dataset (Maynard et al., 2021; 3 donors), we build a
controlled benchmark — known smooth warps, single-block rigid tears (expression unchanged), and an identity
self-control — at severities of 0–8 spot pitches, scored against an approximate array-position ground truth
(~8 px residual). We evaluate two unsupervised incumbents — **PASTE2** (OT, over five warp seeds) and
**STalign** (diffeomorphic LDDMM) — add a **magnitude-matched smooth control**, and
test a minimal graph model, **Sutura** (per-slice graph encoder → cross-attention correspondence → per-spot
displacement; spatial coupling is local kNN message passing only, no explicit smoothness penalty). Sutura is
trained **supervised** on each tissue's ground truth; PASTE2 is unsupervised. Generalisation is assessed by
**leave-one-donor-out across all three donors**.

**Results.** OT registration is robust to smooth warps but degrades reproducibly under tearing: nearest-
correspondence (argmax) error **722±5 → 855±27 px** and layer accuracy **64.9%→60.5%** (mean±95% CI, 5 seeds).
The effect is not merely displacement magnitude: at a *matched* mean displacement (~2000 px), a smooth warp costs
769 px / 60.2% accuracy whereas a tear costs **863 px / 57.5%** — an extra ~100 px and ~3 points attributable to
the discontinuity. The diffeomorphic baseline STalign behaves analogously but more sharply — near-perfect on
small deformation (79 px median) yet collapsing under the tear (866 px, an ~11× rise) — so two incumbent classes
(OT and diffeomorphic) both fail at tears, by smearing and by smooth-overshoot respectively. Trained and
evaluated on the *same donor*, Sutura fits torn-tissue correspondence to a
**median 99→106 px** (5-seed; the previously reported 118 px was an unlucky single seed) — non-trivial versus an
expression-nearest-neighbour baseline (2532 px) — but this is a **supervised, in-sample** result, and a *soft*
coordinate regression: forced to a hard one-spot-per-spot assignment it is **~138 px (≈1 spot pitch)**, so part of
the sub-pitch headline is interpolation between array positions, not per-spot sub-pitch localisation. Critically,
under leave-one-donor-out the advantage vanishes on **all three donors**. On the two held-out folds scored over
**five warp seeds**, median error is **1236±2→1373±34 px** (per-slice standardisation) / **1429±3→1584±52 px**
(pooled) — flat across severity but **~1.8–3.6× worse than PASTE2** on the same unseen tissue (held-out PASTE2
**397±7→697±18 px**, 5 seeds); the third fold is consistent (single-seed 1041–1538 px). Per-slice feature
standardisation narrows the gap but never closes it, and **no batch-integration method (Harmony/Scanorama) was
applied** — donor-invariance remains open.

**Conclusion.** Tearing is a real, magnitude-controlled failure mode of OT/diffeomorphic ST registration. A
learned local-correspondence model fits it in-sample, but donor-invariant generalisation — a recognised hard
problem for deep ST models — remains open across every donor tested. We both quantify the gap (5-seed CIs on two
held-out donors) and **diagnose its mechanism**: cross-donor batch shift pushes held-out expression embeddings
off-distribution, collapsing cross-attention toward uniform so predictions regress to the tissue centroid. This
defines the path (batch integration + multi-donor encoders + a contrastive correspondence loss) and the benchmark
against learned-deformation incumbents (STaCker, INST-Align).

---

## What changed v2 → v3 (all from new experiments)

| v2 (single-seed) | v3 (validated) | Source |
|---|---|---|
| OT tear "658→838" (1 seed) | OT argmax **722±5 → 855±27 px**, acc 64.9%→60.5% (5 seeds, CIs) | item 1b |
| tear-vs-smooth confounded by displacement | **magnitude-matched:** at ~2000 px mean disp, tear 863 vs smooth 769 px (argmax); acc 57.5% vs 60.2% | item 4 |
| Sutura in-sample "99→118" (1 seed) | **99→106 px median** (5 seeds, CI); 118 was an unlucky seed | item 1 |
| generalization = 1 fold (1029–1593) | **3-fold LODO, folds S2/S3 now 5-seed: held-out 1236–1584 px (±2–52 CI), ~1.8–3.6× worse than PASTE2 (397±7→697±18)** | item 3 + ms-lodo |
| fair estimator not shown | Sutura hard-correspondence ~137 px vs PASTE2 argmax 722–855 px (in-sample) | item 2 |

## Net effect of the validation
- **Strengthened:** the OT-tearing thesis is now multi-seed **and** magnitude-controlled (the falsify lane's
  "magnitude confound" is resolved in the thesis's favour).
- **Confirmed with error bars:** the negative cross-donor result holds on **all three** donors, and folds S2/S3
  now carry **5-seed 95% CIs (±2–52 px)** — the held-out gap is a real ~1.8–3.6× deficit, not seed noise.
- **Corrected:** the headline degradation was overstated by a single unlucky seed (+19% → ~+7% in-sample).
- **Unchanged conclusion:** publishable contribution = the benchmark + honest negative; the *method* is an
  in-sample proof-of-concept that does not yet generalise.

## Competitive benchmark (item 5 — partially done)
- ✅ **STalign** (diffeomorphic, the brief's named competitor) was run on this exact benchmark: in-sample
  79→866 px median (sev0→8). On the **held-out donors** it is even more telling — zero-shot **108–199 px at sev0**
  (untrained, beating Sutura's *supervised* in-sample number) collapsing to **744–903 px** at the tear — so the
  diffeomorphic-collapse reproduces out-of-donor. See `validation/COMPETITIVE_BENCHMARK.md`.
- ❌ **STaCker** could not be run (it is an *image*-registration method needing H&E histology our coordinate-warp
  benchmark lacks, and has no public code repo) and ❌ **INST-Align** could not be run (code unreleased as of
  Jun 2026). Their published DLPFC numbers are the only available reference; no head-to-head was fabricated.

## Remaining (not blocking an honest submission)
- The **S1-held-out fold (heldBr5292) is still single-seed**; its multi-seed CIs would make all three folds
  symmetric (PASTE2 and STalign for that pair are already on disk — only one Sutura eval to add).
- Benchmark vs STaCker / INST-Align once code/images are available; a real-torn-tissue example (item 7). These
  upgrade the competitive and ecological-validity claims but are not needed for the current claims to be honest.
- **Highest-value next run if this becomes a full paper:** one independent *learned*-deformation baseline
  (GPSA / STAligner) on the same tear benchmark — it decides whether the non-generalisation is Sutura-specific
  or a field-wide property of learned local-correspondence models.
