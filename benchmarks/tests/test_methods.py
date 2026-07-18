"""Method registry tests (interface-level; heavy inference covered in harness test)."""
import numpy as np
import pytest

from sutura_bench import methods


def test_standard_methods_registered():
    names = methods.names()
    for m in ("identity", "paste2", "gate_rigid", "gate_affine", "gate_quad", "sutura"):
        assert m in names


def test_method_metadata():
    for m in methods.all_methods():
        assert m.kind in ("aligner", "refiner")
        assert callable(m.run)
        # every refiner consumes the shared base
        if m.kind == "refiner":
            assert m.requires_base
    # gates need a base; identity and sutura do not
    assert methods.get("gate_rigid").requires_base
    assert not methods.get("identity").requires_base
    assert not methods.get("sutura").requires_base
    assert methods.get("paste2").requires_base


def test_identity_returns_moving_coords():
    class FakeTask:
        moving_coords = np.arange(20, dtype=float).reshape(10, 2)
        base = None
    out = methods.get("identity").run(FakeTask())
    assert np.allclose(out, FakeTask.moving_coords)


def test_register_rejects_duplicate():
    with pytest.raises(ValueError):
        methods.register(methods.get("paste2"))


def test_get_unknown_raises():
    with pytest.raises(KeyError):
        methods.get("nope")
