# Sutura Genomics — Independent Validation Report
**Prepared for:** Sean Lee · **Date:** 2026-06-24 · **Scope:** every claim in `ARCA_Cofounder_Brief (3).pdf`

This report independently re-derives or refutes every load-bearing claim in the brief. All Sutura/PASTE2
numbers were **re-run from the actual code + data on this machine** (not taken on faith from the brief).
All external claims were verified against primary sources with resolving DOIs/URLs. Nothing here is
fabricated; where I could not verify something, it is marked.

> **One-line bottom line.** The brief's *in-sample* numbers are 100% real and I reproduced them exactly
> (Sutura 99→118 px; PASTE2 658→838 px). But the **headline "≈7× lower error / solves where every method
> fails" does not survive validation**: (1) the generalization test the brief lists as "in progress" was
> already run — **four times** — and is **negative every time** (held-out-donor error ≈ 1029–1593 px, i.e.
> ~1.7–2.5× **worse** than the PASTE2 baseline it claims to beat); (2) several competitor/novelty/OT-theory
> claims are wrong (STalign is not OT; "STaCker" is real, is deep-learning, and already recovers torn tissue;
> graph DL for ST alignment already exists). The *genuinely* solid, novel, publishable result is the **OT
> tearing-failure characterization** plus an **honest proof-of-concept + generalization study**. An abstract
> built on that is in [`ABSTRACT.md`](ABSTRACT.md).

---

## 1. Reproduction of the internal results (all numbers re-run here)

Environment built fresh: Python 3.12, numpy 1.26.4, torch 2.12.1, torch_geometric, scikit-learn, anndata,
PASTE2. Data re-downloaded from the **same** Figshare source the pipeline uses (article 22004273). Scripts:
[`validation/ablations.py`](ablations.py), [`validation/fetch_data.py`](fetch_data.py).

### 1.1 Brief's numbers vs. the on-disk CSVs vs. my re-run

| Brief claim | On-disk CSV | My independent re-run | Verdict |
|---|---|---|---|
| PASTE2 tear 658 → 838 px (+27%) | `sweep_deformation_cross_tear.csv`: 658.1 → 838.2 | (CSV is the compute; subsample re-run confirms direction) | ✅ accurate |
| PASTE2 smooth flat ~647 px | `sweep_deformation_cross.csv`: 639–658 | ✅ flat | ✅ accurate |
| Self-control 0 px, 99% acc | `sweep_deformation_self.csv`: 0.0, 0.993 | **0.0 px at sev0 AND sev8, 99% acc** (re-run) | ✅ accurate |
| Argmax tear 728 → 863 px | `sweep_deformation_argmax_tear.csv`: 728.6 → 863.1 | — | ✅ accurate |
| Alpha=0.5 tear strengthens | `sweep_deformation_tear_a0p5.csv`: slope +412 px > +180 px | — | ✅ accurate |
| Baseline 65.3% acc, 18.7% floor | `sweep_deformation_cross.csv` sev0: 0.6526 / 0.1866 | — | ✅ accurate |
| **Sutura tear 99 → 118 px (+19%)** | `arca_cross_curve.csv`: 99.2 → 118.0 | **99.1 → 118.0 px (exact)** | ✅ accurate |

**The brief does not fabricate any in-sample number.** Every figure traces to a real CSV and I reproduced
the headline Sutura curve to the decimal from the checkpoint `arca_cross.pt`.

Independent subsampled PASTE2 re-run (from scratch, n=300 spots) confirms the *qualitative* OT behavior:
self-control **0.0 px** (scoring is exact), smooth **≈ flat** (239→276 px), tear **degrades steeply**
(276→1227 px; label accuracy **64.7% → 42.3%**).

### 1.2 What the headline comparison actually measures (3 caveats the brief doesn't state)

These are not fraud — they are framing problems that a technical reviewer or a PI (Raphael, Fan) will raise
in the first email:

1. **The two raw slices are already pixel-aligned to 8.1 px (0.06 spot pitch).** I measured the array-bridge
   residual directly: each 151508 spot's own coordinate is 8 px from its 151507 ground-truth target. So the
   "predict the A-frame coordinate" task is essentially **inverting a known synthetic warp on one tissue**,
   and PASTE2's 647 px "floor" is **OT's own diffuse-plan smearing**, not 8 px of biology.
2. **Sutura is supervised on this exact tissue's ground truth; PASTE2 is unsupervised.** Sutura is trained on the
   array-bridge targets for 151507/151508 with held-out *warp seeds* but the **same tissue and the same fixed
   8,364-number target**. PASTE2 solves OT cold. This is learned-on-target vs. zero-shot — not apples to apples.
3. **"Robust to tears" is partly structural.** I shuffled the moving slice's coordinates (destroying geometry):
   error exploded to **3032 px**. But a *severe tear* shifts Sutura's predictions only **18.9 px** vs. unwarped.
   Sutura keys off **local graph neighborhoods + expression**, both of which a smooth warp/tear largely
   preserves — so a flat severity curve is partly built-in, not purely a learned tear-handling triumph.

