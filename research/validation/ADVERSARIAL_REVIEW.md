# Sutura Genomics — Adversarial Review Verdict
**reviewer2 + falsify-all + harden + surveil, run against the Sutura abstract — 2026-06-24**
**Scope:** Sutura project only (`/Users/seangplee/biostartup-main`). Zero contact with the GL/`GI brain 2` project.
25 agents · ~1.8M tokens. Raw output archived in session. Hardened abstract → [`ABSTRACT_v2.md`](ABSTRACT_v2.md).

## TL;DR
The honest abstract survived better than the original brief would have, but the panel found **2 fatal + several
major issues** that must be fixed before submission, and the **novelty claim is now effectively dead** (a crowded
2024–2026 field, incl. an April-2026 paper architecturally adjacent to Sutura). **The one thing that survived
every attack is the central negative finding** — Sutura does not generalize across donors. The genuinely
publishable contribution is the **OT/diffeomorphic tearing-failure characterization**, scoped honestly.

---

## 1. Reviewer panel — all three axes: **MAJOR REVISION**

| Axis | Verdict | Worst finding |
|---|---|---|
| Methods & statistics | major-revision | **FATAL ×2** (below) |
| Novelty & prior art | major-revision | STaCker (+ INST-Align) absent & un-benchmarked; "first to combine" indefensible |
| Overclaiming & framing | major-revision | asymmetric presentation (7× in-sample win quantified; out-of-sample loss softened to "not parity") |

**FATAL 1 — the "≈7×" compares two different estimators.** Sutura's error is a *direct supervised regression
residual*; PASTE2's ~647 px is a *barycentric projection of a diffuse OT plan* (`scoring.py:70–83`) that smears
toward the centroid. Not like-for-like. Fix: use PASTE2's **argmax** projection as the head-to-head number
(already computed: **728→863 px in-sample, 600→730 px held-out**), call the ~647 floor an OT smearing artifact,
and drop the bare "7×."

**FATAL 2 — supervised-on-target vs zero-shot is decisive and was missing from the abstract.** Sutura minimizes
`||pred − gt_A||` onto the *exact array-bridge coordinates it is later scored against* (`train_cross.py:244,270`),
with held-out warp *seeds* but the same fixed target on the same tissue; PASTE2 solves OT cold. The in-sample
99→118 px is a fit-to-target curve, not a zero-shot accuracy comparable to PASTE2. Must be stated in the abstract.

**Other majors:** single eval seed / no error bars (every curve is `seed=0`); the synthetic "tear" is a rigid
block-translation with expression untouched (milder/more learnable than a real tear); the array-bridge GT is
approximate (~300 µm / ~8 px), so "<1 pitch" claims sit below the GT's own uncertainty.

---

## 2. Falsification — 5 claims × 3 independent skeptics

| # | Claim | Verdict |
|---|---|---|
| C1 | OT robust to smooth, degrades under tearing | **SURVIVES, weakened** — tear arm carries a *larger total displacement* than the smooth arm (`warp_slice.py:64–76` adds a rigid offset **on top of** the smooth field), so magnitude isn't matched. Mitigated by: survives argmax + strengthens at α=0.5 + 0 px self-control. |
| C2 | Sutura 99→118 in-sample is a genuine learned correspondence | **SURVIVES, weakened** — true vs expression-NN (2532 px), but wrong-floor + supervised-on-target. |
| C3 | **Sutura does NOT generalize (held-out 1029–1593 px, ~1.7–2.5× worse)** | **SURVIVES — unanimous (0 falls).** Skeptics attacked it as under-training/a bug and it held under direct re-experiment. The negative is robust. |
| C4 | Tears violate GW-OT near-isometry prior; diffeomorphic structurally cannot represent a tear | **SURVIVES, weakened** — half 2 (diffeomorphic) is rock-solid; half 1's *attribution* is muddied by the magnitude confound (C1). |
| C5 | Novelty = defensible combination claim | **SURVIVES, weakened — and the "local smoothness" leg is VAPORWARE.** |

> **Critical (C5):** the abstract/brief claim a "local smoothness **regularizer**" so tears "aren't forced to
> agree." A grep of all training code shows **no such term** — the loss is plain `||pred − gt||`. The locality is
> only the kNN message-passing receptive field, not an explicit penalty. **This must be corrected, not just
> softened** — it is an implementation-vs-claim mismatch a reviewer will catch immediately.

