"""Demo-grade console rendering of the event stream for headless / non-TUI runs.

The full-screen experience is the Textual app (sutura_cli/tui). This is the
plain-stream renderer used by `sutura --headless` and by scripts - built to look
clean and finished on a projector.
"""
from __future__ import annotations

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__
from .core.events import (AgentMessage, BundleWritten, Note, RoutingDecision,
                          StepFinished, StepProgress, StepStarted)

ACCENT = "#a78bfa"     # lavender, matching the Sutura mark
ACCENT2 = "#6ee7ff"    # cyan highlight
DIM = "grey62"


def make_console() -> Console:
    """A UTF-8 console that uses rich's modern renderer (so box-drawing and the
    Sutura glyphs render on Windows Terminal instead of crashing the legacy
    cp1252 console)."""
    import sys
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    return Console(legacy_windows=False, emoji=False, highlight=False)

_ICON = {"ok": "[green]✓[/green]", "warn": "[yellow]⚠[/yellow]",
         "error": "[red]✗[/red]"}


def banner(console: Console, subtitle: str) -> None:
    title = Text()
    title.append("● ", style=f"bold {ACCENT2}")
    title.append("SUTURA", style=f"bold {ACCENT}")
    title.append(" GENOMICS", style="bold white")
    body = Group(
        title,
        Text("local-first spatial-transcriptomics alignment  ·  "
             f"v{__version__}", style=DIM),
        Text(subtitle, style=DIM),
    )
    console.print(Panel(body, box=box.ROUNDED, border_style=ACCENT,
                        padding=(0, 2), expand=False))


class ConsoleSink:
    """Renders one clean line per step, method-and-why prominent, plus a
    completion card. Progress ticks appear as sparse dim sub-lines so long
    steps (alignment) still feel alive."""

    def __init__(self, console: Console | None = None, show_progress=True):
        self.console = console or make_console()
        self.show_progress = show_progress
        self._last_pct: dict[str, int] = {}

    def emit(self, ev) -> None:
        c = self.console
        # routing has its own dedicated line; suppress its generic step chrome
        if getattr(ev, "step_id", "").startswith("route"):
            if isinstance(ev, (StepStarted, StepFinished, StepProgress)):
                return

        if isinstance(ev, StepStarted):
            det = f"  [{DIM}]{ev.detail}[/{DIM}]" if ev.detail else ""
            c.print(f"  [bold]{ev.title}[/bold]{det}")
        elif isinstance(ev, StepProgress):
            if not self.show_progress:
                return
            last = self._last_pct.get(ev.step_id, -1)
            if ev.pct >= last + 25 or ev.pct >= 100:
                self._last_pct[ev.step_id] = ev.pct
                c.print(f"      [{DIM}]· {ev.message} … {ev.pct}%[/{DIM}]")
        elif isinstance(ev, RoutingDecision):
            tag = ("[green]in-distribution[/green]" if ev.in_distribution
                   else f"[{ACCENT}]off-distribution[/{ACCENT}]")
            c.print(f"  [bold]Routing[/bold]  [{DIM}]{ev.pair}[/{DIM}]")
            c.print(f"      [{ACCENT2}]→ {ev.method}[/{ACCENT2}]   {tag} "
                    f"[{DIM}]· Mahalanobis {ev.mahalanobis:.2f} · gene overlap "
                    f"{int(ev.gene_overlap*100)}%[/{DIM}]")
        elif isinstance(ev, StepFinished):
            c.print(f"  {_ICON.get(ev.status, '✔')} [white]{ev.summary}[/white]")
        elif isinstance(ev, Note):
            colour = {"warn": "yellow", "error": "red"}.get(ev.level, DIM)
            c.print(f"      [{colour}]{ev.text}[/{colour}]")
        elif isinstance(ev, AgentMessage):
            c.print(f"\n[{ACCENT2}]{ev.text}[/{ACCENT2}]\n")
        elif isinstance(ev, BundleWritten):
            self._completion(ev.summary)

    def _completion(self, s: dict) -> None:
        panel = completion_panel(s)
        if panel is None:
            self.console.print(f"[{DIM}]bundle: {s.get('path','')}[/{DIM}]")
        else:
            self.console.print(panel)


def completion_panel(s: dict):
    """Build the 'Run complete' summary card (shared by console + TUI). Returns a
    rich Panel, or None if there is nothing to summarise."""
    if not s or not s.get("pairs"):
        return None
    tbl = Table(box=box.SIMPLE_HEAD, expand=False, pad_edge=False, show_edge=False)
    tbl.add_column("Pair", style="white")
    tbl.add_column("Method", style=ACCENT)
    tbl.add_column("Result", style="white")
    tbl.add_column("QC", style=DIM)
    for p in s["pairs"]:
        score = (f"{p['score']:.2f} spot-pitch err" if p.get("has_ground_truth")
                 else f"{p['score']:.2f} coverage")
        tbl.add_row(f"{p['ref']} → {p['mov']}", p["method_label"], score,
                    p.get("verdict") or "-")
    comp = ""
    if s.get("composition") == "pairwise_composition":
        comp = f"  [{DIM}](pairwise composition)[/{DIM}]"
    head = Text()
    head.append("✓ Run complete", style="bold green")
    head.append(f"   {s['job_id']}", style=DIM)
    meta = Text.from_markup(
        f"[{DIM}]sections[/{DIM}] {s['n_sections']}   "
        f"[{DIM}]pairs[/{DIM}] {s['n_pairs']}   "
        f"[{DIM}]3D points[/{DIM}] {s.get('n_points', 0)}{comp}")
    foot = Text.from_markup(
        f"[{DIM}]bundle[/{DIM}] {s['path']}\n"
        f"[{ACCENT2}]▶ open in the Sutura app to view the 3D model[/{ACCENT2}]")
    body = Group(meta, Text(""), tbl, Text(""), foot)
    return Panel(body, title=head, title_align="left", box=box.ROUNDED,
                 border_style="green", padding=(0, 2), expand=False)