> A naive **expression-nearest-neighbor baseline gets 2532 px** (not ~100 px). So Sutura is *not* trivial
> lookup — its learned attention metric is genuinely sharp. The catch is that this metric is learned **on
> this tissue**, which is exactly why it fails to transfer (next section).

### 1.3 THE CENTRAL FINDING — generalization is negative, and the brief misreports it as "in progress"

The brief's Status table says *"Leave-one-out generalization test — In progress."* It is **done**, recorded
in `RESUME.md` (2026-06-22) and in on-disk CSVs, and it is a **clean negative**. I also ran the one untested
fix (per-slice batch correction). Every configuration is negative:

| Train → held-out config | Held-out median sev0 → sev8 (px) | In spot-pitches | vs PASTE2 on the **same** held-out pair (526 → 691 px) |
|---|---|---|---|
| 1 donor, global features | 1508 → 1593 | ~11–12 | **~2.5× worse** |
| 1 donor, **perslice** (my run) | 1311 → 1372 | ~9.6–10 | ~2.2× worse |
| 3 donors, global | 1164 → 1289 | ~8.5–9.4 | ~2× worse |
| 3 donors, **perslice** (my run) | **1029 → 1096** | ~7.5–8 | **~1.7× worse** |

Two facts matter: (a) **the trend is monotonic and encouraging** — more donors + batch correction steadily
close the gap; (b) **even the best config is still ~1.7× worse than the OT baseline Sutura claims to beat**, on
unseen tissue. Mechanism (diagnosed, not guessed, in `RESUME.md` and confirmed by my ablations): cross-donor
batch effect → the held-out donor projects off-distribution → the trained encoder yields non-discriminative
embeddings → cross-attention collapses toward uniform → predictions shrink to the tissue centroid (~1000–1500 px).

The held-out pair 151669/151670 also **lacks Layers 1–2 entirely** (only L3–L6 + WM), a real compositional
shift that compounds the difficulty — worth stating explicitly.

**Implication:** the headline claim is an **in-sample** result. As written, the brief's Section 3.3 / Section 4
("Sutura is the alignment layer", "solves where every method structurally fails") is **not supported by the
team's own completed experiments.** This is the single most important thing to fix before any PI email,
preprint, or YC deck.

---

## 2. Scientific-thesis claims (the "why OT fails" argument)

| Brief statement | Verdict | Precise, defensible version |
|---|---|---|
| "PASTE2 and STalign use Optimal Transport (OT)" | ⚠️ **half wrong** | PASTE/PASTE2 = (partial) **Fused Gromov-Wasserstein OT** ✅. **STalign = LDDMM diffeomorphic, NOT OT** ❌. |
| "the math literally cannot represent the discontinuity a tear creates" | ❌ **imprecise** | An OT/Kantorovich coupling *can* represent many-to-one/abrupt correspondences. What fails is the **prior**: GW-OT assumes **near-isometry / preservation of within-slice pairwise distances** (Mémoli). A tear changes cross-seam distances → inflates the GW distortion cost (Dᵢₖ−D′ⱼₗ)² for the true match → optimum is pulled to a wrong, distance-preserving match. **Entropic regularization (Sinkhorn) further blurs the plan.** The "structurally cannot represent" language is literally true only for **diffeomorphic** methods (STalign/LDDMM), which cannot change topology — STalign's own paper concedes it "cannot accommodate holes or other topological differences." |
| "tearing is one of the most common failure modes … no existing tool handles it well" | ⚠️ **plausible but unsubstantiated** | No benchmark I found quantifies tear frequency, and **STaCker already partially recovers a severed DLPFC slice**. Soften to: "no ST tool handles tears *by design*; smoothness/isometry/diffeomorphic priors make incumbents ill-suited to them." |

