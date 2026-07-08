"""
Modal deployment of the Sutura alignment backend.

Serves the same FastAPI app (backend/app.py) and runs the same pipeline
(backend/pipeline.py) as local, but:
  * heavy alignment runs as a spawned Modal Function (true async, autoscaled)
  * jobs + uploads + outputs live on a Modal Volume (persistent across requests)
  * model checkpoints + the frozen basis are baked into the image from ../results

Deploy:
    pip install modal
    modal token new                      # one-time auth (needs a Modal account)
    modal deploy backend/modal_app.py    # prints the public https URL

The web endpoint is the same API contract as local:
    POST /api/align, GET /api/result/{job_id}, GET /api/download/{job_id}
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import modal

REPO = Path(__file__).resolve().parent.parent

# Image: CPU torch + the alignment stack + repo source & model artifacts.
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "torch==2.12.1", "torch_geometric==2.8.0", "anndata", "scanpy",
        "scikit-learn", "scipy", "numpy", "paste-bio", "fastapi[standard]",
        "python-multipart", "harmonypy==0.0.10",
        extra_index_url="https://download.pytorch.org/whl/cpu",
    )
    # bake in the code and the (small) model artifacts
    .add_local_dir(REPO / "src", "/root/src")
    .add_local_dir(REPO / "backend", "/root/backend")
    .add_local_file(REPO / "results" / "arca_shared_basis.pt",
                    "/root/results/arca_shared_basis.pt")
    .add_local_file(REPO / "results" / "shared_basis.npz",
                    "/root/results/shared_basis.npz")
    # the 4 DLPFC training slices are needed to rebuild the training embedding
    # distribution for the distribution check (Projector) — add if not vendored:
    # .add_local_file(...)  # see README (or precompute & bake the tmu/tinv instead)
)

app = modal.App("sutura-align")
volume = modal.Volume.from_name("sutura-jobs", create_if_missing=True)
JOBS = "/jobs"


@app.function(image=image, volumes={JOBS: volume}, timeout=3600, cpu=4.0,
              memory=8192)
def run_job_modal(job_id: str, files: list[str]):
    """Heavy alignment worker (spawned async)."""
    import sys
    sys.path.insert(0, "/root")
    from backend.pipeline import run_alignment
    jd = Path(JOBS) / job_id

    def status(**kw):
        p = jd / "status.json"
        cur = json.loads(p.read_text()) if p.exists() else {}
        cur.update(kw); p.write_text(json.dumps(cur)); volume.commit()

    status(status="running", stage="starting", progress=1)
    try:
        res = run_alignment(files, jd, progress=lambda s, p: status(
            status="running", stage=s, progress=p))
        status(status="done", stage="done", progress=100, result=res)
    except Exception as e:
        status(status="failed", stage="error", error=f"{type(e).__name__}: {e}")


@app.function(image=image, volumes={JOBS: volume})
@modal.asgi_app()
def web():
    import sys
    sys.path.insert(0, "/root")
    from fastapi import FastAPI, UploadFile, File, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, JSONResponse
    from backend.pipeline import qc_file

    api = FastAPI(title="Sutura alignment (Modal)")
    api.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"])

    def sdir(j): return Path(JOBS) / j

    @api.get("/api/health")
    def health(): return {"ok": True, "runtime": "modal"}

    @api.post("/api/align")
    async def align(files: list[UploadFile] = File(...)):
        if len(files) < 2:
            raise HTTPException(400, "upload at least 2 sections")
        job_id = uuid.uuid4().hex[:12]
        jd = sdir(job_id); jd.mkdir(parents=True, exist_ok=True)
        saved = []
        for i, up in enumerate(files):
            if not up.filename.endswith((".h5ad", ".h5")):
                raise HTTPException(400, f"{up.filename}: only .h5ad accepted")
            dest = jd / f"section_{i}_{Path(up.filename).name}"
            dest.write_bytes(await up.read()); saved.append(str(dest))
        for s in saved:
            _, err = qc_file(s)
            if err:
                raise HTTPException(422, f"{Path(s).name}: {err}")
        (jd / "status.json").write_text(json.dumps(
            {"status": "queued", "stage": "queued", "progress": 0}))
        volume.commit()
        run_job_modal.spawn(job_id, saved)
        return {"job_id": job_id, "status": "queued"}

    @api.get("/api/result/{job_id}")
    def result(job_id: str):
        volume.reload()
        p = sdir(job_id) / "status.json"
        if not p.exists(): raise HTTPException(404, "unknown job_id")
        return JSONResponse(json.loads(p.read_text()))

    @api.get("/api/download/{job_id}")
    def download(job_id: str):
        volume.reload()
        out = sdir(job_id) / "aligned.h5ad"
        if not out.exists(): raise HTTPException(404, "not ready")
        return FileResponse(out, filename=f"sutura_aligned_{job_id}.h5ad")

    return api
