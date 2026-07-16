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
| 4 | Multi-section (>2) reconstruction | DONE (commit pending) |
| 5 | Polished streaming UX | DONE (commit pending) |
| 6 | Comprehensive tests | DONE (commit pending) |
| 7 | Documentation | DONE (commit pending) |
| 8 | Viewer app v1 (sutura-app) | DONE (commit pending) |
| 9 | End-to-end integration test | DONE (commit pending) |

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

### Item 4 — DONE
- Rewrote `reconstruct.py` to compose a multi-section chain into ONE reference frame. Pairwise alignment puts section k+1 into section k's frame; we fit a **similarity transform (Umeyama: rotation + uniform scale + translation)** per pair from the moving section's original coords → its aligned coords, then chain those transforms back to the first section's frame. 2 sections (1 pair) stays exact.
- **Honest labelling:** reconstruction records `composition` = `exact_single_reference` (2 sections) or `pairwise_composition` (>2), with a note that it is NOT a global simultaneous solve (unlike GPSA), plus `global_frame`. Streamed step and report say so.
- **Gap handling:** if a pair was skipped (item-3 resilience), the chain composition breaks there; we reconstruct the contiguous run from the first pair and record `dropped_pairs` + a warning rather than mis-stacking.
- **Proven on a real 4-section DLPFC chain** (Br5292 151507-510): 4 sections / 3 pairs / 18033 points. All four section centroids cluster within ~180 px in the common frame (6634-6817 x, 4953-5058 y) — composition works. z = 0/137/274/411 (pitch spacing). Methods honestly mixed: Sutura (1.29) then PASTE2/PASTE2 (post-QC retries at 6.67/4.35, since DLPFC 3rd/4th slices are farther apart — real orchestrator behavior).
- Tests: composition unit test recovers a known chained similarity to atol 0.05; 2-section-exact asserted. 33 fast tests pass.
- Files: `cli/sutura_cli/core/reconstruct.py`, `cli/sutura_cli/core/agent.py`, `cli/tests/test_units.py`.

### Item 5 — DONE
- Rewrote `render.py` into a demo-grade console renderer: rounded **banner** ("● SUTURA GENOMICS", tagline, backend/store/no-egress), one clean line per step with ✓/⚠/✗ marks, **routing shown with method-and-why** (→ method, in/off-distribution, Mahalanobis, gene overlap), sparse progress ticks so long aligns feel alive, and a **"Run complete" card** (rounded panel + per-pair Method/Result/QC table, sections/pairs/points, bundle path, "▶ open in the Sutura app").
- **Windows fix:** forced UTF-8 + rich's modern renderer (`make_console`) so box-drawing and glyphs render in Windows Terminal instead of crashing the legacy cp1252 console.
- TUI polished to match: `›` step markers, ✓/⚠/✗, two-line routing, a **braille spinner** in the status bar while working (`▷ manual mode │ ⠹ working 45%`), and the shared completion card rendered in-stream. New `tui_screenshot.svg`.
- Refactored the completion card into `render.completion_panel()` shared by console + TUI. Enriched `bundle.summary()` with per-pair rows + reconstruction info. `agent._finalise` no longer dumps a verbose text block (the card replaces it).
- Verified end-to-end on real DLPFC data (banner → steps → routing → align → card). 33 fast tests pass.
- Files: `cli/sutura_cli/render.py`, `cli/sutura_cli/cli.py`, `cli/sutura_cli/tui/app.py`, `cli/sutura_cli/core/bundle.py`, `cli/sutura_cli/core/agent.py`, `cli/docs/tui_screenshot.svg`.

### Item 6 — DONE
Comprehensive suite, all green (real coverage, not token tests):
- **Fast (46 tests, no engine):** `test_units.py` (planner intents incl. new query tools, `_finalize` off-vocab + type-conflict fallback, method/alias normalization, reconstruction similarity-composition to atol 0.05, report candidate breakdown), `test_loaders.py` (18: spatial recovery from obsm aliases/obs pairs, missing/empty path, empty h5ad, zero-gene guard, Space Ranger detect + missing-spatial, Xenium actionable error, single-section message), `test_tui.py` (Textual composes/quits), `test_llm_ollama.py` (the **real local model** plans all 8 core intents + never emits out-of-vocabulary — skips if no Ollama).
- **Engine e2e (`test_e2e.py`, auto-skip if data absent):** in-dist full loop + valid bundle; forced-PASTE2 follow-up; **off-distribution** (Br8100: asserts off-dist routing, auto-adapt candidates recorded, honest PASTE2 label, streamed off-dist); **4-section chain** (asserts pairwise_composition, global_frame, z ordering, and that section centroids cluster < 1000px in one frame). Both slow engine tests pass (20m50s).
- Files: `cli/tests/test_llm_ollama.py` (new), `cli/tests/test_loaders.py`, `cli/tests/test_e2e.py`.

