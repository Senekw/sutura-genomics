"""Loader & error-handling tests: every failure mode a real user could hit must
produce a helpful message (LoaderError / AlignError), not a stack trace. These
build tiny AnnData files and need neither the engine nor the DLPFC data."""
from __future__ import annotations

import anndata as ad
import numpy as np
import pytest

from sutura_cli.core import tools
from sutura_cli.core.context import Section, WorkContext
from sutura_cli.core.events import ListSink
from sutura_cli.core.tools import (LoaderError, _discover, _ensure_spatial,
                                   _load_one, load_data)


def _adata(n=150, g=20, spatial=True, obs_xy=False, obsm_key=None):
    rng = np.random.RandomState(0)
    a = ad.AnnData(rng.poisson(1.0, size=(n, g)).astype("float32"))
    a.var_names = [f"gene{i}" for i in range(g)]
    a.obs_names = [f"cell{i}" for i in range(n)]
    xy = rng.rand(n, 2).astype("float32") * 100
    if spatial:
        a.obsm["spatial"] = xy
    if obsm_key:
        a.obsm[obsm_key] = xy
    if obs_xy:
        a.obs["x"] = xy[:, 0]
        a.obs["y"] = xy[:, 1]
    return a


# --- _ensure_spatial ------------------------------------------------------ #
def test_ensure_spatial_passthrough():
    a = _adata(spatial=True)
    assert _ensure_spatial(a, "s") is None
    assert a.obsm["spatial"].shape == (150, 2)


def test_ensure_spatial_from_obsm_alias():
    a = _adata(spatial=False, obsm_key="X_spatial")
    note = _ensure_spatial(a, "s")
    assert "X_spatial" in note
    assert a.obsm["spatial"].shape == (150, 2)


def test_ensure_spatial_from_obs_columns():
    a = _adata(spatial=False, obs_xy=True)
    note = _ensure_spatial(a, "s")
    assert "obs['x']" in note and "spatial" in a.obsm


def test_ensure_spatial_missing_raises_actionable():
    a = _adata(spatial=False)
    with pytest.raises(LoaderError) as ei:
        _ensure_spatial(a, "mysection")
    msg = str(ei.value)
    assert "mysection" in msg and "obsm['spatial']" in msg


# --- load_data dir/file flows -------------------------------------------- #
def test_load_data_missing_path(tmp_path):
    ctx = WorkContext(tmp_path / "work")
    with pytest.raises(LoaderError) as ei:
        load_data(ctx, ListSink(), str(tmp_path / "does_not_exist"))
    assert "not found" in str(ei.value).lower()


def test_load_data_empty_dir(tmp_path):
    empty = tmp_path / "empty"; empty.mkdir()
    ctx = WorkContext(tmp_path / "work")
    with pytest.raises(LoaderError) as ei:
        load_data(ctx, ListSink(), str(empty))
    assert "No sections found" in str(ei.value)


def test_load_data_recovers_spatial_from_obs(tmp_path):
    d = tmp_path / "data"; d.mkdir()
    _adata(spatial=False, obs_xy=True).write_h5ad(d / "sec1.h5ad")
    _adata(spatial=False, obs_xy=True).write_h5ad(d / "sec2.h5ad")
    ctx = WorkContext(tmp_path / "work"); sink = ListSink()
    res = load_data(ctx, sink, str(d))
    assert len(res["sections"]) == 2
    notes = " ".join(e.text for e in sink.of_kind("note"))
    assert "built spatial coordinates" in notes


def test_load_data_no_spatial_all_fail(tmp_path):
    d = tmp_path / "data"; d.mkdir()
    _adata(spatial=False).write_h5ad(d / "bad.h5ad")
    ctx = WorkContext(tmp_path / "work")
    with pytest.raises(LoaderError) as ei:
        load_data(ctx, ListSink(), str(d))
    assert "No sections could be loaded" in str(ei.value)


