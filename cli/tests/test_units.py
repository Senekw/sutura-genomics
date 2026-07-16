"""Fast unit tests that need neither the engine nor the DLPFC data."""
from __future__ import annotations

from sutura_cli.core.llm import (Reply, RuleBackend, ToolRequest,
                                 WorkflowRequest)
from sutura_cli.core.reconstruct import build_pointcloud


def test_rule_backend_align_intent():
    b = RuleBackend()
    d = b.interpret("align the sections in ./my_data and reconstruct in 3D", {})
    assert isinstance(d, WorkflowRequest)
    assert d.name == "align_and_reconstruct"
    assert d.args["path"] == "./my_data"


def test_rule_backend_realign_intent():
    b = RuleBackend()
    d = b.interpret("redo section 3 with PASTE2", {})
    assert isinstance(d, ToolRequest)
    assert d.name == "realign"
    assert d.args["section"] == "3"
    assert d.args["method"] == "paste2"


def test_rule_backend_needs_path():
    b = RuleBackend()
    d = b.interpret("hello", {"sections": []})
    assert isinstance(d, Reply)


def test_reconstruct_stacks_sections():
    pairs = [{
        "ref_name": "A", "mov_name": "B",
        "ref_coords": [[0, 0], [1, 0], [0, 1]],
        "aligned_coords": [[0.1, 0.1], [1.1, 0.1]],
        "ref_layers": ["L1", "L2", "L3"], "mov_layers": ["L1", "L2"],
        "pitch": 2.0, "method": "PASTE2",
    }]
    rec = build_pointcloud(pairs)
    assert rec["n_sections"] == 2
    assert rec["n_points"] == 5           # 3 ref + 2 moving
    assert rec["z_spacing"] == 2.0
    assert rec["sections"][0]["z"] == 0.0
    assert rec["sections"][1]["z"] == 2.0
    # every point carries [x, y, z, section_index, layer]
    assert all(len(p) == 5 for p in rec["points"])
