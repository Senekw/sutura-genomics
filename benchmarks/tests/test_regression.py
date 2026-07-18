"""Regression-detection tests (synthetic CSVs; no data/torch needed)."""
import csv

import pytest

from sutura_bench import regression


def _write_csv(path, rows):
    fields = ["run_tag", "timestamp", "dataset", "group", "regime", "degenerate",
              "tissue", "method", "kind", "severity", "seed", "median_pitch",
              "mean_pitch", "p90_pitch", "p95_pitch", "median_px", "n", "pitch_px",
              "bridge_coverage", "base_err_pitch", "beats_base", "seconds",
              "status", "detail"]
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({**{k: "" for k in fields}, **r})


def _cell(dataset, method, sev, seed, err, regime="real_serial"):
    return dict(dataset=dataset, method=method, regime=regime, group="dlpfc",
                severity=sev, seed=seed, median_pitch=err, mean_pitch=err,
                p90_pitch=err, status="ok")


def test_save_and_selfcheck_passes(tmp_path):
    csv_path = tmp_path / "base.csv"
    _write_csv(csv_path, [
        _cell("Br5292", "paste2", 0.0, 0, 5.3),
        _cell("Br5292", "gate_rigid", 0.0, 0, 4.4),
        _cell("Br5595", "paste2", 0.0, 0, 4.3),
    ])
    ref = regression.save_reference(csv_path, out_json=tmp_path / "ref.json")
    rep = regression.check(csv_path, ref_json=ref)
    assert rep["passed"]
    assert rep["n_matched"] == 3
    assert not rep["regressions"]


def test_detects_regression(tmp_path):
    ref_csv = tmp_path / "ref.csv"
    _write_csv(ref_csv, [_cell("Br5292", "gate_rigid", 0.0, 0, 4.0)])
    ref = regression.save_reference(ref_csv, out_json=tmp_path / "ref.json")

    worse = tmp_path / "worse.csv"
    _write_csv(worse, [_cell("Br5292", "gate_rigid", 0.0, 0, 4.5)])   # +0.5, +12.5%
    rep = regression.check(worse, ref_json=ref)
    assert not rep["passed"]
    assert len(rep["regressions"]) == 1
    assert rep["regressions"][0]["delta"] == pytest.approx(0.5)


def test_within_tolerance_not_flagged(tmp_path):
    ref_csv = tmp_path / "ref.csv"
    _write_csv(ref_csv, [_cell("Br5292", "gate_affine", 0.0, 0, 3.076)])
    ref = regression.save_reference(ref_csv, out_json=tmp_path / "ref.json")

    jitter = tmp_path / "j.csv"
    _write_csv(jitter, [_cell("Br5292", "gate_affine", 0.0, 0, 3.077)])   # +0.001
    rep = regression.check(jitter, ref_json=ref)
    assert rep["passed"]
    assert rep["n_unchanged"] == 1


def test_detects_improvement(tmp_path):
    ref_csv = tmp_path / "ref.csv"
    _write_csv(ref_csv, [_cell("Br5292", "gate_affine", 0.0, 0, 4.0)])
    ref = regression.save_reference(ref_csv, out_json=tmp_path / "ref.json")

    better = tmp_path / "b.csv"
    _write_csv(better, [_cell("Br5292", "gate_affine", 0.0, 0, 3.0)])   # -1.0
    rep = regression.check(better, ref_json=ref)
    assert rep["passed"]                       # improvements never fail the check
    assert len(rep["improvements"]) == 1


def test_missing_reference_raises(tmp_path):
    csv_path = tmp_path / "x.csv"
    _write_csv(csv_path, [_cell("Br5292", "paste2", 0.0, 0, 5.0)])
    with pytest.raises(FileNotFoundError):
        regression.check(csv_path, ref_json=tmp_path / "absent.json")
