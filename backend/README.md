# Sutura alignment backend

Real inference backend for suturagenomics.bio: upload spatial-transcriptomics
sections, the orchestrator routes to the best alignment method and runs actual
Sutura / PASTE2 inference (no mock), and returns aligned coordinates + honest
metrics + which method produced them.

## Architecture

```
POST /api/align  ──▶ validate .h5ad ──▶ save to storage ──▶ create job ──▶ {job_id}
                                                                │
                                          background worker (async, minutes)
                                                                │
                                   load & QC ─▶ distribution check (frozen shared
                                   basis, Mahalanobis) ─▶ route:
                                     in-dist  → Sutura
                                     off-dist → auto-adapt (fine-tune on the user's
                                                own sections) vs PASTE2, keep best
                                   ─▶ post-QC + retry ─▶ write aligned.h5ad + result
                                                                │
GET /api/result/{job_id}  ◀── status: queued → running(stage,%) → done | failed
GET /api/download/{job_id} ◀── aligned .h5ad
```

- **Async job model**: upload returns a `job_id` immediately; the frontend polls
  `/api/result/{job_id}`. Alignment takes minutes (PASTE2 GW-OT and/or on-the-fly
  fine-tuning), so nothing blocks on a synchronous request.
- **Honesty**: the result always states the exact method used
  (`Sutura`, `Sutura (auto-adapted to your data)`, or `PASTE2`) and why. A PASTE2
  result is never labeled as Sutura.

Files: `pipeline.py` (deployment-agnostic core), `app.py` (FastAPI/local),
`modal_app.py` (Modal deployment), `test_e2e.py` (end-to-end client),
`requirements.txt`.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/align` | multipart upload of ≥2 `.h5ad` sections → `{job_id, status}` |
| GET | `/api/result/{job_id}` | `{status, stage, progress, result?}` |
| GET | `/api/download/{job_id}` | aligned `.h5ad` (moving section with `obsm['spatial_aligned']`) |
| GET | `/api/health` | liveness |

Upload validation (rejected with a clear 4xx + message): must be `.h5ad`, have
`obsm['spatial']` as an (n,2)+ array, 100–200,000 spots, non-empty genes,
≤ 400 MB each, ≥ 2 files (extra sections are used as auto-adapt data).

`result` payload includes: `method`, `method_label`, `reason`, `in_distribution`,
`in_dist_confidence`, `mahalanobis`, `gene_overlap`, `metric`
(`median_error_pitch` when array-bridge ground truth is derivable, else
`footprint_coverage`), `score`, `retry`, `candidates`, `runtime_seconds`,
`aligned_coords` + `ref_coords` (for the 3D viewer), `output_file`.

## Run locally

```bash
# from repo root, with the project venv active
pip install -r backend/requirements.txt   # torch from the CPU wheel index (see file)
uvicorn backend.app:app --host 0.0.0.0 --port 8000

# end-to-end test with a real pair (in another shell)
python backend/test_e2e.py --ref data/DLPFC_151669.h5ad --mov data/DLPFC_151670.h5ad
# off-distribution + auto-adapt path (provide sibling sections as adaptation data):
python backend/test_e2e.py --ref data/DLPFC_151673.h5ad --mov data/DLPFC_151674.h5ad \
    --extra data/DLPFC_151675.h5ad data/DLPFC_151676.h5ad
```

Jobs/uploads/outputs live under `SUTURA_JOBS_DIR` (default `backend/_jobs`).

## Deploy to Modal (preferred)

```bash
pip install modal
modal token new                       # one-time; requires a Modal account
modal deploy backend/modal_app.py     # prints the public https URL
```

`modal_app.py` bakes the code and the small model artifacts
(`results/arca_shared_basis.pt` ≈ 0.3 MB, `results/shared_basis.npz` ≈ 7 MB) into
the image, runs each alignment as a spawned Modal Function (`cpu=4, memory=8Gi,
timeout=3600`), and stores jobs on a Modal Volume (`sutura-jobs`). The web layer
is the same API contract as local.

**One setup note:** the distribution check rebuilds the training-donor embedding
distribution from the 4 DLPFC training slices. Either (a) add those `.h5ad` files
to the image (`add_local_file`), or (b) precompute the mean/inverse-covariance
once and bake that small array in (recommended — avoids shipping ~430 MB of
training data). A `Projector` that loads a cached `tmu/tinv` instead of recomputing
is a 10-line change; see `src/orchestrator.py:Projector`.

### Fallback: Railway / Render

The FastAPI app (`backend/app.py`) is a standard ASGI app and runs as-is on
Railway or Render with a Dockerfile from `requirements.txt` and start command
`uvicorn backend.app:app --host 0.0.0.0 --port $PORT`. Use a persistent disk for
`SUTURA_JOBS_DIR` and a single worker (alignment is CPU-heavy; scale horizontally
with more instances, not threads). These platforms bill for an always-on instance
rather than per-request, so Modal is cheaper for bursty usage.

## What it costs to run

CPU-only; no GPU required. Per-alignment compute (full ~3.5k-spot Visium pair):

| Path | wall time | dominant cost |
|---|---|---|
| in-distribution → Sutura | ~1–3 s | model forward pass |
| off-distribution → PASTE2 | ~2–5 min | GW-OT (`partial_pairwise_align`) |
| off-distribution → auto-adapt + PASTE2 | ~4–7 min | fine-tune (~130 s) + PASTE2 |

**Modal estimate** (verify against current modal.com/pricing): at roughly
$0.13–0.20 per CPU-core-hour, a 5-minute 4-core job ≈ 0.33 core-hours ≈
**$0.04–0.07 per off-distribution alignment**; in-distribution jobs are a fraction
of a cent. Idle cost is ~$0 (Modal scales to zero between requests). Storage on the
Volume is a few MB per job. For low volume, expect **single-digit dollars/month**.

Railway/Render: an always-on small instance is ~$5–20/month regardless of traffic.
