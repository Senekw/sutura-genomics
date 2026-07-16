"""Result bundle: the structured, local, on-disk hand-off from the CLI to the
viewer app. Written to  <store>/results/<job_id>/ .  See docs/BUNDLE_SCHEMA.md
for the full contract; SCHEMA_VERSION (in sutura_cli/__init__.py) gates it.

Layout:
    <job_id>/
        metadata.json         manifest: job, status, engine, inputs, sections, pairs
        qc.json               per-section input QC
        routing.json          per-pair distribution-check + routing decision
        metrics.json          per-pair method used + metric/score (honest labels)
        reconstruction.json   3D serial-section point cloud
        report.md             human-readable summary
        alignment/
            pair_00__<ref>__to__<mov>/aligned.h5ad   (from the engine)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .. import SCHEMA_VERSION, __version__


def new_job_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"job-{stamp}-{uuid4().hex[:6]}"


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(s)).strip("-")[:48] or "section"


@dataclass
class Bundle:
    job_id: str
    root: Path                       # <store>/results/<job_id>
    backend: str = "rule"
    engine: dict = field(default_factory=dict)
    status: str = "running"          # running | complete | failed
    instruction: str = ""
    inputs: list[dict] = field(default_factory=list)
    sections: list[dict] = field(default_factory=list)
    qc: list[dict] = field(default_factory=list)
    routing: list[dict] = field(default_factory=list)
    pairs: list[dict] = field(default_factory=list)
    reconstruction: dict = field(default_factory=dict)
    report_md: str = ""
    warnings: list[str] = field(default_factory=list)
    created: str = field(default_factory=lambda: datetime.now(timezone.utc)
                         .isoformat(timespec="seconds"))

    @classmethod
    def create(cls, results_dir: Path, backend: str, engine: dict,
               instruction: str) -> "Bundle":
        jid = new_job_id()
        root = Path(results_dir) / jid
        (root / "alignment").mkdir(parents=True, exist_ok=True)
        return cls(job_id=jid, root=root, backend=backend, engine=engine,
                   instruction=instruction)

    # --- accumulation ---------------------------------------------------- #
    def pair_dir(self, index: int, ref_name: str, mov_name: str) -> Path:
        d = self.root / "alignment" / \
            f"pair_{index:02d}__{_slug(ref_name)}__to__{_slug(mov_name)}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def add_pair(self, record: dict) -> None:
        # de-duplicate on pair index (a rerun replaces the prior record)
        self.pairs = [p for p in self.pairs if p.get("index") != record.get("index")]
        self.pairs.append(record)
        self.pairs.sort(key=lambda p: p.get("index", 0))

    # --- persistence ----------------------------------------------------- #
    def _write_json(self, name: str, obj: Any) -> None:
        (self.root / name).write_text(
            json.dumps(obj, indent=2, default=str), encoding="utf-8")

    def manifest(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "sutura_version": __version__,
            "job_id": self.job_id,
            "created_utc": self.created,
            "status": self.status,
            "backend": self.backend,
            "engine": self.engine,
            "instruction": self.instruction,
            "inputs": self.inputs,
            "sections": self.sections,
            "n_pairs": len(self.pairs),
            "pairs": [
                {k: p.get(k) for k in
                 ("index", "ref", "mov", "method", "method_label",
                  "metric", "score", "has_ground_truth", "aligned_file")}
                for p in self.pairs
            ],
            "artifacts": {
                "qc": "qc.json",
                "routing": "routing.json",
                "metrics": "metrics.json",
                "reconstruction": "reconstruction.json",
                "report": "report.md",
            },
            "warnings": self.warnings,
        }

    def write(self) -> Path:
        self._write_json("qc.json", {"schema_version": SCHEMA_VERSION,
                                     "sections": self.qc})
        self._write_json("routing.json", {"schema_version": SCHEMA_VERSION,
                                          "pairs": self.routing})
        self._write_json("metrics.json", {"schema_version": SCHEMA_VERSION,
                                          "pairs": self.pairs})
        self._write_json("reconstruction.json", self.reconstruction or
                         {"schema_version": SCHEMA_VERSION, "n_points": 0})
        if self.report_md:
            (self.root / "report.md").write_text(self.report_md, encoding="utf-8")
        # manifest last, so its presence signals a fully written bundle
        self._write_json("metadata.json", self.manifest())
        return self.root

    def summary(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "n_sections": len(self.sections),
            "n_pairs": len(self.pairs),
            "methods": sorted({p.get("method_label", p.get("method", "?"))
                               for p in self.pairs}),
            "path": str(self.root),
        }
