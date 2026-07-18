# workflow-recommend

**Describe your spatial / single-cell experiment in plain English; get back a concrete,
honest, actionable analysis pipeline** — the ordered steps, a specific real tool for each,
why that tool, the actual commands to run it, expected runtime, and the known limitations.

```bash
python workflow/workflow-recommend \
  "3D organ mapping of human kidney, 10x Visium, 12 serial sections, want cell types and spatial domains"
```

This is a standalone prototype, built because labs told us their real pain is the
**downstream** work — segmentation, batch effects, annotation, alignment, and the
manual glue between them — not any single alignment method. So instead of selling one
step, this recommends and orchestrates the *existing* tools for the whole pipeline, and
is honest about where those tools break.

---

## Why this exists (design rationale)

A researcher who has just generated Xenium or Visium data faces a sprawl of dozens of
packages across Python and R, each solving one step, each with its own failure modes,
and no map from "here is my experiment" to "here is the pipeline." The expensive,
error-prone part is choosing and sequencing those tools correctly for *their* platform
and *their* design. That is what this tool automates.

Three commitments shape every design decision:

1. **Honesty over salesmanship.** We never claim to "solve" segmentation or batch
   correction. Those steps are flagged as unsolved / expert-judgment, with their real
   failure modes stated. Where our own alignment method is recommended, it is described
   for exactly what it is (routes to the best existing method; offers a gated refinement)
   — not more.
2. **Grounding over invention.** Every recommended tool is a real, installable package
   with an honest maturity rating and known-limitation note. The knowledge base is plain
   JSON you can audit line by line. Nothing is fabricated.
3. **Actionability over abstraction.** The output is a runnable scaffold: install
   commands, code snippets, runtime expectations, and the specific warning you need to
   see *before* you run each step.

### What it is NOT

- Not an autopilot. It produces a recommended scaffold; you still run the tools and
  exercise expert judgment at every flagged step.
- Not a claim that any step is solved. Segmentation, integration, alignment, annotation,
  and deconvolution all carry explicit failure-mode warnings.
- Not a wrapper that hides the real tools. It points you *at* them, with their real APIs.

---

## Install / run

The **core engine has zero third-party dependencies** (Python 3.9+, stdlib only), so it
runs anywhere without an environment. The *recommended* tools are installed by you, per
the generated pipeline — not by this package.

Run without installing:

```bash
python workflow/workflow-recommend "Xenium breast tumor, cell types and niches"
```

Or install the CLI:

```bash
pip install ./workflow          # provides the `workflow-recommend` command
workflow-recommend "Visium HD lung, disease vs control, 5 donors, differential expression"
```

Run the tests:

```bash
cd workflow && python -m pytest
```

---

## CLI usage

```
workflow-recommend [DESCRIPTION] [options]

  DESCRIPTION            experiment description in natural language ('-' reads stdin)
  -f, --format FMT       markdown (default) | text | json
      --spec-only        print only what the tool parsed from your description
      --list-tools       list knowledge-base tools by step
      --list-platforms   list supported platforms
  -o, --output FILE      write the report to a file
```

Examples:

```bash
# full markdown report
workflow-recommend "Xenium human breast tumor, single section, cell types and niches"

# plain text (ASCII, any console)
workflow-recommend -f text "MERSCOPE developmental series, 4 timepoints"

# machine-readable
workflow-recommend -f json "CosMx lung atlas, 20 donors" | jq .steps

# see how it parsed your description before trusting the pipeline
workflow-recommend --spec-only "Visium kidney, 12 serial sections"

# from stdin
echo "Stereo-seq whole embryo, cell types and domains" | workflow-recommend -
```

---

## Python API

```python
from workflow_recommend import recommend, render, parse_experiment, build_pipeline

# one-shot: description -> Pipeline
pipe = recommend("3D organ mapping of human kidney, 10x Visium, 12 serial sections, "
                 "want cell types and spatial domains")
print(render(pipe))                 # markdown
print(render(pipe, fmt="text"))     # plain text

# inspect the parse and the structured pipeline
spec = parse_experiment("Xenium lung, disease vs control, 6 donors")
print(spec.to_dict())               # what was understood
pipe = build_pipeline(spec)
for step in pipe.steps:
    tool = step.primary.name if step.primary else None
    print(step.order, step.name, "->", tool,
          "[expert]" if step.expert_judgment else "")
    for w in step.warnings:
        print("   !", w)
```

Key objects:

- `ExperimentSpec` — the parsed description (platform, experiment type, section/sample
  counts, goals, reference availability, and parse `notes`). Deterministic keyword
  parsing; it says when it is unsure rather than guessing silently.
- `Pipeline` / `PipelineStep` / `ToolChoice` — the recommended, ordered steps with the
  primary tool, alternatives, optional refinements, and per-step warnings.

---

## How the recommendation works

```
description ──parse──> ExperimentSpec ──build_pipeline──> Pipeline ──render──> report
              (keyword,               (step inclusion +               (markdown /
               transparent)            tool selection, honest)         text / json)
```

1. **Parse** (`parser.py`): deterministic keyword/regex extraction of platform,
   experiment design, number of serial sections and samples, analysis goals, tissue,
   and whether a single-cell reference is available. Unknowns are flagged, not invented.
