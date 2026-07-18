"""Turn an ExperimentSpec into a concrete, ordered, honest pipeline.

The recommender decides WHICH steps a given experiment needs (from platform,
goals, and design), then selects the best-fit real tool for each step from the
knowledge base. It never claims to solve segmentation or batch effects: those
steps carry explicit ``unsolved`` / ``expert_judgment`` flags and honest notes.
"""
from __future__ import annotations

from .knowledge_base import KnowledgeBase, load_kb
from .parser import parse_experiment
from .pipeline import Pipeline, PipelineStep, ToolChoice
from .spec import ExperimentSpec


def _top_tools(kb: KnowledgeBase, step_id: str, platform: str | None,
               n_alt: int = 2, exclude: set[str] | None = None) -> tuple[ToolChoice | None, list[ToolChoice]]:
    exclude = exclude or set()
    ranked = [t for t in kb.tools_for_step(step_id, platform) if t["id"] not in exclude]
    if not ranked:
        return None, []
    primary = ToolChoice(tool=ranked[0], role="primary")
    alts = [ToolChoice(tool=t, role="alternative") for t in ranked[1 : 1 + n_alt]]
    return primary, alts


def _reference_warning(spec: ExperimentSpec, what: str) -> str | None:
    if spec.has_reference is True:
        return None
    availability = ("You did NOT indicate a matched single-cell reference"
                    if spec.has_reference is False
                    else "No matched single-cell reference was mentioned")
    return (f"{what} REQUIRES a matched single-cell/nucleus reference for this tissue. "
            f"{availability}. Obtain or generate one (matched organ + condition) first; "
            f"a mismatched reference yields confident but wrong results.")


def _decorate_step_meta(step_def: dict, step: PipelineStep) -> None:
    step.expert_judgment = bool(step_def.get("expert_judgment"))
    step.expert_note = step_def.get("expert_note", "")
    step.unsolved = bool(step_def.get("unsolved"))


