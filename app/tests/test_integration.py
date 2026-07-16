"""End-to-end integration: the Sutura CLI aligns real data and writes a bundle,
then the viewer app reads and displays it correctly. Proves the full product loop
CLI -> bundle -> app on one machine.

Needs both packages (sutura_cli + sutura_app) and the alignment engine + DLPFC
data; auto-skips otherwise. Slow (runs a real alignment)."""
from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

# the CLI (producer) and the app (consumer) must both be importable
cli = pytest.importorskip("sutura_cli")
from sutura_app import chat, server, store          # noqa: E402


def _repo():
    try:
        from sutura_cli.core import engine
        return engine.find_repo_root()
    except Exception:
        return None


REPO = _repo()
DLPFC = [REPO / "data" / f"DLPFC_{s}.h5ad" for s in ("151507", "151508")] if REPO else []
HAVE = bool(REPO) and all(p.is_file() for p in DLPFC)

pytestmark = pytest.mark.skipif(not HAVE, reason="engine / DLPFC data unavailable")


def _cli_produce_bundle(store_root: Path, data_dir: Path):
    """Drive the CLI headlessly to align real data and write a bundle."""
    from sutura_cli.core.agent import Session
    from sutura_cli.core.config import Config
    from sutura_cli.core.events import ListSink
    from sutura_cli.core.llm import RuleBackend
    cfg = Config(store=store_root, backend="rule", cloud_model="",
                 ollama_model="", ollama_host="http://localhost:11434")
    session = Session(cfg, ListSink(), backend=RuleBackend())
    bundle = session.handle(f"align the sections in {data_dir} and reconstruct in 3D")
    return bundle


def test_cli_bundle_is_read_and_displayed_by_app(tmp_path):
    # 1. CLI aligns real DLPFC sections and writes a bundle
    data_dir = tmp_path / "data"; data_dir.mkdir()
    for p in DLPFC:
        (data_dir / p.name).write_bytes(p.read_bytes())
    store_root = tmp_path / "sutura_home"
    bundle = _cli_produce_bundle(store_root, data_dir)
    assert bundle is not None and bundle.status == "complete"
    job_id = bundle.job_id
    results = store_root / "results"

    # 2. the APP's store layer lists and loads the CLI-produced bundle
    runs = store.list_runs(results)
    assert any(r["job_id"] == job_id for r in runs), "app did not list the CLI run"
    run = store.load_run(job_id, results)
    assert run is not None

    # 3. what the app displays matches what the CLI wrote
    cli_pair = bundle.pairs[0]
    app_pair = run["metrics"]["pairs"][0]
    assert app_pair["method_label"] == cli_pair["method_label"]
    assert app_pair["score"] == cli_pair["score"]
    rec = run["reconstruction"]
    assert rec["n_sections"] == 2 and rec["n_points"] > 0
    assert rec["point_fields"] == ["x", "y", "z", "section_index", "layer"]
    # the aligned .h5ad the CLI wrote is referenced and present
    assert (Path(run["path"]) / app_pair["aligned_file"]).is_file()

    # 4. the app's HTTP API serves the same run (as the browser would fetch it)
    import os
    os.environ["SUTURA_HOME"] = str(store_root)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True); t.start()
    try:
        listing = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/runs", timeout=5).read())
        assert any(r["job_id"] == job_id for r in listing["runs"])
        detail = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/runs/{job_id}", timeout=5).read())
        assert detail["metadata"]["job_id"] == job_id
        assert detail["reconstruction"]["n_points"] == rec["n_points"]
    finally:
        httpd.shutdown()

    # 5. the chatbot answers about the real run, honestly naming the method
    ans = chat.answer(run, "which method did you use and why?", use_ollama=False)
    assert cli_pair["method_label"] in ans["text"]
