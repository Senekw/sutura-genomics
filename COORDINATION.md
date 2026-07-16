# Sutura overnight build — coordination log (for Codex)

**Owner:** Claude (autonomous overnight session, started 2026-07-16)
**Branches:** `sutura-cli` (items 1-7, 9), `sutura-app` (item 8). **Do NOT touch `main` or `demo/` (web demo).**
**Goal:** take the `sutura` CLI from working skeleton → robust, demoable, tested product + build the v1 viewer app that reads its bundles. Alignment only; keep architecture extensible but build nothing speculative.

## Environment facts (verified)
- Engine: existing repo at `C:\Users\karti\arca` — `backend/pipeline.py::run_alignment`, `src/orchestrator.py`, `src/agents.py`, checkpoints in `results/`. CLI wraps these; no alignment logic reimplemented.
- Interpreter: `C:\Users\karti\arca\.venv\Scripts\python.exe` (Python 3.12.9; scanpy 1.11.5, anndata 0.12.17, torch 2.12.1+cpu, POT 0.9.6, paste2 installed).
- CLI package: `cli/` (installed editable, entry point `sutura`). rich/textual/anthropic pip-installed into `.venv`.
- Ollama: **already installed & running** (v0.32.0) at http://localhost:11434. Models on disk: `gemma3:1b`, `gemma3:4b`. Pulling `llama3.2:3b` now (bg).
- DLPFC data: `data/DLPFC_<id>.h5ad` (12 files). Donors: Br5292=151507/08/09/10 (in-dist), Br5595=151669-72 (in-dist), Br8100=151673-76 (off-dist/held-out). Breast/mouse external in `data/external/`.
- Company logo: `~/Downloads/minimalist-company-logo-icon-no-text-bla_AUCegC6uWA2hWy6Pg8V-2w_Kc1WARN1T_6xXOHz8zeLFQ.jpg` (DNA-helix suture mark, lavender-on-black). For the app.

## Item status
| # | Item | Status |
|---|------|--------|
| 1 | Local LLM backend (no key) | DONE (commit pending) |
| 2 | Off-distribution path, honest | DONE (commit pending) |
| 3 | Robust loaders + error handling | DONE (commit pending) |
| 4 | Multi-section (>2) reconstruction | pending |
| 5 | Polished streaming UX | pending |
| 6 | Comprehensive tests | pending |
| 7 | Documentation | pending |
| 8 | Viewer app v1 (sutura-app) | pending |
| 9 | End-to-end integration test | pending |

## Baseline (from prior session, commit ca460a5)
Full CLI skeleton committed: TUI (Textual), agent loop, 6 tools wrapping the engine, bundle writer (schema v1.0), rule/cloud/ollama backends, e2e test on DLPFC pair (in-dist → Sutura, 1.29 spot-pitch, valid bundle). All prior tests pass.

## Decisions & findings (chronological)
- **[item 1] Ollama planner reliability:** tested gemma3:4b vs gemma3:1b on the core intents. gemma3:4b plans all core intents correctly (~10-20s/call CPU). gemma3:1b hallucinates out-of-vocabulary tool names (`redo_section`), garbles methods (`PASE2`), invents args (`format:pdf`). → Hardened the JSON backends: closed action vocabulary + alias/method normalization + validate-and-fall-back-to-rule when the model goes off-script or under-acts (`_finalize` in `cli/sutura_cli/core/llm.py`). Ollama now uses temperature 0, auto-selects an installed model, and any server/parse failure falls back to rules. Pulling llama3.2:3b to use as the recommended small model.