def build_pipeline(spec: ExperimentSpec, kb: KnowledgeBase | None = None) -> Pipeline:
    kb = kb or load_kb()
    pipe = Pipeline(spec=spec)
    goals = spec.all_goals()
    platform = spec.platform
    plat_meta = kb.platforms.get(platform, {}) if platform else {}
    etype = kb.experiment_types.get(spec.experiment_type, {})

    # --- decide platform behavior, degrading gracefully when unknown -----
    if platform:
        needs_seg = bool(plat_meta.get("needs_segmentation"))
        needs_deconv = plat_meta.get("needs_deconvolution")  # True/False/"optional"
        single_cell = plat_meta.get("single_cell")           # True/"near"/False
    else:
        # unknown platform: assume single-cell-resolution imaging-like default, flagged
        needs_seg = True
        needs_deconv = False
        single_cell = True

    spot_based = needs_deconv is True  # Visium: multi-cell spots

    # ==================================================================
    # Assemble steps in canonical order. Each block appends 0 or 1 step.
    # ==================================================================
    steps: list[PipelineStep] = []

    def mk(step_id: str, reason: str) -> PipelineStep:
        sd = kb.steps[step_id]
        st = PipelineStep(step_id=step_id, name=sd["name"], purpose=sd["purpose"],
                          order=sd["order"], reason=reason)
        _decorate_step_meta(sd, st)
        return st

    # --- data loading (always) ---
    st = mk("data_loading", "Every pipeline starts by reading raw platform output into a common object.")
    st.primary, st.alternatives = _top_tools(kb, "data_loading", platform)
    steps.append(st)

    # --- QC (always) ---
    st = mk("qc", "Low-quality cells/spots and genes must be removed before any analysis.")
    st.primary, st.alternatives = _top_tools(kb, "qc", platform)
    if platform in ("cosmx",):
        st.warnings.append("CosMx has notable background; filter aggressively on negative-probe counts.")
    if plat_meta.get("known_limits"):
        st.warnings.append("Platform note: " + plat_meta["known_limits"])
    steps.append(st)

    # --- segmentation (imaging / HD / stereo-seq; NOT spot Visium) ---
    if needs_seg:
        if spot_based:
            pass  # never for spot Visium
        else:
            reason = ("This platform resolves individual transcripts/signal, so cells must be "
                      "segmented before counts exist. Segmentation error propagates into every "
                      "downstream number.")
            st = mk("segmentation", reason)
            st.primary, st.alternatives = _top_tools(kb, "segmentation", platform, n_alt=3)
            # surface transcript-based re-segmentation for imaging smFISH platforms
            if platform in ("xenium", "merscope", "cosmx"):
                st.warnings.append(
                    "The vendor ships a default segmentation; transcript-based re-segmentation "
                    "(Baysor / ProSeg) frequently improves boundaries where membranes aren't stained. "
                    "Compare against the default and inspect visually.")
            if platform is None:
                st.warnings.append(
                    "Platform unknown: segmentation tool is a generic default. Confirm the platform "
                    "to get the right segmenter (e.g. bin2cell for Visium HD, Stereopy for Stereo-seq).")
            steps.append(st)

    # --- normalization (always) ---
    st = mk("normalization", "Depth/total-count differences must be corrected and informative genes selected.")
    st.primary, st.alternatives = _top_tools(kb, "normalization", platform)
    if platform in ("xenium", "merscope", "cosmx"):
        st.warnings.append(
            "For targeted imaging panels, whole-transcriptome HVG selection is moot (all panel genes "
            "are informative); normalize by total counts (and consider cell area) and skip HVG.")
    steps.append(st)

    # --- batch correction / integration ---
    # Requires >1 thing to integrate. Include when there is positive evidence of
    # multiple sections/samples, when the user explicitly asked, or when the design
    # inherently spans many samples -- but suppress if we positively know it is a
    # single section (avoids recommending integration for one slide).
    multi = (spec.n_samples or 0) > 1 or (spec.n_sections or 0) > 1 or spec.serial_sections
    single_known = (not spec.serial_sections and (spec.n_sections or 0) <= 1
                    and (spec.n_samples or 0) <= 1)
    multi_sample_design = spec.experiment_type in {
        "atlas_building", "disease_vs_control", "developmental_timeseries"}
    include_batch = ("batch_correction" in spec.goals) or multi or (
        multi_sample_design and not single_known)
    if include_batch:
        n = spec.n_samples or spec.n_sections
        reason = ("Multiple sections/samples must be integrated into a shared embedding so that "
                  "differences are biology, not batch.")
        if n:
            reason = f"You have {n} sections/samples; " + reason[0].lower() + reason[1:]
        st = mk("batch_correction", reason)
        st.primary, st.alternatives = _top_tools(kb, "batch_correction", platform)
        st.warnings.append(
            "HONEST LIMIT: batch correction is not reliably solved. It can erase real biology "
            "(over-correction) or leave batch structure (under-correction). Run WITH and WITHOUT "
            "correction, and confirm known markers and expected biological differences survive.")
        if spec.experiment_type == "disease_vs_control":
            st.warnings.append(
                "Disease-vs-control danger: integration can 'correct away' the disease effect you are "
                "testing. Integrate for clustering/annotation only; do statistics on uncorrected counts "
                "via pseudobulk (see the DE step).")
        steps.append(st)

    # --- alignment / 3D reconstruction ---
    if "alignment_3d" in goals or spec.serial_sections:
        n = spec.n_sections
        reason = ("Serial sections must be registered into a common coordinate frame before any 3D "
                  "or cross-section spatial analysis.")
        if n:
            reason = f"You described {n} serial sections; they " + reason[reason.find('must'):]
        st = mk("alignment_3d", reason)
        primary, alts = _top_tools(kb, "alignment_3d", platform, n_alt=3,
                                   exclude={"sutura_align"})
        st.primary, st.alternatives = primary, alts
        # surface our own aligner honestly as an optional refinement layer
        sutura = kb.get_tool("sutura_align")
        if sutura:
            st.refinements.append(ToolChoice(
                tool=sutura, role="refinement",
                context_note=(
                    "OPTIONAL, HONEST SCOPE: Sutura Align does not replace the aligner above. It "
                    "(1) routes each section pair to the best-performing existing aligner for that "
                    "data regime, and (2) applies a fit-residual-GATED refinement on top of the base "
                    "alignment (usually PASTE2). The gate means it only refines when the base fit is "
                    "trustworthy and otherwise returns the base mapping unchanged, to avoid making "
                    "things worse. It measurably lowers alignment error in our internal benchmarks "
                    "but is research-stage and does not fix tissue distortion, tears, or folds.")))
        st.warnings.append(
            "HONEST LIMIT: serial-section alignment is hard and imperfect. Distortion, tears, folds, "
            "and unknown z-spacing degrade results, and a numerically good score can still hide wrong "
            "anatomy. Always overlay aligned sections and inspect landmarks visually.")
        if spec.experiment_type == "developmental_timeseries":
            st.warnings.append(
                "For a developmental time series, anatomy changes between timepoints - forcing spatial "
                "registration across stages is often wrong. Prefer integrating in expression space and "
                "reserve spatial alignment for serial sections within a single stage.")
        steps.append(st)

    # --- dimensionality reduction & clustering (always) ---
    st = mk("dimensionality_clustering",
            "Needed to define transcriptional groups prior to annotation and domain analysis.")
    st.primary, st.alternatives = _top_tools(kb, "dimensionality_clustering", platform)
    steps.append(st)

    # --- cell typing vs deconvolution ---
    want_typing = "cell_typing" in goals
    want_deconv = "deconvolution" in goals
    if spot_based and (want_typing or want_deconv):
        # Visium spots: 'cell typing' == deconvolution into proportions
        reason = ("This is a multi-cell spot platform, so per-spot cell identity means estimating "
                  "cell-type PROPORTIONS (deconvolution), not single-cell labels.")
        st = mk("deconvolution", reason)
        st.primary, st.alternatives = _top_tools(kb, "deconvolution", platform)
        w = _reference_warning(spec, "Deconvolution")
        if w:
            st.warnings.append(w)
        steps.append(st)
    else:
        if want_typing or (not spot_based and want_deconv):
            reason = ("Single-cell-resolution data supports per-cell annotation via reference mapping "
                      "or marker-based labeling.")
            st = mk("cell_typing", reason)
            st.primary, st.alternatives = _top_tools(kb, "cell_typing", platform)
            if platform in ("xenium", "merscope", "cosmx"):
                st.warnings.append(
                    "Targeted panel: prebuilt reference models trained on whole-transcriptome scRNA may "
                    "map poorly. Prefer training a classifier on a reference subset to the panel genes, "
                    "and confirm labels with panel markers.")
            st.warnings.append(
                "Automated labels are a starting point, not truth. Confirm with canonical markers and "
                "expert review; novel/ambiguous states will be mislabeled.")
            steps.append(st)
        # optional explicit deconvolution for near-single-cell platforms
        if want_deconv and not spot_based and plat_meta.get("needs_deconvolution") == "optional":
            st = mk("deconvolution",
                    "You asked for deconvolution and this platform's coarse bins can still be multi-cell.")
            st.primary, st.alternatives = _top_tools(kb, "deconvolution", platform)
            w = _reference_warning(spec, "Deconvolution")
            if w:
                st.warnings.append(w)
            steps.append(st)

    # --- spatial domains ---
    if "spatial_domains" in goals:
        st = mk("spatial_domains",
                "You want tissue domains/niches: cluster using expression AND spatial position.")
        st.primary, st.alternatives = _top_tools(kb, "spatial_domains", platform)
        steps.append(st)

    # --- spatial DE / differential expression ---
    if "spatial_de" in goals or spec.experiment_type == "disease_vs_control":
        if spec.experiment_type == "disease_vs_control":
            reason = ("A condition comparison needs statistically defensible differential expression "
                      "between conditions.")
        else:
            reason = "You want spatially variable genes and/or differential expression."
        st = mk("spatial_de", reason)
        # For condition comparisons, lead with pseudobulk DE, not the SVG tools.
        if spec.experiment_type == "disease_vs_control":
            primary, alts = _top_tools(kb, "spatial_de", platform, n_alt=3)
            # promote pydeseq2 to primary if present
            pdq = kb.get_tool("pydeseq2")
            if pdq and (not primary or primary.id != "pydeseq2"):
                new_alts = [primary] + alts if primary else alts
                new_alts = [a for a in new_alts if a.id != "pydeseq2"]
                primary = ToolChoice(tool=pdq, role="primary")
                alts = new_alts[:3]
            st.primary, st.alternatives = primary, alts
            st.warnings.append(
                "HONEST LIMIT: do NOT run per-cell/per-spot DE across conditions - it pseudo-replicates "
                "and massively inflates false positives. Pseudobulk per biological replicate (sample x "
                "cell type) and require multiple samples per condition.")
            if (spec.n_samples or 0) < 2:
                st.warnings.append(
                    "You described fewer than 2 samples per condition (or none stated). Condition-level "
                    "DE has NO valid statistic without biological replicates; results would be anecdotal.")
        else:
            st.primary, st.alternatives = _top_tools(kb, "spatial_de", platform, n_alt=3)
            if spot_based:
                st.warnings.append(
                    "Spot-level spatial DE is confounded by cell-type composition; interpret SVGs "
                    "alongside deconvolution results.")
        steps.append(st)

    # --- cell-cell communication ---
    if "cell_communication" in goals or spec.experiment_type == "tumor_architecture":
        reason = ("You want cell-cell interaction / niche signaling analysis."
                  if "cell_communication" in goals
                  else "Tumor microenvironment work typically needs ligand-receptor / niche analysis.")
        st = mk("cell_communication", reason)
        st.primary, st.alternatives = _top_tools(kb, "cell_communication", platform)
        if spot_based:
            st.warnings.append(
                "On multi-cell spots, ligand and receptor can come from different cells in the same spot; "
                "prefer spatially-resolved methods (COMMOT) and treat results as hypotheses.")
        steps.append(st)

    # --- visualization (always) ---
    st = mk("visualization", "Inspect QC, segmentation, domains, and (if 3D) the reconstructed stack.")
    st.primary, st.alternatives = _top_tools(kb, "visualization", platform)
    if spec.serial_sections:
        napari = kb.get_tool("napari")
        if napari and (not st.primary or st.primary.id != "napari"):
            st.refinements.append(ToolChoice(
                tool=napari, role="refinement",
                context_note="Use napari to view the aligned 3D stack volumetrically and to QC segmentation masks."))
    steps.append(st)

    # sort defensively by canonical order and attach
    pipe.steps = sorted(steps, key=lambda s: s.order)

    # --- pipeline-level warnings ---
    if spec.platform_confidence != "high":
        pipe.warnings.append(
            "Platform was not clearly identified; several step choices are generic defaults. "
            "Re-run with the platform named for a precise pipeline.")
    if spec.experiment_type_confidence == "low" and spec.experiment_type != "general_spatial":
        pipe.warnings.append(
            f"Experiment type inferred as '{etype.get('name', spec.experiment_type)}' with low confidence.")
    return pipe


def recommend(description: str, kb: KnowledgeBase | None = None) -> Pipeline:
    """One-shot: natural-language description -> recommended Pipeline."""
    kb = kb or load_kb()
    spec = parse_experiment(description, kb)
    return build_pipeline(spec, kb)
