# Sutura Genomics

**The alignment layer for spatial transcriptomics.** Graph deep learning for
tissue registration — built for the tears optimal transport can't represent.

This repository is the Sutura Genomics marketing site (Next.js). The section
below tracks the state of **ARCA**, the registration model the product is built
on, so the public-facing claims stay tied to what the research actually shows.

---

## ARCA — research status

ARCA is a learned (graph encoder + cross-attention + deformation head) registrar
for aligning spatial-transcriptomics tissue slices. The target is **torn /
non-isometric warps** — the failure mode where the optimal-transport baseline
(**PASTE2**) is weakest. Error metric: median registration error in pixels
(spot pitch ≈ 137 px). DLPFC dataset, array-bridge ground truth.

We report this honestly: ARCA is excellent in-distribution and is **not yet a
solved generalization story** across donors. Both halves are below.

### 1. In-distribution head-to-head — strong (validated)

Trained and evaluated on the same tissue pair (held-out warp seeds), torn regime:

| severity | PASTE2 (OT) | ARCA |
|---------:|------------:|-----:|
| 0        | 658 px      | 99 px |
| 8        | 838 px      | 118 px |

ARCA is ~6.6–7× lower across the sweep and stays **sub-spot-pitch** at every
severity, where PASTE2 drifts 5–6 pitches off. Caveat: the error *tail* grows at
the torn seam (sev8 p90 ≈ 1205 px) — most spots stay sub-pitch, the discontinuity
itself is the hard tail.

### 2. Cross-donor generalization — open problem (honest negative)

Leave-one-donor-out (train on 2 donors, test the held-out 3rd, all 3 folds):
ARCA stays excellent on its training donors (82–148 px) but lands **~1080–1557 px
out-of-sample** and **loses to PASTE2** (407–838 px) on every unseen donor. The
in-distribution win is real but does **not** transfer as originally built.

Diagnosed mechanism: cross-donor batch effect → off-distribution embeddings →
cross-attention matches to confident-but-wrong locations on unseen tissue. The
gap is in cross-donor **correspondence alignment**, not the deformation head.

### 3. Contrastive correspondence loss — closing the gap (in progress)

Latest direction: a donor-invariant InfoNCE-style correspondence loss to make the
*similarity geometry* (not just per-spot features) transfer. Held-out fold S1
(PASTE2 reference 658 → 838 px):

| config (held-out S1)    | sev0 → sev8 |
|-------------------------|------------:|
| baseline (no contrast)  | 1327 → 1538 px |
| cosine, λ=0.5           | 995 → 1178 px |
| cosine, λ=2.0           | 1070 → 1200 px |
| **attn, λ=0.5**         | **834 → 994 px** |

The contrastive loss roughly halves the cross-donor gap (1254 → 834 px on this
fold) and nearly ties PASTE2 at high severity — but does **not** yet beat it. The
full 3-fold × {readout, λ} matrix is still running; numbers above are fold S1 only
and should not be read as the final result.

---

## Getting started (website)

This is a [Next.js](https://nextjs.org) app.

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

- Landing page: `src/app/page.tsx`
- Demo / contact form: `src/app/demo/page.tsx`
- Deploys via Netlify (`netlify.toml`).
