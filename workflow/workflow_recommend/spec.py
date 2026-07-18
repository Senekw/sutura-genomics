"""Structured representation of a parsed experiment description."""
from __future__ import annotations

from dataclasses import dataclass, field

# Canonical analysis goals. Each maps to one or more pipeline steps.
GOALS = {
    "cell_typing",        # assign cell-type labels (or proportions, for spot data)
    "spatial_domains",    # find tissue domains / niches
    "deconvolution",      # explicit spot deconvolution
    "batch_correction",   # integrate multiple samples/sections
    "alignment_3d",       # register serial sections / 3D reconstruction
    "spatial_de",         # spatially variable genes / differential expression
    "cell_communication", # ligand-receptor / niche interaction
}


@dataclass
class ExperimentSpec:
    """What we parsed from a natural-language experiment description.

    Everything here is derived by keyword/heuristic parsing (see parser.py). The
    ``notes`` field records how confident each inference is and what was assumed,
    so the recommendation can stay honest about its own uncertainty.
    """

    raw_text: str
    platform: str | None = None            # platform id from kb, or None if unknown
    platform_confidence: str = "unknown"   # high | low | unknown
    experiment_type: str = "general_spatial"
    experiment_type_confidence: str = "low"
    serial_sections: bool = False
    n_sections: int | None = None
    n_samples: int | None = None           # samples / donors / conditions / timepoints
    goals: set[str] = field(default_factory=set)
    goals_inferred: set[str] = field(default_factory=set)  # added from the type template, not stated
    has_reference: bool | None = None      # matched single-cell reference available?
    tissue: str | None = None
    notes: list[str] = field(default_factory=list)

    def add_note(self, note: str) -> None:
        self.notes.append(note)

    def all_goals(self) -> set[str]:
        return set(self.goals) | set(self.goals_inferred)

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "platform_confidence": self.platform_confidence,
            "experiment_type": self.experiment_type,
            "experiment_type_confidence": self.experiment_type_confidence,
            "serial_sections": self.serial_sections,
            "n_sections": self.n_sections,
            "n_samples": self.n_samples,
            "goals": sorted(self.goals),
            "goals_inferred": sorted(self.goals_inferred),
            "has_reference": self.has_reference,
            "tissue": self.tissue,
            "notes": list(self.notes),
        }