---

## 3. Harden gates — provenance ✅ / **statistics ❌** / citations ✅

- **Provenance (10/12 → now 12/12):** every headline number traces to a real `results/*.csv`. The two weak links
  (expression-NN 2532 px; the held-out range) were prose-only — now persisted to
  `results/validation_ablations_run.txt`.
- **Statistics (0/8 PASS) — the real weak point.** (a) "7× / <1 pitch throughout" is **median-only**: the same
  CSV shows **mean +176%, p90 +503%** exploding at sev8 — report median (mean, p90). (b) **FAIL: single eval
  seed, no CIs on any headline number.** (c) the 4 LOO configs are **point estimates, not 4 independent samples**
  → "monotonic" is not a statistical claim. (d) supervised-vs-unsupervised; (e) approximate GT.
- **Citations (5/6 PASS):** all six external DOIs resolve to the correct papers and support their claims (Maynard,
  PASTE, PASTE2, STalign, STaCker, Method-of-the-Year). Only nuance: the PASTE2 DOI is the bioRxiv preprint (later
  Genome Research 2023) — cite both.

---

## 4. Surveillance — the field is more crowded than the first pass found

**New competitive threats (2024–2026):**
- **INST-Align** (arXiv:2604.12084, **13 Apr 2026** — *I personally verified this*): "Implicit Neural Alignment
  for Spatial Transcriptomics via Canonical Expression Fields" — a learned coordinate-based **deformation network**
  whose canonical field "**absorbs batch variation**," strong on **large-deformation** sections across 9 datasets.
  Architecturally adjacent to Sutura and explicitly targets the batch/deformation frontier Sutura claims. **Two
  months old.**
- **STaCker** (Sci Rep 2025, *verified*): learned per-spot deformation; already partially recovers a severed DLPFC
  slice. The single closest prior-art competitor — **must be benchmarked.**
- *Surveil-agent-verified (not personally re-fetched):* **JADE** (NeurIPS 2025, attention+OT+graph on DLPFC),
  **AlignDG** (Genome Medicine 2026, cross-condition alignment), **ST-GEARS** (OT camp already does non-rigid ST
  correction — undercuts "OT can't do non-rigid"), **OT-knn** (2026, OT robust to donor heterogeneity).

**Supports for the positioning:**
- **STalign** confirms the not-OT correction. A 2025 batch-effects ST benchmark and **ST-DAI** (arXiv:2507.21516)
  independently establish that **cross-donor generalization is a recognized hard failure mode** of deep ST models
  — i.e., Sutura's negative result is a *known, important* gap, not an embarrassment.

**Implication:** "first to combine cross-attention + per-spot displacement + local smoothness for torn ST" is
**not defensible** — drop it. Reframe novelty as: *an independent, controlled characterization of the OT/
diffeomorphic tearing failure mode, plus a minimal proof-of-concept,* and **benchmark against STaCker and
INST-Align** explicitly.

---

## 5. Prioritized fix list (folded into ABSTRACT_v2.md)

1. **Drop bare "7×"; report PASTE2 argmax (728→863) head-to-head; label the ~647 floor an OT artifact; report median (mean, p90).** [FATAL]
2. **State supervised-on-target vs zero-shot in the abstract.** [FATAL]
3. **Correct the "local smoothness regularizer" → "local kNN message passing only; no explicit smoothness penalty."** [implementation mismatch]
4. **Replace "do not yet reach OT parity" with "~1.7–2.5× worse than PASTE2 on held-out donors."** [framing]
5. **Single-seed / single-fold stated; drop "systematically"/"monotonic" as statistical claims.** [stats]
6. **Add STaCker + INST-Align; drop "first to combine"; reframe novelty as benchmark + proof-of-concept.** [novelty]
7. **Scope OT-failure to "synthetic block-translation tears on DLPFC"; note tear-arm magnitude isn't matched, but argmax/α=0.5/self-control controls implicate the discontinuity.** [stats/honesty]
8. **Retitle: "alternative" → "proof-of-concept."** [framing]

**Net:** the negative generalization finding and the OT-tearing characterization are bulletproof; the *method*
claims and *novelty* are not. The v2 abstract keeps only what survived all four lanes.
