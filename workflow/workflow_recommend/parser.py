"""Parse a free-text experiment description into an ExperimentSpec.

HONEST SCOPE: this is deterministic keyword/regex matching, not natural-language
understanding. It is transparent and predictable, which matters for a tool that
must not silently guess. When it is unsure it says so (via spec.notes and the
``*_confidence`` fields) rather than inventing detail. Unrecognized platforms or
goals degrade gracefully to sensible, clearly-flagged defaults.
"""
from __future__ import annotations

import re

from .knowledge_base import KnowledgeBase, load_kb
from .spec import ExperimentSpec

# ---- platform detection -------------------------------------------------

# Ordered so more specific names win (visium hd before visium).
_PLATFORM_PATTERNS: list[tuple[str, list[str]]] = [
    ("visium_hd", [r"visium\s*hd", r"\bhd\b.*visium", r"visium.*\bhd\b", r"2\s*um bin", r"bin2cell"]),
    ("xenium", [r"\bxenium\b"]),
    ("merscope", [r"\bmerscope\b", r"\bmerfish\b", r"\bvizgen\b"]),
    ("cosmx", [r"\bcosmx\b", r"\bcos\s*mx\b", r"nanostring", r"\bsmi\b"]),
    ("stereo_seq", [r"stereo[\s\-]?seq", r"\bstereoseq\b", r"\bstomics\b", r"\bdnb\b", r"\bbgi\b"]),
    ("visium", [r"\bvisium\b", r"\b10x\s*visium\b"]),
]

# ---- goal detection -----------------------------------------------------

_GOAL_KEYWORDS: dict[str, list[str]] = {
    "cell_typing": [
        "cell type", "cell-type", "celltype", "cell typing", "annotat", "identify cells",
        "which cells", "cell identit", "label cells", "cell population",
    ],
    "spatial_domains": [
        "spatial domain", "tissue domain", "spatial region", "niche", "domain",
        "tissue architecture", "spatial cluster", "anatomical region", "tissue region",
        "layer", "microenvironment",
    ],
    "deconvolution": [
        "deconvolut", "cell type proportion", "cell-type proportion", "composition",
        "abundance per spot", "spot composition",
    ],
    "batch_correction": [
        "batch", "integrat", "harmoniz", "harmonis", "remove batch", "batch effect",
    ],
    "alignment_3d": [
        "3d", "three dimensional", "three-dimensional", "reconstruct", "align", "registration",
        "register", "serial section", "z-stack", "z stack", "volumetric", "stack sections",
        "common coordinate",
    ],
    "spatial_de": [
        "differential expression", "differentially expressed", "\\bde\\b", "spatially variable",
        "svg", "marker gene", "compare expression", "expression difference", "upregulat",
        "downregulat", "spatial gene",
    ],
    "cell_communication": [
        "communication", "ligand", "receptor", "ligand-receptor", "cell-cell interaction",
        "cell cell interaction", "crosstalk", "cross-talk", "signaling", "interaction between",
    ],
}


def _detect_platform(text: str, spec: ExperimentSpec) -> None:
    for pid, patterns in _PLATFORM_PATTERNS:
        for pat in patterns:
            if re.search(pat, text):
                spec.platform = pid
                spec.platform_confidence = "high"
                return
    spec.platform = None
    spec.platform_confidence = "unknown"
    spec.add_note(
        "No platform recognized in the description. Segmentation/deconvolution decisions "
        "depend on platform; recommendation assumes a generic single-cell-resolution spatial "
        "platform. Specify the platform (Visium, Visium HD, Xenium, MERSCOPE, CosMx, Stereo-seq) "
        "for a precise pipeline."
    )


def _detect_experiment_type(text: str, kb: KnowledgeBase, spec: ExperimentSpec) -> None:
    best_id, best_hits = None, 0
    for tid, meta in kb.experiment_types.items():
        hits = 0
        for syn in meta.get("synonyms", []):
            if syn and syn.lower() in text:
                hits += 1
        if hits > best_hits:
            best_id, best_hits = tid, hits
    if best_id:
        spec.experiment_type = best_id
        spec.experiment_type_confidence = "high" if best_hits >= 2 else "low"
    else:
        spec.experiment_type = "general_spatial"
        spec.experiment_type_confidence = "low"
        spec.add_note(
            "Experiment design not clearly identified; treating it as a general spatial survey. "
            "Mention the design (3D organ mapping, tumor architecture, developmental time series, "
            "disease-vs-control, atlas building) for a tailored pipeline."
        )