def test_load_data_empty_h5ad(tmp_path):
    d = tmp_path / "data"; d.mkdir()
    ad.AnnData(np.zeros((0, 0), dtype="float32")).write_h5ad(d / "empty.h5ad")
    _adata().write_h5ad(d / "ok.h5ad")
    ctx = WorkContext(tmp_path / "work"); sink = ListSink()
    res = load_data(ctx, sink, str(d))          # one loads, one warns
    assert len(res["sections"]) == 1
    assert any("empty" in w for w in res["warnings"])


# --- align gene-panel guard ---------------------------------------------- #
def _section(ctx, name, genes):
    a = _adata(g=len(genes))
    a.var_names = list(genes)
    p = ctx.workdir / f"{name}.h5ad"; a.write_h5ad(p)
    return ctx.add_section(Section(id=ctx.new_id(), name=name, fmt="h5ad",
                                   h5ad_path=p, source=str(p), adata=a,
                                   n_spots=a.n_obs, n_genes=a.n_vars,
                                   has_spatial=True, has_layers=False))


def test_align_zero_common_genes(tmp_path):
    ctx = WorkContext(tmp_path / "work")
    r = _section(ctx, "A", [f"a{i}" for i in range(20)])
    m = _section(ctx, "B", [f"b{i}" for i in range(20)])
    with pytest.raises(LoaderError) as ei:
        tools.align(ctx, ListSink(), r.id, m.id, out_dir=tmp_path / "out")
    assert "share 0 genes" in str(ei.value)


# --- Space Ranger detection + missing spatial/ --------------------------- #
def test_discover_spaceranger_dir(tmp_path):
    d = tmp_path / "sample"; d.mkdir()
    (d / "filtered_feature_bc_matrix.h5").write_bytes(b"\x00")
    (d / "spatial").mkdir()
    found = _discover(d)
    assert found and found[0][1] == "spaceranger"


def test_discover_nested_h5ad_and_spaceranger(tmp_path):
    _adata().write_h5ad(tmp_path / "a.h5ad")
    sr = tmp_path / "sr"; sr.mkdir()
    (sr / "filtered_feature_bc_matrix.h5").write_bytes(b"\x00")
    (sr / "spatial").mkdir()
    fmts = sorted(f[1] for f in _discover(tmp_path))
    assert "h5ad" in fmts and "spaceranger" in fmts


def test_spaceranger_missing_spatial_dir(tmp_path):
    d = tmp_path / "sample"; d.mkdir()
    (d / "filtered_feature_bc_matrix.h5").write_bytes(b"\x00")
    with pytest.raises(LoaderError) as ei:
        _load_one("spaceranger", d, tmp_path / "work", "sample")
    assert "spatial/" in str(ei.value)


def test_xenium_actionable_error(tmp_path):
    d = tmp_path / "xen"; d.mkdir()
    (d / "cell_feature_matrix.h5").write_bytes(b"\x00")
    (d / "transcripts.parquet").write_bytes(b"\x00")
    assert _discover(d)[0][1] == "xenium"
    with pytest.raises(LoaderError) as ei:
        _load_one("xenium", d, tmp_path / "work", "xen")
    assert "convert" in str(ei.value).lower() and ".h5ad" in str(ei.value)


# --- workflow-level: single section is a clean message, not a crash ------- #
def test_workflow_single_section_message(tmp_path):
    from sutura_cli.core.agent import Session
    from sutura_cli.core.config import Config
    from sutura_cli.core.llm import RuleBackend
    d = tmp_path / "one"; d.mkdir()
    _adata().write_h5ad(d / "only.h5ad")
    cfg = Config(store=tmp_path / "store", backend="rule", cloud_model="",
                 ollama_model="", ollama_host="http://localhost:11434")
    sink = ListSink()
    session = Session(cfg, sink, backend=RuleBackend())
    session.handle(f"align the sections in {d} and reconstruct in 3D")
    msgs = " ".join(e.text for e in sink.of_kind("agent_message"))
    assert "at least 2" in msgs
    assert session.bundle is None          # no job created for a single section
