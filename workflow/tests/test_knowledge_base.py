"""Integrity tests for the structured knowledge base.

These guard the single most important property of an 'honest, grounded' tool:
the knowledge base must be internally consistent and reference only real,
declared steps/platforms. If someone adds a tool with a typo'd step id or an
unknown platform, these fail loudly.
"""
from workflow_recommend.knowledge_base import load_kb

kb = load_kb()

VALID_PLATFORMS = set(kb.platforms) | {"all"}
VALID_STEPS = set(kb.steps)
VALID_MATURITY = {"mature", "established", "emerging", "research"}


def test_all_kb_files_load():
    assert kb.platforms and kb.experiment_types and kb.steps and kb.tools


def test_tool_ids_unique():
    ids = [t["id"] for t in kb.tools]
    assert len(ids) == len(set(ids)), "duplicate tool ids: " + str(
        [i for i in ids if ids.count(i) > 1])


def test_tools_reference_valid_steps_and_platforms():
    for t in kb.tools:
        assert t.get("steps"), f"{t['id']} has no steps"
        for s in t["steps"]:
            assert s in VALID_STEPS, f"{t['id']} references unknown step {s}"
        for p in t.get("platforms", []):
            assert p in VALID_PLATFORMS, f"{t['id']} references unknown platform {p}"


def test_tools_have_required_fields():
    required = ["id", "name", "steps", "platforms", "install", "why", "runtime", "limitations", "maturity"]
    for t in kb.tools:
        for f in required:
            assert t.get(f), f"{t['id']} missing/empty field: {f}"
        assert t["maturity"] in VALID_MATURITY, f"{t['id']} bad maturity {t['maturity']}"


def test_every_step_has_at_least_one_tool():
    for step_id in kb.steps:
        tools = kb.tools_for_step(step_id)
        assert tools, f"no tool serves step {step_id}"


def test_every_platform_has_a_segmentation_or_deconv_path():
    # imaging/binned platforms need a segmenter; spot platforms need a deconvolver
    for pid, p in kb.platforms.items():
        if p.get("needs_segmentation"):
            assert kb.tools_for_step("segmentation", pid), f"{pid} needs segmentation but no tool"
        if p.get("needs_deconvolution") is True:
            assert kb.tools_for_step("deconvolution", pid), f"{pid} needs deconvolution but no tool"


def test_experiment_types_reference_valid_goals():
    from workflow_recommend.spec import GOALS
    for tid, meta in kb.experiment_types.items():
        for g in meta.get("implies_goals", []):
            assert g in GOALS, f"{tid} implies unknown goal {g}"


def test_tools_ascii_clean():
    # generated reports must render on any console; KB text stays ASCII
    for t in kb.tools:
        for field in ("why", "limitations", "runtime", "install"):
            val = t.get(field, "")
            assert val.isascii(), f"{t['id']}.{field} contains non-ASCII: {val!r}"


def test_ranking_is_deterministic_and_priority_ordered():
    tools = kb.tools_for_step("batch_correction")
    priorities = [t.get("priority", 0) for t in tools]
    assert priorities == sorted(priorities, reverse=True)


def test_sutura_align_is_honest_research_stage():
    t = kb.get_tool("sutura_align")
    assert t is not None
    assert t["maturity"] == "research"
    # must describe routing + gated refinement, and must NOT overclaim
    low = t["why"].lower()
    assert "rout" in low and "gate" in low
    assert "solve" not in low or "does not" in low or "not a substitute" in t["limitations"].lower()
