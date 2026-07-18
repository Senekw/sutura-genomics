"""Tests for the recommendation logic (the honest routing rules)."""
from workflow_recommend.parser import parse_experiment
from workflow_recommend.recommender import build_pipeline, recommend


def step_ids(pipe):
    return [s.step_id for s in pipe.steps]


def primary_id(pipe, step_id):
    st = pipe.step(step_id)
    return st.primary.id if st and st.primary else None


# ---- platform-driven step inclusion ------------------------------------

def test_visium_gets_deconvolution_not_segmentation_or_celltyping():
    pipe = recommend("10x Visium kidney, want cell types")
    ids = step_ids(pipe)
    assert "deconvolution" in ids
    assert "segmentation" not in ids           # spots are not segmented
    assert "cell_typing" not in ids            # spot 'typing' == deconvolution
    assert primary_id(pipe, "deconvolution") in {"cell2location", "rctd"}


def test_xenium_gets_segmentation_and_celltyping_not_deconvolution():
    pipe = recommend("Xenium breast, want cell types")
    ids = step_ids(pipe)
    assert "segmentation" in ids
    assert "cell_typing" in ids
    assert "deconvolution" not in ids


def test_segmentation_step_flagged_unsolved():
    pipe = recommend("Xenium breast, cell types")
    seg = pipe.step("segmentation")
    assert seg.unsolved is True
    assert seg.expert_judgment is True
    assert seg.expert_note  # honest note present


def test_stereo_seq_uses_stereopy_reader():
    pipe = recommend("Stereo-seq mouse embryo section, cell types and domains")
    # stereopy is platform-exclusive and should win data_loading for stereo-seq
    assert primary_id(pipe, "data_loading") == "stereopy"
    assert "segmentation" in step_ids(pipe)


def test_visium_hd_segmentation_is_bin2cell():
    pipe = recommend("Visium HD colon, 2um bins, cell types and domains")
    assert primary_id(pipe, "segmentation") == "bin2cell"


# ---- design-driven step inclusion --------------------------------------

def test_serial_sections_include_alignment_with_sutura_refinement():
    pipe = recommend("Visium heart, 8 serial sections, 3D reconstruction, cell types")
    st = pipe.step("alignment_3d")
    assert st is not None
    assert st.primary.id == "paste2"
    ref_ids = [r.id for r in st.refinements]
    assert "sutura_align" in ref_ids
    # honest framing present in the refinement note
    note = st.refinements[0].context_note.lower()
    assert "rout" in note and "gate" in note and "does not replace" in note


def test_single_section_no_alignment_no_batch():
    pipe = recommend("Xenium skin, single section, cell types")
    ids = step_ids(pipe)
    assert "alignment_3d" not in ids
    assert "batch_correction" not in ids


def test_multi_sample_triggers_batch_correction():
    pipe = recommend("Xenium lung across 5 donors, cell types")
    assert "batch_correction" in step_ids(pipe)


def test_disease_vs_control_uses_pseudobulk_primary_and_warns():
    pipe = recommend("Visium HD lung, disease vs control, 4 donors per group, "
                     "differential expression")
    de = pipe.step("spatial_de")
    assert de is not None
    assert de.primary.id == "pydeseq2"  # pseudobulk promoted over SVG tools
    joined = " ".join(de.warnings).lower()
    assert "pseudobulk" in joined and "false positive" in joined


def test_disease_vs_control_warns_on_missing_replicates():
    pipe = recommend("Visium lung, disease vs control, differential expression")
    de = pipe.step("spatial_de")
    assert any("replicate" in w.lower() for w in de.warnings)


def test_tumor_architecture_includes_communication():
    pipe = recommend("Xenium breast tumor microenvironment, single section")
    assert "cell_communication" in step_ids(pipe)


# ---- honesty guarantees ------------------------------------------------

def test_batch_correction_carries_honest_limit():
    pipe = recommend("Xenium lung, 5 donors, cell types")
    bc = pipe.step("batch_correction")
    assert any("not reliably solved" in w.lower() or "over-correct" in w.lower()
               for w in bc.warnings)


def test_deconvolution_warns_without_reference():
    pipe = recommend("Visium kidney, cell types")  # no reference stated
    dec = pipe.step("deconvolution")
    assert any("reference" in w.lower() for w in dec.warnings)


def test_deconvolution_no_warn_with_reference():
    pipe = recommend("Visium kidney, cell types, with matched scRNA reference")
    dec = pipe.step("deconvolution")
    assert not any("REQUIRES a matched" in w for w in dec.warnings)


# ---- structural guarantees ---------------------------------------------

def test_steps_in_canonical_order():
    pipe = recommend("Visium HD kidney, 6 serial sections, disease vs control, "
                     "4 donors, cell types, domains, communication")
    orders = [s.order for s in pipe.steps]
    assert orders == sorted(orders)


def test_pipeline_always_has_loading_qc_norm_viz():
    pipe = recommend("something vague")
    ids = step_ids(pipe)
    for required in ("data_loading", "qc", "normalization", "dimensionality_clustering", "visualization"):
        assert required in ids


def test_unknown_platform_still_produces_pipeline_and_flags():
    pipe = recommend("spatial transcriptomics of pancreas, cell types")
    assert pipe.steps
    assert any("platform" in w.lower() for w in pipe.warnings)


def test_every_included_step_has_primary_or_note():
    pipe = recommend("Xenium breast tumor, 3 serial sections, cell types, domains, communication, DE")
    for st in pipe.steps:
        # every step should resolve to at least a primary tool
        assert st.primary is not None, f"{st.step_id} has no primary tool"
