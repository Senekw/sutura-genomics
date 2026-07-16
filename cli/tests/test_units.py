"""Fast unit tests that need neither the engine nor the DLPFC data."""
from __future__ import annotations

import pytest

from sutura_cli.core.llm import (Reply, RuleBackend, ToolRequest,
                                 WorkflowRequest, _JSONLLMBackend, _canon_tool,
                                 _norm_method)
from sutura_cli.core.reconstruct import build_pointcloud

_STATE = {"sections": [{"id": "s1", "name": "A"}, {"id": "s2", "name": "B"}]}


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


@pytest.mark.parametrize("text,tool", [
    ("show me the metrics", "metrics"),
    ("how well did it align?", "metrics"),
    ("what were the alignment errors?", "metrics"),
    ("which section aligned worst?", "worst"),
    ("what was the best pair?", "worst"),
    ("explain the routing decision", "explain_routing"),
    ("why did it pick that method?", "explain_routing"),
    ("which method did you use, and why?", "explain_routing"),
    ("what method did you use?", "explain_routing"),
    ("regenerate the report", "report"),
])
def test_rule_backend_query_intents(text, tool):
    d = RuleBackend().interpret(text, _STATE)
    assert isinstance(d, ToolRequest) and d.name == tool


def test_rule_backend_explain_routing_section():
    d = RuleBackend().interpret("explain routing for section 2", _STATE)
    assert isinstance(d, ToolRequest) and d.name == "explain_routing"
    assert d.args["section"] == "2"


def test_rule_backend_no_accidental_rerun():
    # an unrecognised remark must NOT silently trigger a full alignment re-run
    d = RuleBackend().interpret("thanks, that's great", _STATE)
    assert isinstance(d, Reply)


def test_norm_method_variants():
    assert _norm_method("PASTE2") == "paste2"
    assert _norm_method("pase2") == "paste2"
    assert _norm_method("paste-2") == "paste2"
    assert _norm_method("the graph model") == "sutura"
    assert _norm_method("banana") is None


def test_canon_tool_aliases():
    assert _canon_tool("redo_section") == "realign"
    assert _canon_tool("show_worst") == "worst"
    assert _canon_tool("generate_report") == "report"
    assert _canon_tool("why") == "explain_routing"
    assert _canon_tool("totally_made_up") is None


def test_finalize_offvocab_falls_back_to_rule():
    # a weak model emits an out-of-vocabulary tool; _finalize must recover via rules
    b = _JSONLLMBackend()
    bogus = ToolRequest("redo_section", {"section": "2", "method": "PASE2"})
    d = b._finalize(bogus, "redo section 2 with paste2", _STATE)
    assert isinstance(d, ToolRequest) and d.name == "realign"
    assert d.args.get("method") == "paste2"


def test_finalize_type_conflict_prefers_rule():
    # model wrongly turns "switch section 1..." into a full workflow; rules win
    b = _JSONLLMBackend()
    wrong = WorkflowRequest("align_and_reconstruct", {})
    d = b._finalize(wrong, "switch section 1 to the graph model", _STATE)
    assert isinstance(d, ToolRequest) and d.name == "realign"
    assert d.args.get("method") == "sutura"


def test_report_candidate_breakdown_off_distribution():
    from sutura_cli.core.reporting import _candidate_lines
    # a real off-distribution record (Br8100): auto-adapt ran, PASTE2 kept
    p = {"has_ground_truth": True,
         "candidates": [["auto_adapt_epochs", 30], ["sutura_zeroshot", 9.53],
                        ["sutura_adapted", 8.03], ["paste2", 2.82]]}
    lines = "\n".join(_candidate_lines(p))
    assert "auto-adapt" in lines and "30 epochs" in lines
    assert "Sutura (auto-adapted): 8.03" in lines
    assert "PASTE2: 2.82" in lines and "<- kept" in lines
    # the kept marker is on PASTE2 (lowest error), not on Sutura
    assert "PASTE2: 2.82 spot-pitch error  <- kept" in lines


def test_report_no_candidate_breakdown_for_single_method():
    from sutura_cli.core.reporting import _candidate_lines
    assert _candidate_lines({"has_ground_truth": True,
                             "candidates": [["sutura", 1.29]]}) == []


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
    assert rec["composition"] == "exact_single_reference"   # 2 sections = exact
    # every point carries [x, y, z, section_index, layer]
    assert all(len(p) == 5 for p in rec["points"])


def _sim(angle_deg, scale, tx, ty):
    import numpy as np
    a = np.deg2rad(angle_deg)
    R = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]]) * scale
    return lambda P: (np.asarray(P, float) @ R.T) + np.array([tx, ty])


def test_reconstruct_chain_composes_to_global_frame():
    """A 3-section chain: section 2 is aligned into section 1's frame, which is
    itself rotated/translated from section 0. Composition must land section 2 in
    section 0's (global) frame."""
    import numpy as np
    rng = np.random.RandomState(1)
    s0 = rng.rand(30, 2) * 100                      # frame 0 (global)
    s1_orig = rng.rand(25, 2) * 100                 # section 1 in its own frame
    s2_orig = rng.rand(20, 2) * 100                 # section 2 in its own frame
    S10 = _sim(30, 1.0, 12, -5)                     # frame1 -> frame0
    S21 = _sim(-15, 1.0, -8, 20)                    # frame2 -> frame1
    aligned1 = S10(s1_orig)                         # section1 placed in frame0
    aligned2 = S21(s2_orig)                         # section2 placed in frame1

    pairs = [
        {"ref_name": "s0", "mov_name": "s1", "ref_coords": s0.tolist(),
         "aligned_coords": aligned1.tolist(), "mov_coords": s1_orig.tolist(),
         "pitch": 1.0, "method": "Sutura"},
        {"ref_name": "s1", "mov_name": "s2", "ref_coords": s1_orig.tolist(),
         "aligned_coords": aligned2.tolist(), "mov_coords": s2_orig.tolist(),
         "pitch": 1.0, "method": "Sutura"},
    ]
    rec = build_pointcloud(pairs)
    assert rec["n_sections"] == 3
    assert rec["composition"] == "pairwise_composition"
    # section 2's placed points should equal S10(S21(s2_orig)) = S10(aligned2)
    expected = S10(aligned2)
    placed = np.array([[p[0], p[1]] for p in rec["points"] if p[3] == 2])
    assert placed.shape == expected.shape
    assert np.allclose(placed, expected, atol=0.05)