def _detect_sections_and_samples(text: str, spec: ExperimentSpec) -> None:
    # serial sections / slices with an optional count
    section_words = r"(?:serial\s+)?(?:section|slice|slide|z[\-\s]?plane)s?"
    m = re.search(r"(\d+)\s+" + section_words, text)
    if m:
        n = int(m.group(1))
        spec.n_sections = n
        if n > 1:
            spec.serial_sections = True
    # explicit serial-section language even without a number
    if re.search(r"serial\s+section|z[\-\s]?stack|consecutive\s+section|volumetric|3d reconstruct", text):
        spec.serial_sections = True

    # samples / donors / patients / conditions / timepoints
    for unit in ["donor", "patient", "sample", "subject", "individual", "timepoint",
                 "time point", "condition", "replicate", "biopsy", "case"]:
        m = re.search(r"(\d+)\s+" + unit + r"s?", text)
        if m:
            n = int(m.group(1))
            spec.n_samples = max(spec.n_samples or 0, n)


def _detect_reference(text: str, spec: ExperimentSpec) -> None:
    has = re.search(
        r"scrna|sc-rna|single[\-\s]?cell reference|matched single[\-\s]?cell|snrna|"
        r"reference (?:atlas|dataset|single)|single[\-\s]?cell (?:data|atlas|reference)|"
        r"companion single",
        text,
    )
    lacks = re.search(r"no (?:single[\-\s]?cell|scrna|reference)|without (?:a )?reference|no matched", text)
    if lacks:
        spec.has_reference = False
    elif has:
        spec.has_reference = True
    else:
        spec.has_reference = None


def _detect_goals(text: str, kb: KnowledgeBase, spec: ExperimentSpec) -> None:
    for goal, kws in _GOAL_KEYWORDS.items():
        for kw in kws:
            pattern = kw if kw.startswith("\\b") or "\\b" in kw else re.escape(kw)
            if re.search(pattern, text):
                spec.goals.add(goal)
                break

    # Fold in the experiment-type template's implied goals as *inferred* goals.
    etype = kb.experiment_types.get(spec.experiment_type, {})
    for g in etype.get("implies_goals", []):
        if g not in spec.goals:
            spec.goals_inferred.add(g)

    # A serial-section design always implies alignment.
    if spec.serial_sections:
        if "alignment_3d" not in spec.goals:
            spec.goals_inferred.add("alignment_3d")

    # Multiple samples/sections implies integration is on the table.
    if (spec.n_samples or 0) > 1 or (spec.n_sections or 0) > 1:
        if "batch_correction" not in spec.goals:
            spec.goals_inferred.add("batch_correction")

    if not spec.goals and not spec.goals_inferred:
        spec.goals_inferred.update({"cell_typing", "spatial_domains"})
        spec.add_note("No explicit analysis goal detected; defaulting to cell typing + spatial domains.")


def _detect_tissue(text: str, spec: ExperimentSpec) -> None:
    for organ in ["kidney", "brain", "liver", "lung", "heart", "breast", "prostate", "colon",
                  "intestine", "pancreas", "skin", "lymph node", "spleen", "bone marrow",
                  "placenta", "embryo", "tumor", "tumour", "muscle", "retina", "ovary", "testis"]:
        if organ in text:
            spec.tissue = organ
            return


def parse_experiment(description: str, kb: KnowledgeBase | None = None) -> ExperimentSpec:
    """Parse a natural-language experiment description into an ExperimentSpec."""
    kb = kb or load_kb()
    text = description.lower()
    spec = ExperimentSpec(raw_text=description)

    _detect_platform(text, spec)
    _detect_experiment_type(text, kb, spec)
    _detect_sections_and_samples(text, spec)
    _detect_reference(text, spec)
    _detect_goals(text, kb, spec)
    _detect_tissue(text, spec)

    return spec
