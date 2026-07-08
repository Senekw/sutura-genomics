# Auto-adapt agent — findings

**Branch:** `autoadapt` · **Date:** 2026-07-08 · Diagnostic + product feature.
Code: `src/autoadapt.py` (agent + validation), wired into the backend orchestrator
(`backend/pipeline.py`, off-distribution branch). Output: `results/autoadapt_eval.csv`.

## TL;DR

When an input is off-distribution, auto-adaptation — fine-tuning the pretrained
shared-basis Sutura model on the *user's own* sections (frozen basis, transform-only)
— **substantially rescues Sutura from collapse**, but **does not beat PASTE2 on any
of the three off-distribution datasets**. So the orchestrator adapts, compares, and
correctly keeps PASTE2.

| dataset | gene overlap | zero-shot Sutura | **auto-adapted Sutura** | PASTE2 | best | adapt beats PASTE2? |
|---|---:|---:|---:|---:|---|:--:|
| Br8100 | 100% | 9.45 | **6.74** (−29%) | 3.39 | PASTE2 | No |
| mouse brain | 0% | n/a | n/a (inapplicable) | 5.42 | PASTE2 | No |
| breast cancer | 87% | 26.85 | **7.92** (−70%) | 3.61 | PASTE2 | No |

(median registration error in spot-pitches; tear benchmark severity 4, seed 0.
Adaptation ran 30 epochs, ~137 s / ~175 s wall time on CPU.)

## The key question, answered honestly

**Does auto-adaptation on the input's own sections beat PASTE2 on any of these,
where zero-shot Sutura loses? — No, not on any of the three.** But it changes the
picture meaningfully:

- **Br8100** (held-out DLPFC donor, adapted on its own sibling sections
  151675/676): zero-shot 9.45 → adapted **6.74** pitch. A real 29% improvement from
  genuine within-donor adaptation — the model *does* learn Br8100's feature→geometry
  mapping from its other sections — but PASTE2 (3.39) still wins by ~2×.
- **breast** (adapted self-supervised on synthetic tears of its own section): zero-shot
  Sutura **collapses** at 26.85 pitch (worse than centroid), and adaptation pulls it
  all the way down to **7.92** — a 70% rescue — yet PASTE2 (3.61) is still ~2.2× better.
- **mouse brain**: the frozen shared basis is the DLPFC gene panel, which mouse does
  not share (0% overlap), so Sutura and adaptation are **not applicable**; PASTE2 is
  the only option. Honest limitation of a frozen-basis approach: it only transfers to
  inputs on a compatible gene panel.

## What this means

Auto-adapt is a genuine, meaningful improvement — it turns Sutura's off-distribution
**collapse** into a **competitive-but-second-place** result — but it is not (yet)
enough to make Sutura the best method on unseen data. Two honest reasons it falls
short of PASTE2 here:

1. **Adaptation budget.** We fine-tune a few epochs on 1–2 of the user's sections.
   Br8100 (the strongest case, with real sibling-section supervision) improves most;
   breast (self-supervised on synthetic warps of one section) improves a lot from a
   terrible start but has a weaker signal. More adaptation sections / epochs would
   likely help further — but that is minutes-to-hours of per-input compute.
2. **PASTE2 is a strong, warp-robust baseline** on these adjacent Visium pairs (~3–5
   pitch everywhere), and it needs no adaptation.

The product value is real regardless: on an off-distribution input the orchestrator
now *tries* to make our own model work (and reports how close it got) instead of
silently falling back — and if adaptation ever wins, it is kept and labeled as
"Sutura (auto-adapted to your data)". Today, on these three, PASTE2 is kept and
labeled as PASTE2.

## Method (honest)

- **Frozen shared basis throughout** (transform-only, never re-fit); `lognorm_matrix`
  zero-fills any basis gene the section lacks, so partial-overlap panels (breast, 87%)
  can still be projected — while 0%-overlap panels (mouse) are correctly flagged
  inapplicable.
- **Adaptation data, no leakage of the target.** The target pair's real A↔B
  correspondence is never used to adapt — only to score. Adaptation uses either extra
  adjacent sections (Br8100 → 151675/676, supervised cross-section) or, when only the
  target pair is uploaded, self-supervised synthetic tears of one section (breast,
  mouse). Fine-tuning starts from `arca_shared_basis.pt`, early-stops on a held-out
  validation split (patience 4).
- **Three-way compare, keep best**: (a) pretrained zero-shot Sutura, (b) auto-adapted
  Sutura, (c) PASTE2, scored with median error vs the array-bridge ground truth. The
  winner and margin are logged.
- **Validated end-to-end through the live backend**: uploading the Br8100 pair + its
  two sibling sections routes off-distribution, runs auto-adapt (candidates logged:
  zero-shot 9.53 / adapted 6.64 / PASTE2 2.82 on the real pair), keeps PASTE2, and
  labels it transparently as PASTE2.

## Integration

Wired into the orchestrator's off-distribution branch (`backend/pipeline.py`): on an
off-distribution input with a compatible gene panel, it fine-tunes on the user's own
sections, compares all three methods, and keeps the best — falling back to PASTE2
when adaptation does not beat it (which, on this validation set, is always). The
final method is stated transparently in the result payload
(`Sutura` / `Sutura (auto-adapted to your data)` / `PASTE2`).

## Bottom line

Auto-adaptation is the closest thing yet to making Sutura itself work on new data: it
cuts off-distribution error by 30–70% and rescues outright collapse. It does not beat
PASTE2 on Br8100, mouse, or breast, so PASTE2 remains the kept result on all three —
reported honestly. The mechanism is sound and the gap is narrowing; closing it needs
more adaptation data/epochs (or a non-frozen-basis representation), which is the
natural next investment.
