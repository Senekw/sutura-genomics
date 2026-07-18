"""Dataset registry tests."""
from sutura_bench import datasets


def test_registry_nonempty_and_unique_ids():
    specs = datasets.all_specs()
    assert len(specs) >= 8
    ids = [s.id for s in specs]
    assert len(ids) == len(set(ids)), "duplicate dataset ids"


def test_regime_and_gt_consistency():
    for s in datasets.all_specs():
        assert s.regime in ("real_serial", "self_warp")
        assert s.gt in ("array_bridge", "self_warp")
        # self_warp datasets align a section to itself
        if s.regime == "self_warp":
            assert s.ref == s.mov and s.degenerate
        else:
            assert not s.degenerate


def test_default_suite_excludes_self_warp():
    suite = datasets.default_suite()
    assert suite, "no real-serial datasets available"
    assert all(s.regime == "real_serial" for s in suite)
    assert all(not s.degenerate for s in suite)


def test_dlpfc_donors_present():
    dlpfc = {s.id for s in datasets.available_specs(group="dlpfc")}
    # the three first-pair donors are the LODO backbone
    for d in ("Br5292", "Br5595", "Br8100"):
        assert d in dlpfc


def test_get_unknown_raises():
    import pytest
    with pytest.raises(KeyError):
        datasets.get("nope")


def test_catalogue_builds():
    cat = datasets.catalogue(refresh=True)
    assert isinstance(cat, list) and cat
    by_id = {c["id"]: c for c in cat}
    # every available dataset gets measured spot counts
    for c in cat:
        if c.get("available"):
            assert c["n_spots_ref"] > 0
            assert c["has_array_grid"] is True
