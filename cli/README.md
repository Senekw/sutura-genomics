# Sutura CLI (`sutura`)

**Agentic, local-first spatial-transcriptomics alignment — "Claude Code for
spatial data."** You tell `sutura` in natural language what to do with your local
Space Ranger / Xenium / AnnData files; it runs the full alignment and 3D
reconstruction workflow live in a polished full-screen terminal, entirely on your
machine, and writes a structured **result bundle** that the Sutura viewer app
opens.

![Sutura TUI](docs/tui_screenshot.svg)

- **Local-first, no data egress.** Nothing is uploaded. The agent's LLM only ever
  sees *metadata* (section names, spot/gene counts, formats) — never raw
  expression. This is what makes it usable on clinical / PHI samples that can't
  leave the institution.
- **Workflow-native.** It reads real primary-processing output and drives the
  existing Sutura orchestrator: QC → distribution check → routing → alignment →
  post-QC → reporting.
- **Honest by construction.** Every result is labelled with the method that
  produced it and why. Sutura's graph model wins in-distribution; PASTE2 is used
  off-distribution. This automates *best-available* alignment — it does not claim
  to beat every method on every tissue.

This is product #1 (the engine). Product #2, the viewer app, only *reads* the
bundles this CLI writes — it never runs reconstruction. Bundle contract:
[`docs/BUNDLE_SCHEMA.md`](docs/BUNDLE_SCHEMA.md).

## Install

`sutura` wraps the existing alignment engine in this repository (the research
code under `src/`, the trained checkpoint `results/arca_shared_basis.pt`, and the
frozen shared basis). Install it into the same environment as that engine:

```bash
# from the repository root, using the project venv (Python 3.12)
.venv/Scripts/python.exe -m pip install -e cli
# CLI deps only (rich, textual, numpy, anndata). The heavy engine deps
# (scanpy, torch, POT, paste2) already come from the repo environment.
```

This installs the `sutura` entry point. The engine repo is auto-detected from the
install location; override it any time with `SUTURA_REPO=/path/to/repo`.

## Usage

```bash
sutura                                   # launch the full-screen TUI
sutura -H "align ./data and reconstruct in 3D"   # headless (streams to stdout)
```

Inside the TUI, type instructions at the prompt:

```
align the sections in ./my_data and reconstruct in 3D
redo section 2 with PASTE2
```

### LLM backend (the agent's planner)

The planner turns your words into tool calls. It only sees metadata. Pick a
backend with `--backend` or `$SUTURA_BACKEND`:

| backend  | when                                   | needs                          |
|----------|----------------------------------------|--------------------------------|
| `rule`   | offline, deterministic (default fallback) | nothing                     |
| `cloud`  | Anthropic API                          | `ANTHROPIC_API_KEY` in env     |
| `ollama` | local model, best for PHI              | a running Ollama server        |
| `auto`   | cloud → ollama → rule, first available | (default)                      |

Other env vars: `SUTURA_HOME` (result store, default `~/.sutura`),
`SUTURA_CLOUD_MODEL`, `SUTURA_OLLAMA_MODEL`, `OLLAMA_HOST`.

## Demo transcript

Running the loop headless on the DLPFC demo pair (`151507`/`151508`, an
in-distribution donor):

```text
$ sutura -H "align the sections in ./demo_data and reconstruct in 3D" --backend rule
Sutura v0.1.0 - backend: rule - store: ~/.sutura

Planning: load sections -> QC -> routing -> align each pair -> post-QC -> 3D
reconstruct -> report. Everything runs locally; the model only sees metadata.

> Load data - scanning ./demo_data
v 2 section(s): DLPFC_151507 (4226 spots), DLPFC_151508 (4384 spots)
> Quality control - validating inputs
v 2/2 passed
> Distribution check - DLPFC_151507 vs DLPFC_151508
  route -> Sutura (graph model) (in-distribution; Mahalanobis 0.85 < threshold 2.5)
v route -> Sutura (graph model) (Mahalanobis 0.85, gene overlap 100%)
> Align - DLPFC_151507 -> DLPFC_151508 (auto-routed orchestrator)
  ... aligning with Sutura graph model (45%)
v Sutura - 1.29 spot-pitch median error (measured error)
> Post-alignment QC - DLPFC_151507 -> DLPFC_151508
v pass: median error 1.29 spot-pitch
> 3D reconstruction - stacking aligned sections
v 2 sections, 8610 points
> Generate report - summarising results
v report.md (34 lines)
bundle written  ~/.sutura/results/job-20260716-003223-d96723

Results written to ~/.sutura/results/job-20260716-003223-d96723
Methods used: Sutura. Open in the Sutura app to view the 3D model.
You can also say e.g. "redo section 2 with PASTE2".
```

The follow-up `redo section 2 with PASTE2` re-runs that pair with the forced
method and rewrites the same bundle (`method_label` becomes `PASTE2`).

## Result bundle

Written to `~/.sutura/results/<job_id>/`:

```
metadata.json         manifest + index (written last => bundle is complete)
qc.json               per-section input QC
routing.json          per-pair distribution-check / routing decision
metrics.json          per-pair method used + metric/score (honest labels)
reconstruction.json   3D serial-section point cloud
report.md             human-readable summary
alignment/pair_00__<ref>__to__<mov>/aligned.h5ad
```

Full field-by-field contract: [`docs/BUNDLE_SCHEMA.md`](docs/BUNDLE_SCHEMA.md).

## Architecture

The CLI is a thin agent + UI layer over the *existing* engine — no alignment
logic is reimplemented.

```
sutura_cli/
  cli.py            entry point (TUI or --headless)
  render.py         console renderer for headless runs
  core/
    engine.py       locates the repo, lazily imports backend.pipeline / orchestrator / agents
    tools.py        the tools: load_data, qc, distribution_check, align, post_qc
    reporting.py    generate_report (honest, per-pair method labelling)
    reconstruct.py  serial-section z-stack -> 3D point cloud
    bundle.py       result-bundle writer (schema v1.0)
    llm.py          planner backends: rule / cloud / ollama
    agent.py        the agent loop (interpret -> tools -> bundle)
    context.py      WorkContext (raw AnnData stays here, local)
    events.py       typed event stream (UI-independent)
    config.py       store path + backend selection
  tui/app.py        Textual full-screen app (logo, live stream, status/mode bar, prompt)
```

`align` calls `backend.pipeline.run_alignment` (the full routed orchestrator);
forced-method reruns reuse `align_sutura` / `align_paste2`. Routing reuses
`orchestrator.distribution_check`; post-QC reuses the `agents` primitives.

## Tests

```bash
.venv/Scripts/python.exe -m pytest cli/tests -q
```

- `test_units.py` — planner intent parsing + reconstruction (no engine needed).
- `test_tui.py` — the Textual app composes and quits.
- `test_e2e.py` — the full loop on the DLPFC pair, asserting a valid bundle;
  auto-skips if the engine/data are absent. (~9 min: it runs real alignments.)
