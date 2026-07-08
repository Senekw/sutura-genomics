"""
FastAPI backend for suturagenomics.bio (async alignment jobs).

Endpoints:
  POST /api/align            upload >=2 .h5ad sections -> validate -> {job_id}
  GET  /api/result/{job_id}  status (queued|running|done|failed) + result
  GET  /api/download/{job_id} aligned .h5ad output
  GET  /api/health

The upload returns immediately; the alignment (minutes) runs in a background worker
thread. Jobs and files live under SUTURA_JOBS_DIR (default backend/_jobs).

Run locally:  uvicorn backend.app:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import json
import os
import shutil
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from backend.pipeline import run_alignment, qc_file

JOBS_DIR = Path(os.environ.get("SUTURA_JOBS_DIR", Path(__file__).resolve().parent / "_jobs"))
JOBS_DIR.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_MB = 400
_executor = ThreadPoolExecutor(max_workers=1)   # one heavy alignment at a time

app = FastAPI(title="Sutura Genomics alignment API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to https://suturagenomics.bio in production
    allow_methods=["*"], allow_headers=["*"],
)


def _job_dir(job_id): return JOBS_DIR / job_id
def _status_path(job_id): return _job_dir(job_id) / "status.json"


def _write_status(job_id, **kw):
    p = _status_path(job_id)
    cur = json.loads(p.read_text()) if p.exists() else {}
    cur.update(kw)
    p.write_text(json.dumps(cur))
    return cur


def _read_status(job_id):
    p = _status_path(job_id)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def _run_job(job_id, files):
    _write_status(job_id, status="running", stage="starting", progress=1)
    try:
        def progress(stage, pct):
            _write_status(job_id, status="running", stage=stage, progress=pct)
        result = run_alignment(files, _job_dir(job_id), progress=progress)
        _write_status(job_id, status="done", stage="done", progress=100, result=result)
    except Exception as e:
        _write_status(job_id, status="failed", stage="error", progress=0,
                      error=f"{type(e).__name__}: {e}",
                      traceback=traceback.format_exc()[-2000:])


@app.get("/api/health")
def health():
    return {"ok": True, "service": "sutura-align", "jobs_dir": str(JOBS_DIR)}


@app.post("/api/align")
async def align(files: list[UploadFile] = File(...)):
    if len(files) < 2:
        raise HTTPException(400, "Upload at least 2 sections: a reference and a "
                                 "moving slice (extra sections are used for adaptation).")
    job_id = uuid.uuid4().hex[:12]
    jd = _job_dir(job_id); jd.mkdir(parents=True, exist_ok=True)
    saved = []
    for i, up in enumerate(files):
        if not up.filename.endswith((".h5ad", ".h5")):
            shutil.rmtree(jd, ignore_errors=True)
            raise HTTPException(400, f"{up.filename}: only .h5ad Visium files are accepted.")
        dest = jd / f"section_{i}_{Path(up.filename).name}"
        with open(dest, "wb") as fh:
            data = await up.read()
            if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
                shutil.rmtree(jd, ignore_errors=True)
                raise HTTPException(413, f"{up.filename}: exceeds {MAX_UPLOAD_MB} MB.")
            fh.write(data)
        saved.append(dest)

    # fast synchronous validation so bad files are rejected before queuing a job
    for s in saved:
        _, err = qc_file(s)
        if err:
            shutil.rmtree(jd, ignore_errors=True)
            raise HTTPException(422, f"{s.name}: {err}")

    _write_status(job_id, status="queued", stage="queued", progress=0,
                  n_files=len(saved), filenames=[f.filename for f in files])
    _executor.submit(_run_job, job_id, [str(s) for s in saved])
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/result/{job_id}")
def result(job_id: str):
    st = _read_status(job_id)
    if st is None:
        raise HTTPException(404, "unknown job_id")
    return JSONResponse(st)


@app.get("/api/download/{job_id}")
def download(job_id: str):
    st = _read_status(job_id)
    if st is None:
        raise HTTPException(404, "unknown job_id")
    if st.get("status") != "done":
        raise HTTPException(409, f"job not finished (status={st.get('status')})")
    out = _job_dir(job_id) / "aligned.h5ad"
    if not out.exists():
        raise HTTPException(404, "aligned output not found")
    return FileResponse(out, media_type="application/octet-stream",
                        filename=f"sutura_aligned_{job_id}.h5ad")
