"""Tests for the Sutura viewer app: reading bundles, the JSON API, and the
grounded chatbot. Hermetic - builds its own minimal bundle, no engine needed."""
from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from sutura_app import chat, server, store


def _make_bundle(root: Path, job_id="job-test-000000", off_dist=False):
    d = root / "results" / job_id
    (d / "alignment").mkdir(parents=True)
    if off_dist:
        pair = {"index": 0, "ref": "A", "mov": "B", "method": "paste2",
                "method_label": "PASTE2", "reason": "off-distribution ...; auto-adapt ran; kept the best",
                "metric": "median_error_pitch", "score": 2.82, "has_ground_truth": True,
                "in_distribution": False, "mahalanobis": 4.77, "gene_overlap": 1.0,
                "candidates": [["auto_adapt_epochs", 30], ["sutura_zeroshot", 9.53],
                               ["sutura_adapted", 8.03], ["paste2", 2.82]],
                "post_qc": {"verdict": "pass"}, "aligned_file": "alignment/x/aligned.h5ad"}
    else:
        pair = {"index": 0, "ref": "A", "mov": "B", "method": "sutura",
                "method_label": "Sutura", "reason": "in-distribution (Mahalanobis 0.85 < 2.5)",
                "metric": "median_error_pitch", "score": 1.29, "has_ground_truth": True,
                "in_distribution": True, "mahalanobis": 0.85, "gene_overlap": 1.0,
                "candidates": [["sutura", 1.29]], "post_qc": {"verdict": "pass"},
                "aligned_file": "alignment/x/aligned.h5ad"}
    meta = {"schema_version": "1.0", "job_id": job_id, "created_utc": "2026-07-16T01:00:00+00:00",
            "status": "complete", "backend": "rule", "instruction": "align ...",
            "sections": [{"name": "A", "n_spots": 100, "n_genes": 50, "has_layers": True},
                         {"name": "B", "n_spots": 110, "n_genes": 50, "has_layers": True}],
            "n_pairs": 1, "pairs": [pair],
            "artifacts": {"qc": "qc.json", "routing": "routing.json",
                          "metrics": "metrics.json", "reconstruction": "reconstruction.json",
                          "report": "report.md"}, "warnings": []}
    (d / "metadata.json").write_text(json.dumps(meta))
    (d / "metrics.json").write_text(json.dumps({"schema_version": "1.0", "pairs": [pair]}))
    (d / "routing.json").write_text(json.dumps({"pairs": [{"routed_method": "Sutura"}]}))
    (d / "qc.json").write_text(json.dumps({"sections": [
        {"name": "A", "pass": True, "n_spots": 100, "n_genes": 50, "has_layers": True, "issue": None}]}))
    (d / "reconstruction.json").write_text(json.dumps({
        "kind": "serial_section_zstack", "composition": "exact_single_reference",
        "n_sections": 2, "n_points": 3, "z_spacing": 1.0, "global_frame": "A",
        "sections": [{"index": 0, "name": "A", "z": 0.0, "method": "reference"},
                     {"index": 1, "name": "B", "z": 1.0, "method": "Sutura"}],
        "point_fields": ["x", "y", "z", "section_index", "layer"],
        "points": [[0, 0, 0, 0, "Layer1"], [1, 0, 0, 0, "Layer2"], [0, 0, 1, 1, "Layer1"]]}))
    (d / "report.md").write_text("# report\nMethod: Sutura\n")
    return meta


# --- store ---------------------------------------------------------------- #
def test_store_lists_and_loads(tmp_path):
    _make_bundle(tmp_path)
    runs = store.list_runs(tmp_path / "results")
    assert len(runs) == 1 and runs[0]["job_id"] == "job-test-000000"
    run = store.load_run("job-test-000000", tmp_path / "results")
    assert run["metadata"]["status"] == "complete"
    assert run["reconstruction"]["n_sections"] == 2
    assert run["report_md"].startswith("# report")


def test_store_ignores_incomplete(tmp_path):
    (tmp_path / "results" / "job-x").mkdir(parents=True)   # no metadata.json
    assert store.list_runs(tmp_path / "results") == []


# --- chat (grounded, honest) --------------------------------------------- #
def test_chat_reports_method(tmp_path):
    _make_bundle(tmp_path)
    run = store.load_run("job-test-000000", tmp_path / "results")
    a = chat.answer(run, "which method did you use?", use_ollama=False)
    assert "Sutura" in a["text"]


def test_chat_compare_in_distribution_is_honest(tmp_path):
    _make_bundle(tmp_path)                       # in-dist: only Sutura ran
    run = store.load_run("job-test-000000", tmp_path / "results")
    a = chat.answer(run, "how does PASTE2 compare?", use_ollama=False)
    assert "only Sutura" in a["text"] and "CLI" in a["text"]   # doesn't fabricate


def test_chat_compare_off_distribution_uses_candidates(tmp_path):
    _make_bundle(tmp_path, off_dist=True)
    run = store.load_run("job-test-000000", tmp_path / "results")
    a = chat.answer(run, "compare the methods", use_ollama=False)
    assert "PASTE2 2.82" in a["text"] and "kept" in a["text"]
    assert "Sutura (auto-adapted) 8.03" in a["text"]


def test_chat_refuses_to_rerun(tmp_path):
    _make_bundle(tmp_path)
    run = store.load_run("job-test-000000", tmp_path / "results")
    a = chat.answer(run, "re-run the alignment with paste2", use_ollama=False)
    assert "doesn't run alignment" in a["text"]


# --- server API ----------------------------------------------------------- #
@pytest.fixture
def running_server(tmp_path, monkeypatch):
    _make_bundle(tmp_path)
    monkeypatch.setenv("SUTURA_HOME", str(tmp_path))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read()


def test_api_runs(running_server):
    status, body = _get(running_server + "/api/runs")
    data = json.loads(body)
    assert status == 200 and len(data["runs"]) == 1


def test_api_run_detail(running_server):
    status, body = _get(running_server + "/api/runs/job-test-000000")
    data = json.loads(body)
    assert data["metadata"]["job_id"] == "job-test-000000"
    assert data["reconstruction"]["n_points"] == 3


def test_api_index_and_assets(running_server):
    for path in ("/", "/app.js", "/styles.css", "/vendor/three.module.min.js"):
        status, body = _get(running_server + path)
        assert status == 200 and body, f"{path} not served"


def test_api_chat(running_server):
    req = urllib.request.Request(
        running_server + "/api/chat", method="POST",
        data=json.dumps({"job_id": "job-test-000000",
                         "question": "which method?"}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        data = json.loads(r.read())
    assert "Sutura" in data["text"]