2. **Decide steps** (`recommender.py`): from platform + design + goals, choose which of
   the canonical steps this experiment actually needs. Examples of the rules:
   - Spot platforms (Visium) → **deconvolution**, never cell segmentation or per-cell
     typing (spots are multi-cellular).
   - Imaging platforms (Xenium/MERSCOPE/CosMx) → **segmentation + per-cell typing**,
     never deconvolution.
   - Serial sections → **alignment / 3D reconstruction**.
   - >1 section/sample or a multi-sample design → **batch integration** (suppressed when
     we positively know it is a single section).
   - Disease-vs-control → **pseudobulk DE** (PyDESeq2) promoted over per-spot DE, with a
     pseudo-replication warning.
3. **Select tools**: for each step, rank the knowledge-base tools compatible with the
   platform by maturity/priority (with a boost for platform-native tools like Stereopy
   and bin2cell), pick a primary plus alternatives, and attach honest per-step warnings.
4. **Render**: emit a report with a spec summary, an at-a-glance step list, the steps to
   "read first," and the full per-step detail.

---

## The knowledge base

Plain JSON under [`workflow_recommend/kb/`](workflow_recommend/kb/), designed to be
audited and extended without touching code:

- **`tools.json`** — real packages mapped to pipeline steps, each with install command,
  a runnable code snippet, honest maturity rating (`mature` > `established` > `emerging`
  > `research`), runtime estimate, and known failure modes. Covers QC, segmentation,
  normalization, batch correction, alignment/3D, cell typing, deconvolution, spatial
  domains, spatial DE, cell-cell communication, and visualization.
- **`platforms.json`** — Visium, Visium HD, Xenium, MERSCOPE, CosMx, Stereo-seq, and the
  properties that drive step selection (spot vs single-cell, needs segmentation, needs
  deconvolution).
- **`steps.json`** — the canonical ordered pipeline steps and, crucially, which are
  `expert_judgment` / `unsolved`.
- **`experiment_types.json`** — templates (3D organ mapping, tumor architecture,
  developmental time series, disease-vs-control, atlas building) that seed the goals a
  design usually implies.

To add a tool: add one JSON object to `tools.json` with its `steps` and `platforms`.
Integrity tests (`tests/test_knowledge_base.py`) will confirm it references only valid
steps/platforms, has all required fields, and stays ASCII-clean.

### Tools covered (real packages)

QC/backbone: Scanpy, Squidpy, SpatialData/spatialdata-io, Sopa, Stereopy ·
Segmentation: Cellpose, StarDist, Baysor, ProSeg, bin2cell, DeepCell/Mesmer ·
Batch/integration: Harmony, scVI/scANVI, Scanorama, Seurat ·
Alignment/3D: PASTE/PASTE2, STalign, GPSA, moscot, Tangram, **Sutura Align (ours)** ·
Cell typing: CellTypist, Tangram, Azimuth, popV, scANVI ·
Deconvolution: cell2location, RCTD, DestVI, SPOTlight ·
Spatial domains: SpaGCN, BayesSpace, STAGATE, GraphST, BANKSY ·
Spatial DE / DE: SpatialDE, SPARK-X, Hotspot, PyDESeq2 (pseudobulk) ·
Communication: LIANA+, CellPhoneDB, COMMOT ·
Visualization: napari, Vitessce, TissUUmaps.

---

## Where our own alignment fits (stated honestly)

For serial-section alignment the primary recommendation is **PASTE2** (the established
optimal-transport method). **Sutura Align** appears as an *optional refinement*, and the
report says plainly what it does:

> It does not replace the aligner. It (1) routes each section pair to the best-performing
> existing aligner for that data regime, and (2) applies a fit-residual-**gated**
> refinement on top of the base alignment. The gate means it only refines when the base
> fit is trustworthy and otherwise returns the base mapping unchanged, to avoid making
> things worse. It measurably lowers alignment error in our internal benchmarks but is
> research-stage and does not fix tissue distortion, tears, or folds.

No claim that alignment is solved; the honest limitation is front and center.

---

## Repository layout

```
workflow/
├── README.md                    # this file
├── COORDINATION.md              # build log
├── pyproject.toml               # installable; entry point `workflow-recommend`
├── workflow-recommend           # no-install launcher script
├── workflow_recommend/          # the package (zero runtime deps)
│   ├── kb/                       # the knowledge base (JSON)
│   ├── knowledge_base.py         # KB loader + ranking
│   ├── parser.py                 # NL -> ExperimentSpec
│   ├── spec.py                   # ExperimentSpec data model
│   ├── recommender.py            # step inclusion + tool selection
│   ├── pipeline.py               # Pipeline / PipelineStep / ToolChoice
│   ├── render.py                 # markdown / text reports
│   └── cli.py                    # the CLI
├── examples/                     # 6 worked examples + generate.py
└── tests/                        # pytest suite (parser, recommender, KB, render, CLI)
```

## Honesty, in one paragraph

Segmentation and batch correction are not solved problems, and this tool never pretends
otherwise. It orchestrates real, existing tools, tells you which step you are trusting at
each point, and flags every place that needs your eyes and judgment. Treat its output as
a well-informed starting scaffold — validate each step against your biology, confirm tool
versions before running, and inspect results visually.
