# Sutura CLI architecture

Sutura's CLI is a thin **agent + UI layer over the existing alignment engine**.
No alignment logic is reimplemented here; the engine (the research repo's
`backend/pipeline.py`, `src/orchestrator.py`, `src/agents.py`, checkpoints) is
wrapped as tools the agent calls. This note explains the design so a contributor
can add a new capability without touching alignment code.

## The four layers

```
 natural language
        │
        ▼
 ┌──────────────┐   interpret(instruction, metadata) → Decision
 │  LLM backend │   rule | ollama | cloud            (metadata only, never expression)
 └──────┬───────┘
        ▼
 ┌──────────────┐   dispatches a Decision to a workflow or a tool,
 │  agent loop  │   streams Events, accumulates a result Bundle
 └──────┬───────┘
        ▼
 ┌──────────────┐   load_data · qc · distribution_check · align ·
 │    tools     │   post_qc · reconstruct · report · (metrics/worst/explain)
 └──────┬───────┘
        ▼
 ┌──────────────┐   backend.pipeline.run_alignment / align_sutura /
 │    engine    │   align_paste2 · orchestrator.distribution_check · agents.*
 └──────────────┘
```

Everything above the engine line lives in `cli/sutura_cli/`. The engine is
located and lazily imported by `core/engine.py` (override with `$SUTURA_REPO`).

### 1. LLM backends (`core/llm.py`)

A backend's only job: turn an instruction + **metadata** (`WorkContext.state_view()`
— names, spot/gene counts, formats; never expression) into a `Decision`:

- `WorkflowRequest(name, args)` — run a multi-step workflow (today: `align_and_reconstruct`).
- `ToolRequest(name, args)` — a single tool (`realign`, `report`, `metrics`, `worst`, `explain_routing`).
- `Reply(text)` — answer/clarify.

Three backends implement `interpret()`:

- **`RuleBackend`** — deterministic keyword parser. No network, no key. Precise for the closed action vocabulary; it is also the safety net.
- **`OllamaBackend`** — local model via `http://localhost:11434` (metadata-only prompt, `format=json`, temperature 0). Best for PHI. Auto-selects an installed model.
- **`CloudBackend`** — Anthropic API (`ANTHROPIC_API_KEY`), same metadata-only prompt.

The LLM backends never trust raw model output. `_finalize()` normalises it
against the closed vocabulary (method/tool-alias normalisation) and **falls back
to the rule planner** when the model goes out-of-vocabulary or under-acts; on any
action-type disagreement the deterministic rule planner wins. This is what lets a
1–3B local model drive the loop safely.

### 2. The agent loop (`core/agent.py`)

`Session.handle(instruction)` interprets one instruction and dispatches it:
- a workflow runs an ordered tool sequence (load → qc → per-pair route+align+post-qc → reconstruct → report), accumulating a `Bundle`;
- a tool request runs one action (a forced re-alignment, a report refresh, or a read-only query over the current bundle).

The session owns the `WorkContext` (raw AnnData stays here, local) and the current
`Bundle`. Follow-up instructions operate on that same job.

### 3. Tools (`core/tools.py`, `core/reporting.py`, `core/reconstruct.py`)

Each tool takes `(ctx, sink, ...)`, emits `Event`s, and returns a metadata dict.
Tools wrap the engine and never re-implement alignment:

| tool | wraps |
|------|-------|
| `load_data` | `anndata` / `scanpy.read_visium`; `_ensure_spatial` recovers coords |
| `qc` | `pipeline.qc_file` |
| `distribution_check` | `orchestrator.Projector` + `distribution_check` (routing) |
| `align` | `pipeline.run_alignment` (auto-routed); `align_sutura`/`align_paste2` (forced) |
| `post_qc` | `agents.neighbor_consistency` / `footprint_coverage` |
| `reconstruct` | `reconstruct.build_pointcloud` (similarity-transform chaining) |
| `report` | `reporting.build_report_md` |

### 4. Events & rendering (`core/events.py`, `render.py`, `tui/app.py`)

The core never draws anything. It emits typed `Event`s to an `EventSink`. Three
sinks render them: `ConsoleSink` (headless, demo-grade), the Textual app, and
`ListSink` (tests). This is what keeps the whole agent loop headlessly testable.

## The result bundle

Every job writes a structured bundle to `~/.sutura/results/<job_id>/`
(`core/bundle.py`, schema v1.0 in [`BUNDLE_SCHEMA.md`](BUNDLE_SCHEMA.md)). The
viewer app reads it; the CLI never renders 3D itself.

## Extending it (adding a capability)

The architecture is intentionally general. To add a new **tool** (staying within
alignment — nothing speculative):

1. Write `def my_tool(ctx, sink, ...)` in `core/tools.py`, emitting `StepStarted`/`StepFinished` and returning a metadata dict. Wrap engine functions; don't reimplement them.
2. Add a handler on `Session` and a dispatch branch in `handle()`.
3. Teach the planners: add the action to `ACTION_SPEC` + an alias in `_TOOL_ALIASES` + a `_canonicalize` case (LLM backends), and a keyword rule in `RuleBackend` (offline). Add a unit test in `test_units.py` asserting the intent routes correctly.
4. If it changes the bundle, bump `SCHEMA_VERSION` and update `BUNDLE_SCHEMA.md`.

Read-only query tools (`metrics`, `worst`, `explain_routing`) are the simplest
template: they answer from `self.bundle` and emit an `AgentMessage`, running no
alignment.

## Testing

- `test_units.py` — planner intents, `_finalize` fallback, reconstruction composition, report formatting (no engine).
- `test_loaders.py` — every loader failure mode (no engine).
- `test_llm_ollama.py` — the real local model plans the core intents (skips if no Ollama).
- `test_tui.py` — the Textual app composes/quits.
- `test_e2e.py` — full loop on in- and off-distribution data + a 4-section chain (needs engine + DLPFC; auto-skips otherwise).
