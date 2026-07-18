"""workflow_recommend - honest, grounded spatial/single-cell pipeline recommendations.

Public API
----------
    from workflow_recommend import recommend, render, parse_experiment, load_kb

    pipe = recommend("3D organ mapping of human kidney, 10x Visium, 12 serial "
                     "sections, want cell types and spatial domains")
    print(render(pipe))                 # markdown report
    print(render(pipe, fmt="text"))     # plain-text report

    # or step by step:
    spec = parse_experiment(description)     # NL -> ExperimentSpec (inspectable)
    pipe = build_pipeline(spec)              # ExperimentSpec -> Pipeline

Design principles: recommend REAL existing tools, never claim to solve
segmentation/batch effects, and flag every step that needs expert judgment.
Zero third-party dependencies for the core engine.
"""
from __future__ import annotations

from .knowledge_base import KnowledgeBase, load_kb
from .parser import parse_experiment
from .pipeline import Pipeline, PipelineStep, ToolChoice
from .recommender import build_pipeline, recommend
from .render import render
from .spec import GOALS, ExperimentSpec

__version__ = "0.1.0"

__all__ = [
    "recommend",
    "render",
    "parse_experiment",
    "build_pipeline",
    "load_kb",
    "KnowledgeBase",
    "ExperimentSpec",
    "Pipeline",
    "PipelineStep",
    "ToolChoice",
    "GOALS",
    "__version__",
]


def sutura_align_note() -> str:
    """Honest one-paragraph description of the in-house aligner (see tools.json)."""
    t = load_kb().get_tool("sutura_align")
    return t["why"] if t else ""
