"""Read result bundles from the shared local store (~/.sutura/results/).

Display-only: this module opens the JSON artifacts the CLI wrote; it never runs
alignment. A bundle is considered complete once metadata.json exists (the CLI
writes it last).
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def default_store() -> Path:
    env = os.environ.get("SUTURA_HOME")
    return Path(env).expanduser() if env else (Path.home() / ".sutura")


def results_dir() -> Path:
    return default_store() / "results"


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def list_runs(results: Path | None = None) -> list[dict]:
    """Summaries of every complete bundle, newest first."""
    results = Path(results) if results else results_dir()
    runs = []
    if not results.is_dir():
        return runs
    for d in results.iterdir():
        meta = d / "metadata.json"
        if not (d.is_dir() and meta.is_file()):
            continue
        m = _read_json(meta)
        if not m:
            continue
        runs.append({
            "job_id": m.get("job_id", d.name),
            "created_utc": m.get("created_utc"),
            "status": m.get("status"),
            "backend": m.get("backend"),
            "n_sections": len(m.get("sections", [])),
            "n_pairs": m.get("n_pairs", len(m.get("pairs", []))),
            "methods": sorted({p.get("method_label", p.get("method", "?"))
                               for p in m.get("pairs", [])}),
            "instruction": m.get("instruction", ""),
        })
    runs.sort(key=lambda r: r.get("created_utc") or "", reverse=True)
    return runs


def load_run(job_id: str, results: Path | None = None) -> dict | None:
    """The full bundle for one job (metadata + all artifacts + report text)."""
    results = Path(results) if results else results_dir()
    d = results / job_id
    meta = _read_json(d / "metadata.json")
    if not meta:
        return None
    art = meta.get("artifacts", {})
    return {
        "metadata": meta,
        "qc": _read_json(d / art.get("qc", "qc.json"), {}),
        "routing": _read_json(d / art.get("routing", "routing.json"), {}),
        "metrics": _read_json(d / art.get("metrics", "metrics.json"), {}),
        "reconstruction": _read_json(
            d / art.get("reconstruction", "reconstruction.json"), {}),
        "report_md": _read_text(d / art.get("report", "report.md")),
        "path": str(d),
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