### Item 7 — DONE
- **README** rewritten: local-model-no-key emphasis (`ollama pull llama3.2:3b`), a full **natural-language command table** (align / redo / switch / metrics / worst / explain-routing / report / help), backend selection + env vars, a polished demo transcript (banner → steps → routing → completion card), robustness summary, and links to the schema/architecture/sessions docs.
- **`docs/ARCHITECTURE.md`** (new): the 4-layer design (LLM backends → agent loop → tools → engine), the metadata-only contract, the event/sink rendering split, and a **step-by-step "how to add a new tool"** guide (stays extensible without touching alignment code).
- **`docs/BUNDLE_SCHEMA.md`** updated: reconstruction `composition` (exact_single_reference | pairwise_composition) + `global_frame` + `dropped_pairs`, per-section `method`, off-distribution `candidates`/`reason` example, `post_qc.adjacency_warning`, and `status="failed"` semantics.
- **`docs/example_sessions.md`** (from item 1): real local-model sessions kept as the clean demo transcript.
- Files: `cli/README.md`, `cli/docs/ARCHITECTURE.md` (new), `cli/docs/BUNDLE_SCHEMA.md`.

### Item 8 — DONE (branch sutura-app, off sutura-cli)
Built the **viewer app** — a local, display-only companion under `app/` (entry point `sutura-app`), branched from sutura-cli so it has the schema + real bundle producer for item 9.
- **Zero-dependency Python server** (`server.py`, stdlib `http.server`): serves the SPA + a read-only JSON API — `GET /api/runs`, `GET /api/runs/<job_id>` (full bundle), `POST /api/chat`. Never runs alignment.
- **`store.py`**: reads bundles from `~/.sutura/results/` per schema v1.0 (metadata/qc/routing/metrics/reconstruction/report), lists newest-first, ignores incomplete bundles (no metadata.json).
- **Frontend** (`static/`, vanilla + **vendored three.js**, no build step): run list sidebar; per run → **3D reconstruction viewer** (three.js point cloud, orbit/zoom/autorotate, colour by **layer / section / method**, reusing the demo's layer palette), summary stat cards, **per-pair method + why + score + QC table**, **method-comparison table** (from candidates, off-dist only, kept marked), input-QC table, report.md, and honest badges. Uses the company logo (`static/logo.jpg`).
- **Chatbot** (`chat.py`, collapsed until invoked): grounded strictly in the loaded bundle — answers method/why/worst/metrics, **shows how PASTE2 compares from the candidates** (and honestly says "only Sutura ran here; run redo-with-PASTE2 in the CLI" when it wasn't), **refuses to re-run alignment**, optional local-Ollama for free-form (given only bundle facts).
- **Reuse note:** reuses the web demo's *visual language* (layer palette `#8ecae6…#e63946`, three.js point cloud, method-honesty copy) rather than importing its React components — a deliberate v1 choice for a build-free, offline, local app. Web demo (`demo/`) untouched.
- **Verified:** served the 4 real bundles from tonight (in-dist Sutura, off-dist Br8100/breast PASTE2, 4-section chain PASTE2+Sutura); `/api/runs` returns all 4 with honest methods; index/app.js/styles/logo/three.js all serve 200; `node --check app.js` passes; 10 hermetic app tests pass (store, API, chat honesty).
- Files: `app/` (pyproject, sutura_app/{__init__,server,store,chat}.py, static/{index.html,styles.css,app.js,logo.jpg,vendor/three.module.min.js}, tests/test_app.py).

### Item 9 — DONE
- **Integration test** `app/tests/test_integration.py`: drives the **CLI** to align real DLPFC and write a bundle, then proves the **app** reads and displays it — store lists+loads the job, displayed method/score/reconstruction match what the CLI wrote, the referenced aligned `.h5ad` exists, the **HTTP API** serves the same run (as the browser fetches it), and the **chatbot** honestly names the method. Passes on the in-dist pair (Sutura, 1.29 spot-pitch).
- **Documented** the working loop in `app/docs/INTEGRATION.md` (diagram + the two commands + what the test proves).
- Proves the full local product loop **CLI → bundle → app**, no data egress.

## Open blockers
- **Browser screenshot:** the Claude-in-Chrome extension is offline this session, so I could not capture a live in-browser screenshot of the viewer. Rendering is verified indirectly (API serves valid data for all 4 real bundles, all assets 200, `node --check` passes on the frontend JS). Providing a self-contained Artifact preview as visual confirmation instead.
- **Xenium (unchanged):** no Xenium data on disk; squidpy 1.6.6 has no `xenium` reader. Implemented as detect + actionable error (convert Xenium → .h5ad, point Sutura at it) per the "clear message" option. Real Xenium ingest deferred until a sample + reader are available.

## Recommendations for next / for Codex
- TBD (updated at end).
