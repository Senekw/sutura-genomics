"""End-to-end test: drive the agent loop headlessly on the DLPFC demo pair with
the offline rule backend, and assert a valid result bundle is written.

This needs the alignment engine (repo src/ + checkpoints) and its heavy deps
(scanpy / torch / paste2). It is skipped automatically if the DLPFC data or the
engine are not present.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sutura_cli import SCHEMA_VERSION
from sutura_cli.core import engine
from sutura_cli.core.config import Config
from sutura_cli.core.agent import Session
from sutura_cli.core.events import BundleWritten, ListSink
from sutura_cli.core.llm import RuleBackend


def _repo():
    try:
        return engine.find_repo_root()
    except Exception:
        return None


REPO = _repo()
DLPFC = [REPO / "data" / f"DLPFC_{s}.h5ad" for s in ("151507", "151508")] if REPO else []
HAVE_DATA = bool(REPO) and all(p.is_file() for p in DLPFC)

pytestmark = pytest.mark.skipif(
    not HAVE_DATA, reason="DLPFC data / alignment engine not available")


def _config(tmp_path) -> Config:
    return Config(store=tmp_path, backend="rule", cloud_model="", ollama_model="",
                  ollama_host="http://localhost:11434")


def test_full_loop_writes_valid_bundle(tmp_path):
    # stage the two DLPFC sections in an isolated input dir
    data_dir = tmp_path / "input"
    data_dir.mkdir()
    for p in DLPFC:
        (data_dir / p.name).write_bytes(p.read_bytes())

    sink = ListSink()
    session = Session(_config(tmp_path), sink, backend=RuleBackend())
    bundle = session.handle(
        f"align the sections in {data_dir} and reconstruct in 3D")

    # a bundle was produced and announced
    assert bundle is not None
    assert bundle.status == "complete"
    assert sink.of_kind("bundle_written"), "no BundleWritten event emitted"
    written = sink.of_kind("bundle_written")[0]
    assert isinstance(written, BundleWritten)
    root = Path(written.path)

    # required artifacts exist
    for name in ("metadata.json", "qc.json", "routing.json", "metrics.json",
                 "reconstruction.json", "report.md"):
        assert (root / name).is_file(), f"missing {name}"

    meta = json.loads((root / "metadata.json").read_text())
    assert meta["schema_version"] == SCHEMA_VERSION
    assert meta["status"] == "complete"
    assert len(meta["sections"]) == 2
    assert meta["n_pairs"] == 1

    # the one pair records an honest method label + an aligned .h5ad on disk
    pair = meta["pairs"][0]
    assert pair["method_label"] in {"Sutura", "Sutura (auto-adapted to your data)",
                                    "Sutura (zero-shot)", "PASTE2",
                                    "Sutura (graph model)"}
    assert (root / pair["aligned_file"]).is_file()

    # aligned h5ad carries the aligned coordinates
    import anndata as ad
    aligned = ad.read_h5ad(root / pair["aligned_file"])
    assert "spatial_aligned" in aligned.obsm

    # reconstruction stacked both sections into a 3D point cloud
    rec = json.loads((root / "reconstruction.json").read_text())
    assert rec["n_sections"] == 2
    assert rec["n_points"] > 0
    assert rec["point_fields"] == ["x", "y", "z", "section_index", "layer"]


def test_followup_realign_updates_bundle(tmp_path):
    data_dir = tmp_path / "input"
    data_dir.mkdir()
    for p in DLPFC:
        (data_dir / p.name).write_bytes(p.read_bytes())

    sink = ListSink()
    session = Session(_config(tmp_path), sink, backend=RuleBackend())
    session.handle(f"align the sections in {data_dir} and reconstruct in 3D")

    bundle = session.handle("redo section 2 with paste2")
    assert bundle.pairs[0]["method"] == "paste2"
    assert bundle.pairs[0]["method_label"] == "PASTE2"
    meta = json.loads((bundle.root / "metadata.json").read_text())
    assert meta["pairs"][0]["method_label"] == "PASTE2"
