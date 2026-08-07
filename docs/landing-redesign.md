# Landing page redesign — design spec

**Status:** proposal, not implemented. Written for review before any code lands.
**Scope:** `src/app/page.tsx`, `src/app/globals.css`, `src/app/layout.tsx`, plus a new
hero visual component and a trimmed hero data payload.

---

## 1. Diagnosis — why the current page reads as generic

### 1.1 It is a literal port of another company's site

`src/app/globals.css:89-91` says so in its own comment:

> `Cuebench-faithful landing — exact port of cuebench.dev. Values lifted 1:1 from
> cuebench.dev's stylesheet (ink #111, muted #8a8a8a, hair rgba(17,17,17,.10),
> 13px/28px pill, 74px divider, rise 0.8s stagger).`

Every visual decision on the page — colour, type scale, button geometry, divider
width, animation timing — was inherited rather than chosen. Nothing about the
result is specific to Sutura, because nothing about it was derived from Sutura.

One inherited value is actively wrong: `--cb-yc: #fb651e` (`globals.css:96`) is
**Y Combinator orange**, and it is currently the focus-ring colour on every
interactive element of the landing page (`globals.css:266-271`). Sutura is not a
YC company. This should be removed regardless of whether the rest of the redesign
proceeds.

### 1.2 The structure is the default AI-startup single screen

Centered logo → animated tagline → one black pill → founder names → copyright.
This layout is close to a genre convention at this point. It signals "pre-product
landing page" — which is precisely the wrong signal for a company that has a
working model, a benchmark suite, and a functioning demo.

### 1.3 The typewriter costs more than it earns

`page.tsx:47-58` cycles three taglines at 55ms/char with a 2400ms hold:

- "The alignment layer for spatial transcriptomics"
- "Graph deep learning for tissue registration"
- "Built for the tears optimal transport can't represent"

The third is the only differentiated one, and a visitor reaches it ~11 seconds in
— well past the point most people leave. At any given moment the page displays a
partial sentence, so there is no glanceable statement of what the company does.
The animation also produces no stable text for social/OG preview scraping, and
`.tagline` reserves only `min-height: 1.7em` (`globals.css:153`), so the copy is
constrained to one line by layout rather than by editing.

**Recommendation: static headline.** Set the strongest line in type and leave it
there.

### 1.4 The site withholds its own evidence

This is the substantive problem; the styling issues are secondary to it.

The repository contains material that essentially no competitor landing page has:

| Asset | Location | Currently visible on marketing site |
|---|---|---|
| Two-incumbent head-to-head benchmark | `research/validation/COMPETITIVE_BENCHMARK.md` | No |
| Honest cross-donor negative result (3-fold LOO) | `research/RESUME.md`, `README.md` | No |
| Contrastive-loss progress table | `README.md` | No |
| WebGL volume renderer, custom shaders | `src/app/demo/results/TissueStack3D.tsx` | No — behind `/demo/login` |
| Real spatialLIBD tissue geometry, 4 sections × 3,000 spots | `public/demo/br5292_stack.json` | No — behind `/demo/login` |
| Figures (benchmark, LODO, architecture) | `research/figures/*.png` | No |

A spatial-transcriptomics company's homepage currently contains nothing spatial:
no tissue, no registration, no data, no figure. The single most effective change
available is not restyling — it is moving evidence you already own onto the page.

### 1.5 Smaller credibility leaks

- Two `@gmail.com` addresses are the only contact route (`page.tsx:13,15`).
  Domain email would cost nothing and read very differently to an institutional
  buyer.
- `Jost` (`layout.tsx:5-9`) is a free Futura clone in extremely wide use. It is
  not bad, but it is not a decision.
- `metadata` (`layout.tsx:11-15`) has no `openGraph`, no `twitter` card, and no
  OG image, so every shared link renders as a bare text stub.

---

## 2. Numbers integrity — resolve before anything ships publicly

The redesign puts benchmark numbers on a public page. Three discrepancies between
`src/lib/demoDatasets.ts` and the validated research must be settled first. This
section is the highest-priority item in this document; a benchmark table is only
an asset if every row survives scrutiny.

### 2.1 GPSA was never run

`demoDatasets.ts:100` lists:

```ts
{ method: "GPSA", median: "931 px", p90: "1,523 px", acc: "57.4%" },
```

