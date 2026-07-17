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

## FINAL SUMMARY (all 9 items complete)

**Branches:** `sutura-cli` = baseline + items 1-7 (commits ca460a5 → ddd3e9a). `sutura-app` = branched off sutura-cli after item 7, + items 8-9 (59e1571, 32b2247). `main` and `demo/` untouched.

**What got done**
1. Local Ollama planner (llama3.2:3b), no API key — full NL→plan→execute loop for all core intents; closed-vocabulary validation + rule fallback keeps even 1B models honest; new query tools (metrics/worst/explain_routing); 3 real sessions logged.
2. Off-distribution path proven on Br8100 + breast: correct off-dist routing, auto-adapt runs, PASTE2 kept, honest candidate breakdown everywhere.
3. Robust loaders: actionable errors for every failure mode (missing path, wrong obsm keys w/ auto-recovery, empty section, mismatched panels, single-section, non-adjacent, Space Ranger, Xenium), per-pair resilience.
4. Coherent multi-section reconstruction: similarity-transform chaining into one frame, honest exact-vs-pairwise labelling; proven on a 4-section chain.
5. Demo-grade streaming UX: banner, clean steps, method-and-why routing, completion card (console + TUI), Windows-UTF-8 fix.
6. Comprehensive tests: 46 fast + 4 engine e2e (in/off-dist + 4-chain) + integration; local-LLM test hits the real model.
7. Docs: README (NL command table, local-model quickstart, transcript), ARCHITECTURE.md, updated BUNDLE_SCHEMA.md.
8. Viewer app v1 (sutura-app): stdlib server + vanilla/three.js SPA reading the bundle schema — run list, 3D reconstruction (colour by layer/section/method), per-pair method+why+metrics+QC, method-comparison from candidates, grounded chatbot (shows PASTE2 comparison honestly, refuses to re-run). 10 app tests pass.
9. Integration test: CLI aligns real data → bundle → app reads/displays/serves/answers. Documented in app/docs/INTEGRATION.md.

**What's proven** (real runs tonight): in-dist Sutura 1.29 spot-pitch; Br8100 PASTE2 2.82 (adapt 9.53→8.03); breast PASTE2 3.47 (adapt 26.9→7.77); 4-chain composed (centroids cluster <180px); local model plans 7/7 intents; app serves all 4 real bundles; CLI→app integration test green. ~60 tests total.

**What's open / not done**
- **Xenium** ingest: no data + no reader in this env → implemented as detect + actionable convert-to-.h5ad error. Real ingest needs a sample + a squidpy/Xenium reader.
- **Browser screenshot** of the served app: Chrome extension offline all session. Rendering verified via API + valid-JS + assets; a self-contained Artifact preview of a real bundle was published as visual confirmation.
- **"Panel too different → PASTE2 direct (no adapt)"** branch is coded + unit-tested but not exercised on real data (breast still shares 95% genes); would need a targeted/Xenium panel (<50% overlap).
- Neither branch pushed (per no-push-unless-asked). LF→CRLF warnings are cosmetic.