**Net:** keep the mechanism (it's a real, publishable insight), but **fix the wording**: say *"tears violate the
near-isometry prior of GW-OT and are smoothed by entropic regularization; diffeomorphic methods cannot
represent a tear at all."* Sources (all resolved): PASTE `10.1038/s41592-022-01459-6`; PASTE2
`10.1101/2023.01.08.523162` (Genome Research 2023); STalign `10.1038/s41467-023-43915-7`; Mémoli GW (2011);
Peyré & Cuturi *Computational OT* `arXiv:1803.00567`; Cuturi Sinkhorn (2013).

---

## 3. Novelty / prior-art (the "structurally distinct from every existing method" claim)

❌ **Not defensible as written.** Every building block exists, and a close competitor already does the whole thing:

- **Graph DL for ST alignment already exists:** STAligner (graph attention, `10.1038/s43588-023-00528-w`),
  SLAT (GCN + adversarial, `10.1038/s41467-023-43105-5`), CAST (deep GNN, `10.1038/s41592-024-02410-7`),
  SANTO (dynamic graph CNN, `10.1038/s41467-024-50308-x`), SPACEL/GraphST (GCNs).
- **Cross-attention + learned deformation fields exist** in medical/point-cloud registration: XMorpher / Deformable
  Cross-Attention Transformer (`arXiv:2303.06179`), VoxelMorph (`arXiv:1809.05231`), deep graph matching.
- **Local/discontinuity-tolerant smoothness exists:** learned spatially-varying regularization, sliding-motion
  registration (Chen et al. 2024, `arXiv:2412.17982`).
- **A per-spot deformation field for ST already exists — and handles tears:** **STaCker** (*Sci Rep* 2025,
  `10.1038/s41598-025-01862-x`), a U-Net elastic registration that I confirmed "was the only program that
  partially restored the severed portion" of a torn DLPFC slice.

✅ **The honest, still-novel claim:** *Sutura may be the first to combine **cross-attention correspondence between
two ST slice-graphs** with a **learned per-spot displacement field** and **explicit local-only
(tear-tolerant) smoothness**, purpose-built for torn ST tissue.* That is a **combination/application** claim.
**Sutura must benchmark against STaCker** (the closest learned-deformation ST competitor) — its absence from the
brief is a gap.

---

## 4. Market / dataset claims

**Market — broadly defensible, drop one superlative.** ST market ≈ **$300–600M (2023–24), CAGR ~12–15%**
consensus (MarketsandMarkets $554.5M→$995.7M 2024–29 @12.4%; Grand View ~$337.5M 2023 @15.2%); 17–21% figures
are outliers — cite a range. Adoption is *understated*, not overstated: Nature Methods **Method of the Year
2020** (`10.1038/s41592-020-01033-y`); publications rose from <100/yr to **~630 in 2023 across 2,049
institutions in 65 countries** (`PMC11164738`). Replace "one of the fastest-growing areas in biology"
(unprovable) with those two citable facts. Visium/Slide-seq/MERFISH all real; Visium pitch **100 µm / 55 µm** ✅.

**Dataset — fully verified.** Maynard et al. 2021, *Nat Neurosci*, "Transcriptome-scale spatial gene
expression in the human DLPFC," **DOI `10.1038/s41593-020-00787-0`, PMID `33558695`**; 12 samples / 3
subjects; L1–L6+WM annotations (I confirmed the layer tables in the downloaded h5ad). Subject groupings:
**Br5292 = 151507–510, Br5595 = 151669–672, Br8100 = 151673–676** — so 151507/508 (train) and 151669/670
(held-out) are genuinely different donors. Figshare **22004273** (CC BY 4.0) exists and hosts the files. Two
honesty notes: the **array bridge is approximate** (adjacent sections are different tissue, here 300 µm apart),
and the **"pitch ~137 px" is image-space pixels** (scalefactor-dependent), *not* the physical 100 µm — don't
conflate the two figures.

---

## 5. Outreach targets (verified PIs, use lab URLs — do not invent emails)

| Priority | PI | Institution | Why (method) | Verified URL |
|---|---|---|---|---|
| ★★★ | **Benjamin Raphael** | Princeton CS | **PASTE/PASTE2** (the OT methods Sutura argues against) | cs.princeton.edu/~braphael/ |
| ★★★ | **Jean Fan** | Johns Hopkins BME | **STalign** (diffeomorphic) | jef.works |
| ★★★ | **Kristen Maynard** | Lieber Institute | generated the **exact DLPFC dataset** (PMID 33558695) | scholar.google.com (yOdhxxYAAAAJ) |
| ★★ | Evan Macosko / Fei Chen | Broad/Harvard | Slide-seq | macoskolab.com · hscrb.harvard.edu/people/fei-chen |
| ★★ | Xiaowei Zhuang | Harvard/HHMI | MERFISH | zhuang.harvard.edu/merfish.html |
| ★★ | Rahul Satija | NYGC | Seurat | nygenome.org/.../rahul-satija-phd |
| ★ | Fabian Theis | Helmholtz Munich | squidpy/scanpy | helmholtz-munich.de/en/icb/fabian-theis |
| ★ | Mingyao Li | UPenn | SpaGCN/iStar | dbei.med.upenn.edu/staff/mingyao-li-phd |
| ★ | Rong Fan | Yale | DBiT-seq | (Yale BME) |
| ★ | Lior Pachter | Caltech | kallisto/spatial | pachterlab.github.io/group.html |

Raphael and Fan are simultaneously the best adopters *and* the sharpest critics of the OT/tear thesis — emailing
them early doubles as technical validation.

---

## 6. What to fix in the brief (priority order)

1. **Correct the LOO status to "done — negative," and reframe the headline as in-sample.** (Load-bearing.)
2. **Add STaCker** as a competitor and a benchmark target; remove "no tool handles tears" / "STaCker uses OT."
3. **Fix the OT wording** ("violates the near-isometry prior" / reserve "structurally cannot" for diffeomorphic).
4. **Soften "structurally distinct from every existing method"** to the combination/application claim.
5. **Correct STalign** (LDDMM, not OT).
6. Market: cite Method-of-the-Year + publication curve + a CAGR *range*; drop the superlative.
7. Note the array bridge is approximate and px ≠ µm.

All raw evidence: result CSVs in `results/`, my scripts in `validation/`, research JSON dump captured in the
session. Every DOI/PMID above resolved to the correct paper.
