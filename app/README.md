# Sutura viewer app

A **local, display-only** companion to the Sutura CLI. It reads the result
bundles the CLI writes to `~/.sutura/results/<job_id>/` and renders them — the 3D
reconstruction, which method produced each pair and why, all metrics, QC, and a
clean summary. It **never runs alignment or reconstruction**; it only displays
what the CLI produced, and it is honest about which method produced each result.

## Install & run

```bash
.venv/Scripts/python.exe -m pip install -e app
sutura-app                     # opens http://127.0.0.1:8787 in your browser
sutura-app --port 9000 --no-browser
```

Point it at a different store with `SUTURA_HOME` (default `~/.sutura`).

## What it shows

- **Runs** — every completed bundle in the store, newest first.
- **3D reconstruction** — a three.js point cloud of the stacked sections; colour
  by cortical layer, by section, or by the method that aligned each section;
  orbit / zoom / autorotate.
- **Method per pair** — the method that produced each pair's alignment, *why*
  (the routing reason), the score, and the post-QC verdict. Honest labelling
  throughout (Sutura in-distribution, PASTE2 off-distribution).
- **Method comparison** — for off-distribution pairs, the candidates the
  orchestrator compared (auto-adapted Sutura vs PASTE2) with the kept method marked.
- **Input QC** and the full **report**.
- **Chatbot** (optional, collapsed until you open it) — answers questions about
  the run *from the bundle data only*: which method and why, which pair aligned
  worst, and **how PASTE2 compares** (from the recorded candidates). It will not
  run alignment — it points you back to the CLI for that. An optional local
  Ollama model handles free-form questions, given only the bundle facts.

## Architecture

- `sutura_app/server.py` — stdlib `http.server`; static SPA + read-only JSON API.
- `sutura_app/store.py` — reads bundles (schema v1.0; see the CLI's
  `docs/BUNDLE_SCHEMA.md`).
- `sutura_app/chat.py` — grounded chatbot over one run.
- `sutura_app/static/` — vanilla-JS SPA, three.js vendored (no build step).

Reuses the Sutura web demo's visual language (layer palette, three.js point
cloud, method-honesty copy). It does not modify the web demo.

## Tests

```bash
.venv/Scripts/python.exe -m pytest app/tests -q
```