**Recommended next (for Rushil / Codex)**
1. **Push both branches** and open PRs (sutura-cli first, then sutura-app on top).
2. **See the app live:** `sutura -H "align ./demo_data and reconstruct in 3D"` then `sutura-app` — confirm the 3D viewer in a real browser (the one thing I couldn't do headless).
3. **Xenium:** grab a public 10x Xenium sample + wire a real reader (squidpy version bump or manual cell_feature_matrix + cells parquet loader) to replace the actionable-error stub.
4. **Global reconstruction:** the multi-section stack is honest pairwise composition; a true simultaneous solve (GPSA-style) is the natural v2 for long chains.
5. **App polish for SF:** wire the app's optional Ollama chat end-to-end in-browser; add a per-layer breakdown chart; consider packaging `sutura`+`sutura-app` as one installer.
6. **Cloud backend** untested (no key) — smoke-test CloudBackend once a key is available.

## TUI visual redesign (2026-07-16, post-overnight) — DONE
User feedback: the Textual TUI was cluttered — branding top-right, backend buried in scroll, a 35-section load dumped a wall of text, no separation between stages, per-pair results as repeated multi-line blocks. Redesigned the *presentation* only (functionality identical):
- **Top-left fixed header** (`Brand` widget): `◗ SUTURA` + a second line with the active backend/model — e.g. `ollama · llama3.2:3b · local, no data egress` (backend now selected eagerly at mount in a worker, so it shows immediately instead of scrolling past).
- **Collapsed load summary:** `load_data` no longer lists every section; it emits `loaded 35 section(s) · 3,400–4,900 spots each` (names shown only for ≤4). Fixed in `tools.py` so console benefits too.
- **Stage separation:** each stage (Load / QC / Alignment / 3D reconstruction / Report) is a left-aligned `Rule` divider with the stage name, so the eye parses what happened where.
- **Compact per-pair table:** new `PairResult` event (emitted from `agent._record_pair`) carries structured pair data; the renderer prints one aligned row per pair — `pair → method → error → routing(in/off·maha, the "why") → qc` — under a single column header, instead of multi-line routing+align+post-QC blocks. Method labels shortened (Sutura / Sutura·adapt / PASTE2); per-pair step chrome routed to the status bar.
- **Calmer completion card:** no longer re-lists every pair (the stream table already did); shows counts + methods + bundle path.
- Applied the same treatment to the headless console renderer (`render.py`) for consistency. New `tui_screenshot.svg`.
- Tests: `test_tui.py` updated for `Brand`/`_backend_line`/`_short_method`; 44 fast tests pass.
- Files: `cli/sutura_cli/tui/app.py`, `cli/sutura_cli/render.py`, `cli/sutura_cli/core/events.py` (+PairResult), `cli/sutura_cli/core/agent.py`, `cli/sutura_cli/core/tools.py`, `cli/tests/test_tui.py`, `cli/docs/tui_screenshot.svg`.
- Both branches pushed to `Senekw/sutura-genomics` (not `biostartup`); `main`/website untouched. `sutura-app` merged to carry the redesign.

## CLI redesign round 2 — assistant framing, theme, safety mode (2026-07-16) — DONE
Purely UX/visual (functionality identical):
1. **ASCII DNA logo** top-left in the `Brand` header (a 4-line double-helix mark, purple), doesn't scroll. Same mark added to the headless console banner.
2. **Backend/model hidden:** removed the `ollama · llama3.2:3b` line from the header and headless startup; kept "local · no data egress". Backend still selected silently under the hood.
3. **Purple / black / white theme** across the TUI (near-black `#08080c` bg, `#f0eefb` text, `#b78bff` purple accents/dividers/routing) and the console renderer (ACCENT→purple, dropped cyan).
4. **Confirmation before file access:** in **manual mode** the agent asks "About to read N sections from <path> and run alignment. Continue? [y/n]" before reading/aligning; decline reads nothing. Implemented via `Session.on_confirm` + `Session.mode`; the TUI blocks the worker thread on a `threading.Event` until the user answers. Headless defaults to **auto** (no prompt).
5. **Auto/manual toggle:** `f2` key or typing `auto`/`manual`; current mode shown in the status bar ("▸ manual mode — confirms before file access").
6. **Name-a-file-and-go:** `Session._named_target` resolves a bare file/folder name mentioned in the request against the cwd ("use my_sections", "the file is breast.h5ad") — no path syntax needed.
7. **Assistant framing:** welcome + placeholder call it "your spatial-transcriptomics alignment assistant", not a chatbot.
- Note: the 21st.dev "Custom ASCII art" canvas raster pipeline (the big JSON param spec) is a *web/canvas* effect; it doesn't map to a Textual terminal, so the TUI uses a clean hand-drawn ASCII helix. That canvas effect is a candidate for the **web app** live view if wanted.
- Tests: +9 (mode toggle, ASCII logo, `_named_target` file/folder resolution, manual-decline reads nothing, auto no-prompt). 49 fast tests pass.
- Files: `cli/sutura_cli/tui/app.py`, `cli/sutura_cli/core/agent.py`, `cli/sutura_cli/render.py`, `cli/sutura_cli/cli.py`, `cli/tests/test_tui.py`, `cli/tests/test_loaders.py`, `cli/docs/tui_screenshot.svg`.

## App live-progress mode (sutura-app) — DONE
Stream the REAL CLI pipeline to the browser and animate it; display-only viewer kept.
- **Server (SSE):** `sutura_app/live.py` = `LiveHub` (thread-safe pub/sub with replayable history) + `serialize()` (core events → small JSON; per-pair geometry downsampled to ~1600 pts, keeping mov/aligned index-matched) + `LiveSink` + `run_live()`. `server.py` adds `GET /live`, `GET /api/live/stream` (SSE), `GET /api/live/state`, and `serve_live()` + a `live` subcommand.
- **Entry points:** `sutura-app live "<instruction>"` OR `sutura --live "<instruction>"` (CLI delegates to the app). Starts the server, opens `/live`, runs the real alignment (auto mode), streams every stage.
- **Live page** (`static/live.{html,css,js}`, purple/black/white, vanilla canvas): left stage timeline (load→QC→routing→align→post-QC→3D→report) lighting up; center canvas animates the **before→after**: reference spots static, moving spots lerp from their **torn** coords to their **aligned** coords (the real computed output) over ~2.2s per pair; right panel builds the honest per-pair list (method + error + qc + in/off-dist); on done it fetches the composed reconstruction and ends on the **rotating real 3D volume** + summary metrics. **Never fabricated** — geometry & metrics are the real pipeline output.
- **To add coords for the animation:** `events.PairResult` gained optional `ref/mov/aligned_coords` + layers (TUI/console ignore them); `agent._record_pair` populates them.
- **Verified end-to-end:** captured a real run (3 DLPFC sections → 2 pairs): events {start, 20 stage, 17 progress, 2 routing, 2 pair w/ real geom 2192 & 2395 pts, done, end}; methods honest (Sutura 1.29, PASTE2 6.67 retry); 13,399-pt 3D volume. SSE endpoints serve 200; SSE frames deliver. Published a self-contained **Artifact** replaying the real stream (browser ext offline, so no live screenshot).
- Tests: `app/tests/test_live.py` (hub replay, serialize stage/routing/pair-with-geom/pair-without). 63 fast tests pass (cli + app).
- Files: `app/sutura_app/live.py` (new), `app/sutura_app/server.py`, `app/sutura_app/static/live.{html,css,js}` (new), `cli/sutura_cli/core/events.py`, `cli/sutura_cli/core/agent.py`, `cli/sutura_cli/cli.py` (--live), `app/README.md`, `app/tests/test_live.py`.

## Website — DONE (branch `agent-beta-gate` in `C:\Users\karti\sutura-genomics`, off origin/main; NOT pushed, NOT deployed)
Repo: `Senekw/sutura-genomics` (Next.js 16, static export, Netlify). Worked on a branch off origin/main; the live site (main) is untouched.
- **Agent beta-tester gate:** after the existing sign-in, an interstitial `/demo/beta` asks "Are you an agent beta tester?" → **Yes** reveals a second gate requiring the beta code **SGYC1234 / spatialbioSGYC** (with the note "if you're YC it's the same one provided before") → unlocks the live agent runs. "Not now" → continues to the demo. The live `/demo/runs` page is now gated behind the beta flag (redirects to `/demo/beta`). `demo/login` redirects to `/demo/beta` after sign-in.
- **Auth:** `src/lib/demoAuth.ts` gained `BETA_CREDENTIAL` + `checkBetaCredentials` / `betaSignIn` / `betaSignOut` / `isBetaAuthed` (separate sessionStorage flag). Client-side, matching the existing demo-cred pattern (it's a walkthrough gate, not real auth — noted in code).
- **Chatbot now actually works, keyless + serverless** (required, since the site is a static export with no runtime API): `analysisChat.localAnswer(question, ds, run)` parses the question and answers from THIS run's REAL metrics — worst/best region, tear resolved, PASTE2 comparison, method, coverage, params, per-region breakdown. `askChat` uses it as the grounded path (still prefers `/api/chat` if some deployment provides one). Honest labelling kept, no fabricated numbers. The existing on-brand `AnalysisAssistant` UI is reused.
- **Deep Chat decision:** the user pointed at Deep Chat, but it's not installed and the site is a static export — a real LLM there needs either a browser-hosted `webModel` (multi-GB download, bad UX) or the same client-side rule-based handler. So I made the EXISTING chat genuinely answer (same keyless substance) rather than add a heavy dependency + build risk to production. Deep Chat can be a later UI swap over the same `localAnswer` backend if wanted.
- **Verified:** `next build` + TypeScript pass; `/demo/beta` and `/demo/runs` generate; credential + intent logic sanity-checked. Purple `#6633ee` (site's existing brand) kept.
- Files: `src/lib/demoAuth.ts`, `src/app/demo/login/page.tsx`, `src/app/demo/beta/page.tsx` (new), `src/app/demo/runs/page.tsx`, `src/lib/analysisChat.ts`, `src/components/demo/AnalysisAssistant.tsx`. Commit `2af09c2`.

## App live-progress `--live` freeze — DIAGNOSED + FIXED (2026-07-16, branch `sutura-app`)
**Symptom (reported):** `sutura --live "align these sections and reconstruct in 3D"` froze — both the browser live view and the terminal got stuck mid-run and stopped progressing to the next step.

**Reproduction (what I ran):** editable-installed `cli/` + `app/`, `SUTURA_REPO=C:\Users\karti\arca`. Drove the REAL pipeline via `sutura_app.server live` on clean DLPFC sets (2-section `demo_data/` = 151507/08; 12-section `data/` = 11 pairs) and watched the SSE stream with a timestamping client (browser proxy — the Chrome extension was offline, so no canvas screenshot; the SSE bytes are identical to what the browser's `EventSource` receives, and `live.js` is purely event-driven off them).

**Root cause (a real per-pair engine stall + three live-plumbing gaps that turned it into a silent freeze):**
0. **The actual trigger — a wedged alignment pair.** On the 12-section run the SECOND pair routed off-distribution and ran **PASTE2** (`PASTE2 starts...`), which then made **zero progress for 180s+** (POT/optimal-transport solve grinding/wedged on that pair). This is the concrete "stuck mid-run and stopped progressing to the next step" — a single pair's engine call hangs. The pipeline itself is NOT deadlocked (2- and 12-section runs stream every earlier stage cleanly); one pair's solver is pathological.
1. **Terminal is silent for the whole run.** `serve_live` ran the pipeline with ONLY a `LiveSink` (hub → browser); nothing was printed to the terminal during a run. Confirmed: a 12-section run did >90s of real work while the terminal still showed only its 2 startup lines. That IS "terminal stuck mid-run" — no progress output at all, so a slow/wedged run is indistinguishable from a crash.
2. **No watchdog / heartbeat / timeout anywhere.** The only keepalive was the 15s SSE `: ping`, which just warms the socket — it does NOT detect a stalled *stage*. So the wedged PASTE2 pair left the browser timeline on "align · active" forever and the terminal silent — a silent hang with no diagnosis and no way to tell "slow" from "wedged".
3. **Fragile SSE fan-out under backpressure.** `LiveHub.publish` used `queue.put_nowait` on a 1000-cap queue and silently dropped the NEWEST message on overflow — including the terminal `done`/`end` — so a slow/large run could leave the browser stuck on the last stage; `subscribe()` replay also truncated silently at 1000. (Latent at small scale; a late-connect client confirmed history replay otherwise works.)

**Key measured fact:** a full-resolution PASTE2 (POT optimal-transport) solve on ONE DLPFC pair (4226×4384 spots, 33,538 genes) takes **393s (~6.5 min)** — slow but FINITE, not wedged. Sutura (in-distribution) pairs take ~15–30s. So the "stall" is a legitimately-slow PASTE2 pair emitting zero intermediate progress; the OLD live view showed nothing during it, so it looked frozen. Off-distribution pairs (and post-QC PASTE2 safety-net retries) hit this; in-distribution pairs don't. The user's 2–3 homogeneous DLPFC sections are in-distribution → Sutura → fast, so their freeze was purely the no-feedback + no-heartbeat gap.

**Fix (layered: visibility first, bound only the interactive view, watchdog as backstop):**
- **Terminal now shows progress.** `serve_live` tees the SAME event stream to the CLI's `ConsoleSink` — `--live` renders load→QC→Alignment table→3D→report→"Run complete" card, identical to headless, plus a final `✓ alignment complete` / `✗ did not finish (…)` line. This alone kills the "terminal frozen" symptom.
- **Watchdog + heartbeat + backstop timeout** (`live.run_live` rewritten): pipeline runs in a worker thread; the main thread supervises via a `WatchedSink` that stamps last-event time + current stage. A `heartbeat` every `SUTURA_LIVE_HEARTBEAT` (10s) proves liveness on the browser AND terminal during a silent PASTE2 solve. If no event for `SUTURA_LIVE_STAGE_TIMEOUT` (default **600s**, sits ABOVE a full 393s PASTE2 so a legit slow pair is never falsely aborted) or the run exceeds `SUTURA_LIVE_RUN_TIMEOUT` (5400s), it publishes `error`+`end` and returns — **surfaces instead of hanging**. `run_live` returns an outcome dict; `serve_live`'s exit code reflects it.
- **Per-pair alignment budget, OFF by default, bounded only for the live view** (`cli/sutura_cli/core/tools.py`): each pair's engine call runs under `_call_with_timeout`; past `SUTURA_ALIGN_TIMEOUT` it raises `AlignError`, which the agent's existing `except (LoaderError, AlignError)` **skips-and-continues** (reconstruction builds from the contiguous good chain). Read at CALL time; default **0 = OFF** so headless/batch runs let PASTE2 finish (correctness). `serve_live` sets a live-only default of **180s** (user value wins) so the browser view stays responsive — a pair slower than that is skipped with an honest note rather than freezing the animation. The skipped solve keeps running in a leaked daemon thread but self-clears when PASTE2 finishes (~6.5 min); it no longer blocks the pipeline.
- **Robust delivery.** `publish` evicts the OLDEST queued item on overflow (keeps newest incl. `done`/`end`); queue cap 8192, history cap 20000. `MultiSink` tees to N sinks and isolates a failing sink.
- **Browser** (`live.js`/`live.css`): handles `heartbeat` (keepalive caption on idle stages), `error` (marks the active stage red, "Live run interrupted"), `end` with non-complete status; new `.stage.error` style.

**Verification (real runs):**
- **PASTE2 timing:** measured 393.3s to completion on DLPFC_151507→151508 (detached run) — the number that sets every threshold.
- **Unit tests** (hermetic): watchdog surfaces `error("stalled")`+`end` in ~2s on a stall (no hang); heartbeats fire on a slow-but-progressing stage; clean run ends `status=complete`; overflow test proves newest events survive; `MultiSink` isolates a failing sink. `_call_with_timeout` / `_align_timeout`: returns value, propagates errors verbatim, raises `AlignError` on stall in ~1s, OFF when 0, reads env at call time.
- **2-section end-to-end (fixed):** terminal streamed the whole run and printed `✓ alignment complete`; browser SSE delivered load→qc→route→align→postqc→pair(geom 159KB)→reconstruct→report→**done→end** with interleaved heartbeats (Sutura 1.29 spot-pitch, 8,610-pt volume).
- **Large-input (12-section `./data`), OLD code:** reproduced the real freeze — pair 2's PASTE2 solve ran silently; terminal showed only 2 lines, browser stuck on "align". FIXED code, watchdog only: surfaced `✗ stage 'align' stalled` on BOTH terminal (with 27 `… still in 'align' (Ns)` heartbeats) and browser (`error`+`end`).
- **Graceful skip-and-continue (3-section live `./x/live3`, `SUTURA_ALIGN_TIMEOUT=90`):** pair 0 aligned via Sutura (1.29); pair 1's post-QC PASTE2 retry ran silently → 16 heartbeats streamed to browser + terminal (`… still in 'align' (Ns)`) → skipped at 90s with `pair … skipped: … exceeded the 90s per-pair time limit` → run CONTINUED to 3D reconstruct (2 sections, 8,610 pts) + report → `✓ Run complete` (job `…233029-62794e`) and `done→end` on the browser. No hang; both sides ended cleanly.
- Tests: `app/tests/test_live.py` +5; app suite 19 passed; cli suite 56 fast + 13 e2e/ollama passed (a `.F` in one combined run was an ollama timeout flake under concurrent demo-server load, not a code failure — each suite passes in isolation).
- Files: `app/sutura_app/live.py`, `server.py`, `static/live.{js,css}`, `tests/test_live.py`, **`cli/sutura_cli/core/tools.py`**. Env knobs: `SUTURA_ALIGN_TIMEOUT` (per-pair budget; 0=off, live default 180), `SUTURA_LIVE_STAGE_TIMEOUT` (600), `SUTURA_LIVE_RUN_TIMEOUT` (5400), `SUTURA_LIVE_HEARTBEAT` (10).
- **On "35 sections":** `./data` actually *discovers* 35 sections — 12 DLPFC + nested Space Ranger samples under `data/external/` (breast, mouse) — and QC passed 35/35. But those are different tissues/gene panels, so most cross-tissue pairs route to PASTE2 (~6.5 min each) → an unbounded run would take hours (not a hang). With the live 180s budget those pairs are skipped with honest notes and the run stays interactive; run headless with `SUTURA_ALIGN_TIMEOUT=0` to align them fully.

## Recommendations for next / for Codex
- TBD (updated at end).

## Overnight validation of the hybrid PASTE2-beating result (2026-07-17, branch hybrid-combined)
**Goal:** rigorously validate/harden/extend last night's result: fit-residual-gated piecewise
correction on PASTE2 beat PASTE2 (3.73 vs 4.39 LODO), and self-supervised breast 1.20 vs 3.65.
Branch pushed to Senekw first (backup). Built `src/hybrid_validate.py` (resumable, PASTE2 cache,
heartbeat, per-cell try/except, watchdog).

### Setup verified before launch
- PASTE2 is deterministic: re-solving Br8100 sev0 gives 2.9866 == last night's 2.987 (cache sound).
- **Gate reproduces exactly with UNIFORM weights**: gated_rigid Br8100 sev0 = 1.4611 == last night's
  1.461. KEY: the gate needs NO features at all - only the PASTE2 base coords + moving geometry
  (per-pair OT confidence weighting actually made it slightly worse: 1.736). So the gate is fully
  feature-free / deployable, which also strengthens the leakage story.
- PASTE2 timing: DLPFC ~90-450s/solve (grows with severity); OOD cheap (mousebrain sev4 = 55s).
  Caching every base makes all re-analysis free.
- OOD pairs available: breast (bridge 91%), mousebrain (bridge 90%). Mouse kidney is single-section
  (no pair); no cerebellum on disk. So OOD = breast + mousebrain + the DLPFC held-out donors.

### Grid running (PID 22340, seed-outer so seed-0-all-datasets lands first)
Datasets Br8100/Br5292/Br5595 (DLPFC) + breast/mousebrain (OOD); DLPFC sev {0,1,2,3,4,6,8},
OOD sev {0,2,4,6,8}; seeds {0,1,2}. Configs per cell (on the cached PASTE2 base): paste2,
gated_rigid (=last night's gate), gated_rigid_cv, gated_affine, gated_quad (CV-gated, high-sev
extension), gated_rigid_thr{2,3,6,8} (robustness), selfsup_clean (leak-free: trained only on
self-warps of ref A), selfsup_leak (trained on A-B bridge == last night's breast setup),
combo_gated_selfsup. Incremental -> research/results/hybrid_validate.csv.

### Early single-cell numbers (Br8100 sev0 seed0, cached)
paste2 2.99 | gated_rigid 1.461 (reproduces) | gated_affine 1.44 | gated_quad 1.45 |
selfsup_clean 14.05 (leak-free residual does NOT transfer at sev0 - watch this). 

### CRITICAL early signal (Br8100 sev0 seed0, full run) - the self-sup result was LEAKING
paste2=2.99 | gated_rigid=1.461 (reproduces) | gated_affine=1.44 | gated_quad=1.45 |
**selfsup_clean=12.86 (leak-free, trained only on ref-A self-warps) - does NOT beat PASTE2** |
**selfsup_leak=1.49 (trained on the A-B array bridge = last night's breast setup) - beats PASTE2**.
=> Last night's self-supervised breast 1.20 almost certainly LEAKED (train target == eval target,
the array bridge). The leak-free version fails to generalize. Confirming across breast/mouse next.
The GATE result stands (real, reproduces, leakage-audited GT-free + feature-free). Being brutally
honest per the brief: the "biggest result" (self-sup OOD) does not survive a leakage-clean test.

### Br8100 full severity (seed 0): affine EXTENDS the win to high severity
config MEAN(sev-avg): paste2=3.30 | gated_rigid=2.77 | **gated_affine=2.36 (best)** | gated_quad=2.46
| selfsup_clean=12.86 (leak-free, FAILS) | selfsup_leak=1.57 (leaking) | combo=7.02.
gated_rigid now wins at EVERY severity s0..s8 (gate falls back at high sev so no harm - last night's
crossover harm is gone). **gated_affine actively helps at high sev** (s6 3.29 vs paste2 3.63; s8 3.83
vs 4.03) - the per-piece affine fit absorbs the smooth stretch the rigid model can't. This is the
high-severity extension the brief asked for. Confirmed leak: clean 12.86 vs leaking 1.57.

### DLPFC LODO-mean (seed 0) - reproduces 3.73 exactly + affine improves it
On last night's 5-sev grid [0,2,4,6,8]: gated_rigid = (Br8100 2.946 + Br5292 4.744 + Br5595 3.498)/3
= **3.73**, paste2 = **4.39** - EXACT reproduction of last night to the decimal.
On the fuller 7-sev grid [0,1,2,3,4,6,8]: paste2=4.28 | gated_rigid=3.49 | **gated_affine=3.08 (best,
28% cut vs PASTE2)** | gated_quad=3.14. Wins on all 3 folds at every severity. selfsup_clean fails on
all 3 (13-14); selfsup_leak gives the ~1.1-1.9 leak signature. Affine = the high-severity extension,
validated across all DLPFC donors. Seeds 1,2 (variance) + breast/mouse OOD pending.

### BREAST (OOD, seed 0) - DEFINITIVE: last night's 1.20 was a LEAK; but the GATE generalizes OOD
paste2=3.65 (reproduces last night's 3.652) | gated_rigid=3.24 | gated_affine=3.22 | gated_quad=3.20
(**gate BEATS PASTE2 on breast too, ~12% cut**) | **selfsup_clean=6.02 (leak-free) LOSES to PASTE2** |
**selfsup_leak=1.09 == last night's "1.20"** (leaking; trains on the eval target). combo=3.84 (worse
than gate alone - the self-sup "winner" wasn't real, so combining hurts).
VERDICT so far: (1) last night's self-supervised OOD headline was a leakage artifact - the honest
leak-free number LOSES to PASTE2. (2) The training-free GATE is the real result and it generalizes
off-distribution (beats PASTE2 on breast). (3) "Combine the two winners" collapses to "there is one
real winner (the gate)". Mouse brain + seed variance pending.

### SPEED: subsampling PASTE2 gives big speedups, gated win survives (Br8100 sev4)
N=3639(full) 238s paste2 3.50 gated 3.26 | N=2500 71s (3.4x) paste2 3.60 gated 3.24 (NO accuracy loss)
| N=1500 18s (13x) gated_affine 2.95 | N=900 6s (42x) | N=600 2s (135x). PASTE2 scales super-linearly;
the GATE beats PASTE2 at EVERY subsample level. Recommendation: subsample to ~2500 spots = 3.4x faster,
lossless; ~1500 = 13x, minor loss. With base-caching (already in the harness) this makes the method
practical. (Note: n_scored shrinks with N so low-N numbers are noisier.)

### MOUSEBRAIN (2nd OOD, seed 0) + seed-0 pass COMPLETE
mousebrain: paste2=5.47 | gated_rigid=5.18 | **gated_affine=4.92 (best, wins every severity)** |
selfsup_clean=6.28 (leak-free, LOSES) | selfsup_leak=0.84 (leak signature). 
=> Gate generalizes to BOTH OOD datasets (breast + mouse), beating PASTE2 at ~every severity.
Self-sup leak-free FAILS on all 5 datasets; the leak version is last night's result.
SEED-0 SUMMARY (all 5 datasets): gate (esp. affine) beats PASTE2 everywhere. affine LODO(DLPFC,7sev)
=3.08 vs paste2 4.28; breast affine 3.22 vs 3.65; mouse affine 4.92 vs 5.47. Seeds 1,2 (variance) running.

## MORNING SUMMARY (overnight validation complete, 2026-07-17, branch hybrid-combined)
Full grid DONE: 5 datasets x severities x 3 seeds, 1117 rows, **0 errors**, ~4.5h detached.

**Is the PASTE2-beating result real and robust? YES - for the gate.**
- Reproduces last night EXACTLY: gated_rigid = 3.73 on the 5-sev grid (paste2 4.39), to the decimal.
- Beats PASTE2 on ALL 5 datasets (3 DLPFC + breast + mouse) at essentially EVERY severity.
- **gated_affine is the validated best: DLPFC LODO 3.10 +/- 0.04 vs PASTE2 4.26 +/- 0.03 (27% cut).**
  Off-dist: breast 3.21 vs 3.67; mouse 5.26 vs 5.58. Variance tiny - not a lucky seed.
- Proven GT-FREE and FEATURE-FREE (bit-identical output when gt/features are trashed); threshold-robust
  (beats PASTE2 for thr 2-12). No leakage.
- High-severity extension WORKS: the gate falls back (no harm) and per-piece affine actively helps at
  high severity (CV-gated so it can't overfit).
- Speed: subsample PASTE2 to ~2500 spots = 3.4x lossless / ~1500 = 13x; gate wins at every level.

**The other headline (self-supervised OOD breast 1.20) was a LEAK - RETRACTED.**
It trained on the A-B array bridge = the eval target. Leak-free (train on ref-A self-warps only) it
LOSES to PASTE2 on every dataset (breast 6.02 vs 3.65; mouse 6.28 vs 5.47; DLPFC ~13-14). The "1.20"
was the leak's dataset-independent signature (~0.8-1.9 everywhere). Combining it with the gate hurts.

**Single most important thing this enables:** a drop-in, training-free, ground-truth-free accuracy
boost for OT-based spatial alignment (PASTE2/GW) that is SAFE BY CONSTRUCTION (self-gated on its own
fit residual, so it never makes results worse) and improves PASTE2 by ~15-30% on torn tissue,
generalizing across tissues. Product: a "+accuracy" toggle that can't regress. Paper: a method note
(+ the array-bridge-self-supervision-leaks cautionary tale).

Artifacts: research/FINDINGS_hybrid_validated.md, research/results/hybrid_validate.{csv,png},
hybrid_validate_summary.txt, leakage_audit.txt, speed_probe.txt. Harness: src/hybrid_validate.py
(resumable, PASTE2-cached). main/website/demo untouched.

## Solidify/package pass (2026-07-17, branch hybrid-combined) - honest assessment

Packaged the validated gate: `src/gate_refine.py` (self-contained, no torch/features/GT) with
`gate_refine(base_coords, moving_coords, order="affine")`; 9 unit tests pass (incl. exact reproduction
of 1.4611 and never-regress on a garbage base). Wired into the orchestrator behind `--gate-refine`
(default OFF; honest "PASTE2 + Sutura refinement" labeling; kept only if it doesn't regress).
Robustness pass on 3 new DLPFC cross-section pairs running (appends to hybrid_validate.csv).

### Honest boundary found while packaging
Identical-copy SELF-alignment is degenerate: PASTE2 matches each spot to its twin by (identical)
expression and is ~exact (err ~0), so the gate has nothing to refine and can add a little noise on the
smooth-warp component. Consequence: single-section tissues (cerebellum/kidney/etc.) can't give a valid
gate test without a real 2nd section. "Never-regress" is EMPIRICAL over realistic imperfect-OT inputs
(holds on all 5 grid datasets + confirmed on the new cross pairs), NOT a hard guarantee on a near-
perfect base. Documented in gate_refine docstring, tests, and PAPER draft.

### (a) Publish as a method note? YES - qualified.
Strong enough for an Applications Note (Bioinformatics) / Method (GigaScience): a reusable, honest,
safe-by-construction ~15-30% accuracy add-on for OT alignment on torn tissue, GT-free and feature-free
by proof, reproduced across datasets/severities/seeds, + a genuinely useful leakage cautionary result.
NOT enough for a high-impact standalone-method paper (it's a refinement, not a new aligner).
**Single biggest risk to publishing:** the ground truth is SYNTHETIC tears (smooth-bump + rigid
excision) with Visium-array-bridge GT. A reviewer will ask for at least one REAL torn section with
independent GT (landmarks / H&E registration). That single experiment (Section 7 of the paper draft)
is the gating item; without it, it's a synthetic-benchmark methods note, not a full paper.

### (b) Ship as a product feature? YES.
It's a cheap, safe "+accuracy" toggle on any PASTE2 result: never-regress on realistic inputs (it
falls back), needs no training/labels, and the subsampling path (3.4x lossless / 13x) keeps it
interactive. Wired behind a flag with honest labeling. Good product properties.
**Single biggest risk to shipping:** the never-regress guarantee is empirical, not absolute - a near-
perfect base + smooth-warped moving frame can regress slightly. Mitigation before GA: keep it opt-in
with the honest "kept only if it improves vs the base" label (already implemented in the orchestrator:
if refined error > base error it KEEPS PASTE2), and/or a no-GT self-check that reverts when the gate's
own fit barely changes the base. The orchestrator wiring already only relabels to "+refinement" when
it does not regress, so the shipped default is safe.

### Bottom line
The gate is a real, robust, honestly-scoped result: publishable as a method note (pending one real-tear
experiment) and shippable as a safe accuracy add-on now. The retracted leaky self-sup is NOT
reintroduced anywhere.

### Orchestrator wiring VERIFIED on a real run
`python src/orchestrator.py --only Br8100 --gate-refine`: routed off-dist Br8100 to PASTE2 (3.39),
applied the gate -> 2.51 pitch (26% better), labeled honestly "Applied PASTE2 + Sutura refinement:
3.39 -> 2.51 pitch (kept, never-regress)". Default (no flag) behavior unchanged. Fixed a real-input
bug: raw PASTE2 barycentric output carries NaN rows (zero-mass spots); gate_refine now fits on finite
rows and fills NaN spots with the piece fit (never propagates NaN). +test. Robustness grid confirms
the gate on the NEW DLPFC cross pairs too (Br5292b sev0: paste2 4.40 -> gated_affine 2.37).

### Robustness pass - new DLPFC cross pairs confirm; PASTE2 s8 timeout on big pairs
Br5292b (4789/4634 spots, NEW cross pair) seed0: gate wins at every completed severity -
paste2 4.40->gated_affine 2.37 (s0), 4.51->2.63 (s2), 4.83->3.42 (s4), 5.18->4.24 (s6); ~35% mean cut.
Br5595b/Br8100b in progress. HONEST: on the largest pairs at sev8, full-res PASTE2 exceeded the 900s
watchdog and was skipped (per-cell try/except; run continued) - a real data point that full PASTE2 is
impractical at ~4800 spots + max tear, reinforcing the subsampling speedup (~2500 spots = 3.4x lossless).
The gate is unaffected (milliseconds); only the PASTE2 base is the bottleneck.
