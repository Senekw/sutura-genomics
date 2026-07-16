"""Console rendering of the event stream for headless / non-TUI runs.

The full-screen experience is the Textual app (sutura_cli/tui). This is the
plain-stream fallback used by `sutura --headless` and by scripts/tests.
"""
from __future__ import annotations

from rich.console import Console

from .core.events import (AgentMessage, BundleWritten, Note, RoutingDecision,
                          StepFinished, StepProgress, StepStarted)


class ConsoleSink:
    def __init__(self, console: Console | None = None, show_progress=True):
        self.console = console or Console()
        self.show_progress = show_progress
        self._last_pct: dict[str, int] = {}

    def emit(self, ev) -> None:
        c = self.console
        if isinstance(ev, StepStarted):
            det = f" [dim]- {ev.detail}[/dim]" if ev.detail else ""
            c.print(f"[bold]> {ev.title}[/bold]{det}")
        elif isinstance(ev, StepProgress):
            if not self.show_progress:
                return
            last = self._last_pct.get(ev.step_id, -1)
            if ev.pct >= last + 10 or ev.pct >= 100:      # throttle
                self._last_pct[ev.step_id] = ev.pct
                c.print(f"  [dim]... {ev.message} ({ev.pct}%)[/dim]")
        elif isinstance(ev, RoutingDecision):
            tag = "in-distribution" if ev.in_distribution else "off-distribution"
            c.print(f"  [cyan]route -> {ev.method}[/cyan] "
                    f"[dim]({tag}; {ev.reason})[/dim]")
        elif isinstance(ev, StepFinished):
            mark = {"ok": "[green]v[/green]", "warn": "[yellow]![/yellow]",
                    "error": "[red]x[/red]"}.get(ev.status, "v")
            c.print(f"{mark} {ev.summary}")
        elif isinstance(ev, Note):
            colour = {"warn": "yellow", "error": "red"}.get(ev.level, "dim")
            c.print(f"  [{colour}]{ev.text}[/{colour}]")
        elif isinstance(ev, AgentMessage):
            c.print(f"\n[bold cyan]{ev.text}[/bold cyan]\n")
        elif isinstance(ev, BundleWritten):
            c.print(f"[bold green]bundle written[/bold green] [dim]{ev.path}[/dim]")
