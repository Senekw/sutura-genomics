# workflow-agent - Coordination Log

Standalone prototype: **workflow-recommend**. Takes a natural-language description of a
spatial / single-cell experiment and returns a concrete, honest, actionable pipeline
recommendation grounded in real, existing tools.

Branch: `workflow-agent`. Scope: only files under `workflow/`. Never touches main,
website, demo, cli/, app/, src/, or other branches.

## Design goals
- **Honest.** Never claim to "solve" segmentation or batch effects. Recommend and
  orchestrate existing tools; flag unsolved/expert-judgment steps explicitly.
- **Grounded.** Every tool is real, with a real install command and honest maturity /
  failure-mode notes. No invented packages.
- **Actionable.** Ordered steps, specific tool per step, why, runnable commands/code,
  expected runtime, known limitations.
- **Multi-platform / multi-experiment.** Visium, Visium HD, Xenium, MERSCOPE, CosMx,
  Stereo-seq x 3D organ mapping, tumor architecture, developmental time series,
  disease-vs-control, atlas building.

## Log

### 2026-07-18
- Created branch `workflow-agent`, scaffolded `workflow/`.
- Built knowledge base as structured JSON (tools, steps, platforms, experiment types).
  - `platforms.json`: Visium, Visium HD, Xenium, MERSCOPE, CosMx, Stereo-seq (+ the
    properties that drive step selection: spot vs single-cell, needs seg, needs deconv).
  - `steps.json`: 12 canonical ordered steps, with `expert_judgment` / `unsolved` flags.
  - `tools.json`: 40+ real packages with install command, code snippet, maturity rating,
    runtime estimate, and honest failure-mode notes. Includes `sutura_align` described
    honestly (routes to best method + gated refinement; research-stage; no overclaim).
  - `experiment_types.json`: 3D organ mapping, tumor architecture, developmental time
    series, disease-vs-control, atlas building, single-section survey, general.
- Built the engine (zero third-party deps, stdlib only):
  - `parser.py` - deterministic keyword/regex NL -> ExperimentSpec (flags unknowns).
  - `recommender.py` - step inclusion + tool selection with honest per-step warnings.
  - `render.py` - markdown / plain-text reports; `cli.py` - `workflow-recommend` CLI.
  - `pyproject.toml` (installable, entry point) + `workflow-recommend` no-install launcher.
- Wrote 59 tests (parser, recommender logic, KB integrity, render, CLI) - all green.
- Generated 6 worked examples (one per experiment type) via `examples/generate.py`.
- Wrote `README.md` with design rationale + honesty section.

Key honesty guarantees enforced by code + tests:
  - Segmentation & batch correction are flagged `unsolved` / `expert_judgment`, never
    "solved"; each carries its real failure modes.
  - Spot platforms (Visium) -> deconvolution, never per-cell typing/segmentation.
  - Imaging platforms -> segmentation + per-cell typing, never deconvolution.
  - Disease-vs-control -> pseudobulk DE (PyDESeq2) with pseudo-replication + "don't
    correct away the effect" warnings.
  - Deconvolution warns when no matched single-cell reference is available.
  - `sutura_align` surfaced only as an OPTIONAL refinement on PASTE2, described honestly.

Fixes during build:
  - Platform-native tools (Stereopy, bin2cell) now win their own platform's steps.
  - Batch correction suppressed when we positively know it is a single section.

STATUS: prototype complete. Run: `python workflow/workflow-recommend "<description>"`;
tests: `cd workflow && python -m pytest`.

Deliverables (all under `workflow/`):
  - Working prototype: CLI `workflow-recommend` + documented Python API.
  - Knowledge base as structured data: `workflow_recommend/kb/*.json`.
  - README with design rationale + examples.
  - Tests: `tests/` (59 passing).
  - Worked examples: `examples/` (6 experiment types).

Caveat: KB reviewed 2026-07 against real, current tools; versions/APIs move, so the
report tells users to confirm before running. Not exhaustive - easy to extend by adding
JSON objects to `tools.json` (integrity tests guard consistency).
