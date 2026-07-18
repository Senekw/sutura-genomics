"""Data models for a recommended pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field

from .spec import ExperimentSpec


@dataclass
class ToolChoice:
    """One recommended tool at a step, carrying its KB record verbatim."""

    tool: dict                      # the raw KB tool record
    role: str = "primary"           # primary | alternative | refinement
    context_note: str = ""          # step-specific note about using this tool here

    @property
    def id(self) -> str:
        return self.tool["id"]

    @property
    def name(self) -> str:
        return self.tool["name"]


@dataclass
class PipelineStep:
    step_id: str
    name: str
    purpose: str
    order: int
    reason: str                                    # why this step is in *this* pipeline
    primary: ToolChoice | None = None
    alternatives: list[ToolChoice] = field(default_factory=list)
    refinements: list[ToolChoice] = field(default_factory=list)
    expert_judgment: bool = False
    expert_note: str = ""
    unsolved: bool = False
    warnings: list[str] = field(default_factory=list)

    def all_choices(self) -> list[ToolChoice]:
        out = []
        if self.primary:
            out.append(self.primary)
        out.extend(self.refinements)
        out.extend(self.alternatives)
        return out


@dataclass
class Pipeline:
    spec: ExperimentSpec
    steps: list[PipelineStep] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def step(self, step_id: str) -> PipelineStep | None:
        for s in self.steps:
            if s.step_id == step_id:
                return s
        return None
