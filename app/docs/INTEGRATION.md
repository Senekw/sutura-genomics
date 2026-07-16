# End-to-end integration: CLI → bundle → app

This is the proven, working product loop, entirely local, no data egress.

## The path

```
┌──────────┐   align real data     ┌───────────────────────────┐   read + display   ┌──────────┐
│  sutura  │ ────────────────────► │ ~/.sutura/results/<job>/  │ ─────────────────► │ sutura-  │
│  (CLI)   │   writes a bundle      │  metadata / metrics /     │   (never re-runs)  │  app     │
└──────────┘                        │  reconstruction / report  │                    └──────────┘
                                    └───────────────────────────┘
```

## Do it yourself

```bash
# 1. the CLI aligns local sections and writes a bundle to ~/.sutura/results/
sutura -H "align the sections in ./demo_data and reconstruct in 3D"

# 2. the viewer app reads that same store and displays the run
sutura-app            # opens the browser at http://127.0.0.1:8787
```

Both read/write the same store (`$SUTURA_HOME`, default `~/.sutura`). The app is
display-only — it renders the bundle the CLI produced and never runs alignment.

## What the integration test proves

`app/tests/test_integration.py::test_cli_bundle_is_read_and_displayed_by_app`
(needs the engine + DLPFC data; auto-skips otherwise):

1. Drives the **CLI** (`sutura_cli.core.agent.Session`) to align real DLPFC
   sections and write a bundle (`status == complete`).
2. The **app** store layer (`sutura_app.store`) lists and loads that job.
3. What the app displays **matches** what the CLI wrote — method label, score,
   reconstruction point count/fields — and the aligned `.h5ad` it references
   exists on disk.
4. The app's **HTTP API** (`/api/runs`, `/api/runs/<job_id>`) serves the same run,
   exactly as the browser fetches it.
5. The **chatbot** answers about the real run, honestly naming the method that
   produced it.

Verified passing on the in-distribution DLPFC pair (151507/151508 → Sutura, 1.29
spot-pitch), producing a valid bundle the app renders.
