"""End-to-end harness tests (use the cached PASTE2 base; skip if data/cache absent)."""
import csv

import numpy as np
import pytest

from conftest import requires_dlpfc, requires_cache
from sutura_bench import harness
from sutura_bench.harness import RunConfig, RESULT_FIELDS


@requires_dlpfc
@requires_cache
def test_run_and_reproduce_gate(tmp_path):
    out = tmp_path / "t.csv"
    cfg = RunConfig(datasets=["Br8100"], methods=["paste2", "gate_rigid", "gate_affine"],
                    seeds=[0], severities=[0.0, 4.0], run_tag="t", out_csv=out)
    harness.run(cfg)
    rows = list(csv.DictReader(open(out)))
    ok = [r for r in rows if r["status"] == "ok"]
    assert len(ok) == 6                       # 3 methods x 2 severities
    assert set(rows[0].keys()) == set(RESULT_FIELDS)

    # bit-exact reproduction of the known Br8100 sev-0 gate numbers
    def val(method, sev):
        return float(next(r["median_pitch"] for r in ok
                          if r["method"] == method and float(r["severity"]) == sev))
    assert val("paste2", 0.0) == pytest.approx(2.9866, abs=1e-3)
    assert val("gate_rigid", 0.0) == pytest.approx(1.4611, abs=1e-3)
    assert val("gate_affine", 0.0) == pytest.approx(1.4376, abs=1e-3)
    # the gate never regresses on this realistic base
    assert val("gate_rigid", 4.0) <= val("paste2", 4.0) + 1e-6


@requires_dlpfc
@requires_cache
def test_resume_skips_done_cells(tmp_path):
    out = tmp_path / "r.csv"
    base = dict(datasets=["Br8100"], methods=["paste2"], seeds=[0],
                severities=[0.0], run_tag="r", out_csv=out)
    harness.run(RunConfig(**base))
    n1 = len(list(csv.DictReader(open(out))))
    harness.run(RunConfig(**base))            # resume: should add nothing
    n2 = len(list(csv.DictReader(open(out))))
    assert n1 == n2 == 1


@requires_dlpfc
@requires_cache
def test_identity_worse_than_paste2_under_tear(tmp_path):
    out = tmp_path / "i.csv"
    cfg = RunConfig(datasets=["Br8100"], methods=["identity", "paste2"], seeds=[0],
                    severities=[4.0], run_tag="i", out_csv=out)
    harness.run(cfg)
    ok = [r for r in csv.DictReader(open(out)) if r["status"] == "ok"]
    ident = float(next(r["median_pitch"] for r in ok if r["method"] == "identity"))
    p2 = float(next(r["median_pitch"] for r in ok if r["method"] == "paste2"))
    assert ident > p2                         # doing nothing is worse than aligning
