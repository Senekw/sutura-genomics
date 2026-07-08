"""
End-to-end test of the Sutura backend against a running server: uploads a real
.h5ad pair, polls until done, prints the result, downloads the aligned output.

Usage (server must be running, e.g. uvicorn backend.app:app --port 8000):
  python backend/test_e2e.py --ref data/DLPFC_151669.h5ad --mov data/DLPFC_151670.h5ad
  python backend/test_e2e.py --url http://localhost:8000 --ref ... --mov ... [--extra ...]
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import requests


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--ref", required=True)
    p.add_argument("--mov", required=True)
    p.add_argument("--extra", nargs="*", default=[])
    p.add_argument("--timeout", type=int, default=1800)
    args = p.parse_args()

    print(f"health: {requests.get(args.url + '/api/health').json()}")
    files = [("files", (Path(f).name, open(f, "rb"), "application/octet-stream"))
             for f in [args.ref, args.mov, *args.extra]]
    r = requests.post(args.url + "/api/align", files=files)
    if r.status_code != 200:
        print(f"UPLOAD REJECTED [{r.status_code}]: {r.json()}"); return
    job_id = r.json()["job_id"]
    print(f"job_id={job_id}")

    t0 = time.time(); last = None
    while time.time() - t0 < args.timeout:
        st = requests.get(f"{args.url}/api/result/{job_id}").json()
        tag = f"{st['status']}/{st.get('stage')} {st.get('progress')}%"
        if tag != last:
            print(f"  [{time.time()-t0:5.0f}s] {tag}"); last = tag
        if st["status"] in ("done", "failed"):
            break
        time.sleep(3)

    if st["status"] == "failed":
        print(f"FAILED: {st.get('error')}"); return
    res = st["result"]
    print("\n=== RESULT ===")
    for k in ["method", "method_label", "in_distribution", "in_dist_confidence",
              "mahalanobis", "gene_overlap", "metric", "score", "has_ground_truth",
              "retry", "candidates", "runtime_seconds"]:
        print(f"  {k}: {res.get(k)}")
    print(f"  reason: {res.get('reason')}")

    out = Path("backend/_e2e_download.h5ad")
    dl = requests.get(f"{args.url}/api/download/{job_id}")
    out.write_bytes(dl.content)
    print(f"\ndownloaded aligned output -> {out} ({len(dl.content)/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