### Item 1 — DONE
- Pulled **llama3.2:3b** (fast: 3-5s/plan on CPU) — the recommended local model. gemma3:4b (accurate, ~15s) and gemma3:1b (tiny) also verified.
- All 3 models score **7/7 on core action intents** after: closed-vocabulary validation + method/tool-alias normalization + few-shot examples + `_finalize` adjudication (rule planner wins any action-TYPE disagreement; model handles phrasings rules can't; server/parse failures fall back to rules). Ollama uses temperature 0 and auto-selects an installed model.
- **New read-only query tools** (answer from the bundle, no re-run): `metrics`, `worst`, `explain_routing` — covers the "show metrics / which aligned worst / explain routing" intents. Handlers in `agent.py`; rule patterns + LLM vocabulary in `llm.py`.
- Softened the rule fallback: an unrecognized remark no longer silently triggers a full re-alignment (returns a clarifying Reply); only explicit "go ahead" runs the workflow when sections are loaded.
- **Real sessions logged** to `cli/docs/example_sessions.md`: Session A (full workflow + 4 queries, llama3.2:3b, executed on DLPFC), Session B (align → force PASTE2 4.79 → switch back to Sutura 1.29, honest labels), Session C (12-phrasing planner gallery, 12/12 correct). All planning via the local model; metadata-only.
- Tests: +11 unit tests (query intents, alias/method normalization, off-vocab & type-conflict fallback). 19 fast tests pass.
- Files: `cli/sutura_cli/core/llm.py`, `cli/sutura_cli/core/agent.py`, `cli/tests/test_units.py`, `cli/docs/example_sessions.md`.

### Item 2 — DONE
- Ran the full flow on TWO off-distribution datasets, both routed correctly and honestly, no crashes:
  - **Br8100** (DLPFC 151673/674, same panel, maha 4.77): off-dist → auto-adapt ran (Sutura zero-shot 9.53 → adapted 8.03), **PASTE2 kept (2.82 spot-pitch)**.
  - **Breast** (V1 Block A s1/s2, maha 20.4, 95% overlap): off-dist → auto-adapt ran (Sutura zero-shot 26.9 → adapted 7.77), **PASTE2 kept (3.47 spot-pitch)**. GT available for both (array-bridge).
- Auto-adapt path exercised & honestly labelled on both: bundle `candidates` field records every method's score + `auto_adapt_epochs`, `reason` says "auto-adapt ran; kept the best of [...]", report shows a **Methods-compared breakdown** with the kept method marked. Honest story confirmed: auto-adapt helps a lot off-distribution but PASTE2 still wins → matches our claim.
- **Fixed a labelling bug:** the routing preview used to say flatly "PASTE2" for off-dist; now says "off-distribution: auto-adapt Sutura vs PASTE2, keep best" (or "PASTE2 (gene panel too different to adapt the model)" when overlap < 50%). Honest in streamed output, routing.json, and report.
- Note: breast shares 95% of the basis genes, so the "panel too different → PASTE2 direct, no adapt" branch isn't hit by breast; it would need a targeted/Xenium panel (<50% overlap). Logic is in place and unit-covered; not exercised on real data tonight.
- Files: `cli/sutura_cli/core/tools.py` (honest routing preview), `cli/sutura_cli/core/reporting.py` (candidate breakdown), `cli/tests/test_units.py` (+2). 20 fast tests pass.

### Item 3 — DONE
Hardened `tools.py` + `agent.py` so every realistic failure mode yields a helpful message (new `LoaderError`/`AlignError`), never a stack trace:
- **Missing path** → "Path not found: ... Give a folder of .h5ad / a .h5ad / a Space Ranger dir." **Empty/again dir** → "No sections found ... looks for .h5ad / Space Ranger / Xenium."
- **Wrong obsm keys** → `_ensure_spatial` recovers coords from obsm aliases (X_spatial, spatial_coords, xy, ...) or obs column pairs (x/y, imagecol/imagerow, pxl_*_in_fullres, array_col/row, x_centroid/y_centroid) with an info note; if truly absent → actionable error listing available obsm keys.
- **Empty section** (0 cells/genes) → clear error, other sections still load.
- **Mismatched panels** → align preflight raises if the pair shares 0 genes ("share 0 genes ... same gene identifiers").
- **Single-section input** → clean AgentMessage ("needs at least 2 adjacent sections"), no crash, no bundle created.
- **Non-adjacent sections** → post-QC emits an adjacency warning when footprint coverage < 0.4 (recorded in bundle as `adjacency_warning`).
- **Per-pair resilience:** a failing pair is caught, logged to bundle.warnings, and the job continues; if all pairs fail the bundle is written with status="failed" (honest record).
- **Space Ranger:** validates spatial/ subfolder + readable matrix with targeted messages.
- **Xenium:** detected and rejected with an actionable message (convert to .h5ad) — see blocker below.
- Tests: new `cli/tests/test_loaders.py` (12 tests: spatial recovery, missing/empty path, empty h5ad, zero-gene guard, single-section). 32 fast tests pass.

## Open blockers
- **Xenium (unchanged):** no Xenium data on disk; squidpy 1.6.6 has no `xenium` reader. Implemented as detect + actionable error (convert Xenium → .h5ad, point Sutura at it) per the "clear message" option. Real Xenium ingest deferred until a sample + reader are available.

## Recommendations for next / for Codex
- TBD (updated at end).
