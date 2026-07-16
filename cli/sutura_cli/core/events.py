"""Event stream between the agent loop and any front-end (TUI, console, tests).

The core never draws anything. It emits typed Events to an EventSink; the TUI
renders them as live step output, the console sink prints them, and tests
collect them in a list. This is what keeps the agent loop UI-independent and
headlessly testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


# --- event kinds ---------------------------------------------------------- #
@dataclass
class Event:
    kind: str


@dataclass
class StepStarted(Event):
    step_id: str
    title: str
    detail: str = ""
    kind: str = field(default="step_started", init=False)


@dataclass
class StepProgress(Event):
    step_id: str
    pct: int
    message: str = ""
    kind: str = field(default="step_progress", init=False)


@dataclass
class StepFinished(Event):
    step_id: str
    status: str = "ok"            # ok | warn | error
    summary: str = ""
    kind: str = field(default="step_finished", init=False)


@dataclass
class RoutingDecision(Event):
    pair: str
    method: str                  # honest label of the method actually chosen
    reason: str
    in_distribution: bool
    confidence: float
    mahalanobis: float
    gene_overlap: float
    kind: str = field(default="routing", init=False)


@dataclass
class Note(Event):
    text: str
    level: str = "info"          # info | warn | error
    kind: str = field(default="note", init=False)


@dataclass
class AgentMessage(Event):
    """The assistant speaking to the user (planning, summaries, answers)."""
    text: str
    kind: str = field(default="agent_message", init=False)


@dataclass
class BundleWritten(Event):
    job_id: str
    path: str
    summary: dict[str, Any] = field(default_factory=dict)
    kind: str = field(default="bundle_written", init=False)


# --- sinks ---------------------------------------------------------------- #
class EventSink(Protocol):
    def emit(self, event: Event) -> None: ...


class ListSink:
    """Collects events in a list (used by tests and headless callers)."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)

    def of_kind(self, kind: str) -> list[Event]:
        return [e for e in self.events if e.kind == kind]


class CallbackSink:
    """Adapts a plain function into an EventSink (used by the TUI)."""

    def __init__(self, fn) -> None:
        self._fn = fn

    def emit(self, event: Event) -> None:
        self._fn(event)


class FanoutSink:
    def __init__(self, *sinks: EventSink) -> None:
        self._sinks = sinks

    def emit(self, event: Event) -> None:
        for s in self._sinks:
            s.emit(event)