There is no GPSA run anywhere in `research/`. The only mention of GPSA in the
whole repository is `research/validation/ABSTRACT_v3.md:114`, which lists it as
**future work** ("…on the same tear benchmark — it decides whether the
non-generalisation is Sutura-specific"). `COMPETITIVE_BENCHMARK.md` is explicit
about the standard applied elsewhere: *"I did not invent head-to-head numbers for
methods I could not execute."*

**Action: delete the GPSA row** from the demo, and do not put it on the landing
page. It is currently the one claim on the site that the research does not
support.

### 2.2 The STalign row is the sev8 number presented as a general result

`demoDatasets.ts:99` lists STalign at 866 px median. Per
`COMPETITIVE_BENCHMARK.md` §3, that is STalign's **severity-8** figure. At
severity 0, STalign scores **79 px — better than Sutura's 99 px**.

Presenting only 866 px implies STalign is uniformly weak. It isn't; it is
excellent on small deformation and collapses specifically at the tear. That
collapse (+11× from sev0→sev8) is a *stronger* argument for Sutura's thesis than
a flat "we beat them" row, because it isolates the failure to topology change
exactly as the thesis predicts.

**Action: publish the severity curve, not a single row.** See §4.4.

### 2.3 Two different headline numbers are in circulation

- `README.md`: ARCA 99 px vs PASTE2 658 px (sev0)
- `demoDatasets.ts:97-98`: Sutura 109 px vs PASTE2 732 px

These are presumably different seeds or aggregations, but the site should pick
one canonical pair, state its provenance inline, and use it everywhere.

### 2.4 Every published number needs its qualifier attached

`COMPETITIVE_BENCHMARK.md` §5 is unambiguous: Sutura's win is **supervised and
in-sample**, and out-of-sample it loses to both incumbents. Any headline number
on the landing page must carry "in-distribution, supervised" adjacent to it — not
in a footnote. §4.5 makes this a feature rather than a disclaimer.

---

## 3. Design direction

**Position:** a research lab that publishes its failures, not a startup landing
page. The credibility of the negative result is the brand. Every design decision
below serves reading the evidence, not decorating it.

Three principles:

1. **Derive the identity from the domain.** Colour comes from the cortical layer
   palette already in the product; motion comes from registration; the grid comes
   from the Visium spot lattice. Nothing borrowed from another company's CSS.
2. **Data is the ornament.** No decorative gradients, no abstract mesh blobs. The
   only large visual is real tissue.
3. **Publish the negative.** Give the failure the same typographic weight as the
   win.

### 3.1 Colour

Source the palette from `demoDatasets.ts:75-81` — the L1→WM cortical ramp already
shipping in the product. It is spectral, domain-derived, and unmistakably yours.

```css
/* Cortical layer ramp — L1 → WM. Source: demoDatasets.ts DLPFC regions. */
--layer-l1: #5e4fa2;   /* deep violet   */
--layer-l2: #3a7ecf;
--layer-l3: #66c2a5;
--layer-l4: #a6d96a;
--layer-l5: #fee08b;
--layer-l6: #fdae61;
--layer-wm: #d53e4f;   /* white matter  */

/* Derived UI roles */
--ink:        #0f1015;  /* near-black, slight violet cast to sit with L1 */
--ink-muted:  #6b6b78;
--paper:      #fbfbfd;
--hair:       rgba(15, 16, 21, 0.09);
--accent:     var(--layer-l1);   /* primary — violet, not black */
--signal:     var(--layer-wm);   /* the tear / failure state */
--focus:      var(--layer-l2);   /* replaces the YC orange */
```

Two roles carry meaning and should be used only for that: `--signal` marks the
tear and the negative results; `--accent` marks Sutura's own measurements. That
consistency does more for perceived rigor than any amount of polish.

**Ship the dark theme.** A spectral point cloud on near-black is dramatically more
legible than on white, and instrument software in this field is dark by
convention. Recommend dark as the default with a light variant, or dark hero
against light content sections.

### 3.2 Typography

Replace the single-font Jost setup with a three-role system:

| Role | Recommendation | Use |
|---|---|---|
| Display | A grotesk with real character — Söhne, Untitled Sans, or GT America. Free fallback: **Inter Tight** or **Instrument Sans**. | Headline, section heads |
| Text | Same family, regular weight | Body copy |
| Mono | **JetBrains Mono** or **IBM Plex Mono** | All numerals, benchmark tables, axis labels, dataset IDs |

The mono role is the important one. Setting every measurement in mono — `99 px`,
`658 px`, `151507` — makes the page read as instrumentation rather than
marketing, and gives tabular figures that align in columns. This one change
carries more identity than the choice of display face.

Scale (dark hero):

```
display   clamp(2.75rem, 6vw, 4.5rem)   weight 400   tracking -0.02em   leading 1.05
subhead   clamp(1.05rem, 2vw, 1.35rem)  weight 300   tracking  0        leading 1.5
section   1.75rem                        weight 400   tracking -0.01em
body      1.0625rem                      weight 300   leading 1.65      max-width 62ch
mono/data 0.9375rem                      weight 400   tabular-nums
label     0.75rem                        weight 500   tracking  0.08em  uppercase
```

### 3.3 Motion

Current motion is a generic 4-step fade-and-rise stagger (`globals.css:99-128`).
Replace with two motions that mean something:

1. **Registration reveal (hero, once on load).** Section B's spots enter offset
   from section A's, then settle into alignment over ~1.2s with a slight
   overshoot. The page literally performs the product. Runs once, never loops.
2. **Idle rotation (hero, continuous).** The stack rotates ~2°/s about Y. Slow
   enough to read as ambient, fast enough to convey volume.

Everything else: opacity only, 200ms, no translation. Honour
`prefers-reduced-motion` by rendering the settled state immediately and freezing
rotation — the existing block at `globals.css:277-291` is a good model, extend it
to cover the new motions.

---

## 4. Page structure

Seven sections. Copy below is a first draft, not final.

### 4.1 Hero — the tension, plus real tissue

Full-viewport, dark. The 3D stack occupies the right ~55% on desktop, sits behind
the text at low opacity on mobile.

> **Optimal transport can't represent a tear.**
> Sutura is a learned registrar for spatial transcriptomics — graph encoder,
> cross-attention, deformation head — built for the discontinuities that break
> smooth alignment methods.
>
> `[Read the benchmark]`  `[Sign in]`

Beneath, a thin mono strip captioning what is actually on screen:

```
DLPFC Br5292 · 4 adjacent sections · 151507–151510 · 12,000 spots · spatialLIBD
```

That caption does real work: it tells the visitor the visual is measured data
rather than a decorative render.

### 4.2 The problem — why tears break existing methods

Three short columns, each naming a method class and its failure mode. This is
straight from `COMPETITIVE_BENCHMARK.md` §4 and is unusually well-evidenced:

- **Optimal transport (PASTE2)** — diffuse-plan smearing. 659 → 838 px.
- **Diffeomorphic (STalign)** — smooth overshoot; a diffeomorphism cannot change
  topology. 79 → 866 px, an 11× degradation.
- **Both converge to ~850 px at a severe tear.** Two different mechanisms, one
  shared wall.

This section is more persuasive than any claim about Sutura, because it
establishes that the problem is real before proposing a solution.

### 4.3 The approach

Short prose plus a small diagram: graph encoder → cross-attention → deformation
head. `research/figures/fig_architecture.png` exists; redraw as inline SVG so it
scales and can be themed, rather than shipping the PNG.

### 4.4 The benchmark

The severity curve, not a leaderboard. X axis severity 0→8, Y axis median error
(px), three lines: Sutura, PASTE2, STalign. Horizontal reference line at 137 px
labelled **spot pitch** — the line that matters, since sub-pitch is the
meaningful threshold.

The curve tells the whole story in one read: STalign starts below Sutura and
climbs 11×; PASTE2 starts high and stays high; Sutura stays flat and sub-pitch.
A table cannot show that shape.

Directly under the chart, in the same type size as the chart title, not smaller:

> These are in-distribution, supervised results — trained and evaluated on the
> same tissue pair with held-out warp seeds. Out of distribution, the picture is
> different. ↓

### 4.5 What doesn't work yet — the differentiator

Give this section the same visual weight as §4.4. Do not tuck it away.

> **Cross-donor generalization is unsolved.**
>
> Trained on two donors and tested on a held-out third, across all three folds,
> Sutura stays excellent on its training donors (82–148 px) and lands 1,080–1,557
> px out of sample — losing to PASTE2 (407–838 px) on every unseen donor. Adding a
> second training donor did not buy donor-invariance. Per-slice batch correction
> recovered 10–15% and did not close the gap.
>
> Diagnosed mechanism: multi-donor training fixed attention collapse — the encoder
> is discriminative now — but the learned correspondences are confident and wrong
> on unseen tissue. The gap is in cross-donor correspondence alignment, not the
> deformation head.
>
> Current direction: a donor-invariant InfoNCE correspondence loss. On held-out
> fold S1 it roughly halves the gap (1,327 → 834 px at sev0) and nearly ties
> PASTE2 at high severity. It does not beat it yet. The full 3-fold × {readout, λ}
> matrix is still running.

Three-fold LOO table rendered in mono, `--signal` on the losing cells.

No landing-page generator produces this section. It is the single least
copyable thing the company could put on the web, and for a research audience it
buys more trust than the benchmark above it.

### 4.6 Try it

Route to the existing demo. Screenshot or short loop of the results view, with
the dataset list (DLPFC real; breast/kidney marked synthetic, as
`demoDatasets.ts:5-6` already notes).

### 4.7 Footer

Team, domain email addresses, privacy policy, `security.txt` (already at
`public/.well-known/security.txt`), and a link to the research README.

---

## 5. Implementation notes

### 5.1 Hero visual

Do not import `TissueStack3D` directly — it carries `OrbitControls`, dataset
switching, and interaction state the hero doesn't need. Extract a
`HeroTissueStack` sharing the point-shader material (`TissueStack3D.tsx:19-45`)
with controls removed and a fixed camera.

Payload: `br5292_stack.json` is 226 KB for 12,000 points. For a hero above the
fold, subsample to ~4,000 points (~75 KB) into a dedicated
`public/hero_stack.json`. Visually near-identical at hero scale.

Loading: `next/dynamic` with `ssr: false`, plus a static SVG or CSS point-field
poster so the hero paints immediately and has a sane no-WebGL fallback. Do not
let LCP wait on Three.js. Budget: hero interactive < 2.5s on a mid-range laptop;
if the WebGL path can't hit that, ship the static poster as the default and
promote to 3D only on `matchMedia('(min-width: 1024px)')`.

### 5.2 The benchmark chart

Inline SVG, hand-authored. No charting library — the data is three fixed series
of five points and does not justify a dependency. Renders instantly, themes with
CSS variables, and stays sharp.

Source data: `research/results/stalign_tear.csv`,
`sutura_multiseed_tear.csv`, `sweep_deformation_ms_tear_seed0.csv`. Extract to a
small typed constant in `src/lib/benchmark.ts` with the source path in a comment,
so published numbers are traceable to a file.

### 5.3 CSS

The `.landing` block (`globals.css:106-291`) is single-purpose and should be
deleted, not extended — it encodes another site's layout assumptions
(`min-height: 100vh` centering, `letter-spacing: normal` reset at
`globals.css:117`). New sections should be Tailwind + a small token layer, with
the design tokens from §3.1 replacing the `--cb-*` variables.

Retain from the current implementation: the `prefers-reduced-motion` block's
approach, `focus-visible` outlines (recolour to `--focus`), and the existing
`@theme inline` token bridge (`globals.css:36-70`), which is sound.

### 5.4 Metadata

Add `openGraph` and `twitter` to `layout.tsx`, and a real OG image — a frame of
the tissue stack with the headline set over it. Also worth adding: a JSON-LD
`Organization` block.

### 5.5 Accessibility

- Contrast: the layer ramp includes light values (`#fee08b`, `#a6d96a`) that fail
  against white. On dark they are fine. Any layer colour used for text or on
  light backgrounds needs a darkened variant.
- The benchmark chart needs a text alternative — the underlying table, visually
  hidden or in a `<details>`.
- The hero canvas is decorative: `aria-hidden="true"`, with the caption strip
  carrying the real information.
- Keep every section reachable and readable with JS disabled except the canvas.

---

## 6. Sequencing

| # | Change | Effort | Impact |
|---|---|---|---|
| 1 | Remove the GPSA row; fix the STalign row (§2.1–2.2) | XS | Correctness — do this regardless |
| 2 | Kill the YC orange; canonicalize headline numbers | XS | Correctness |
| 3 | Static headline replacing the typewriter | S | High |
| 4 | Hero tissue stack | M | Highest |
| 5 | Benchmark severity chart | M | High |
| 6 | "What doesn't work yet" section | S | High — most differentiating per unit effort |
| 7 | Palette + type system, dark theme | M | Medium-high |
| 8 | Problem / approach / try-it sections | M | Medium |
| 9 | OG metadata, domain email | XS | Medium |

Items 1–3 and 6 are together about a day and capture most of the gain. Items 4–5
are where the visual identity actually lands.

---

## 7. Open questions

1. **Dark or light default?** Recommend dark; it suits the point cloud and the
   instrument-software convention, but it is a brand call.
2. **Display typeface budget?** Free (Inter Tight / Instrument Sans) is a clear
   improvement on Jost. A licensed grotesk is a further step; needs a decision on
   spend.
3. **How prominent should §4.5 be?** Recommended as a peer of the benchmark
   section. There is a real argument it belongs on a linked research page instead
   — it depends whether the primary audience is investors or lab buyers. For labs,
   prominent is right.
4. **Canonical headline pair?** §2.3 — pick 99/658 or 109/732 and use it
   everywhere.
5. **Is the demo's synthetic breast/kidney data linkable from a public page?**
   It is labelled synthetic in-product, but public-facing use needs the label to
   be unmissable.
