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
from .core.events import (AgentMessage, BundleWritten, Note, PairResult,
                          RoutingDecision, StepFinished, StepProgress,
                          StepStarted)

_QUIET_PREFIXES = ("route", "align:", "postqc:")


def _short_method(m: str) -> str:
    if not m:
        return "?"
    if "adapt" in m:
        return "Sutura·adapt"
    if "zero-shot" in m:
        return "Sutura·zs"
    if "sutura" in m.lower() or "graph" in m.lower():
        return "Sutura"
    if "paste" in m.lower():
        return "PASTE2"
    return m[:12]


def _fit(s: str, w: int) -> str:
    return s if len(s) <= w else s[: w - 1] + "…"

ACCENT = "#b78bff"     # purple, the Sutura accent
ACCENT2 = "#d9c4ff"    # bright purple highlight
DIM = "grey58"
_RULE = "#2a2340"      # dim purple stage divider


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


_DNA = ["●╲ ╱●", " ╲╳╱ ", " ╱╳╲ ", "●╱ ╲●"]


def banner(console: Console, subtitle: str) -> None:
    mark = Text("\n".join(_DNA), style=f"bold {ACCENT}")
    title = Text()
    title.append("SUTURA", style=f"bold {ACCENT}")
    title.append("  spatial-transcriptomics alignment assistant", style=DIM)
    body = Group(
        mark,
        title,
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
        self._pairs_open = False

    def _stage(self, title: str):
        self.console.print()
        self.console.rule(f"[bold {ACCENT}] {title} ", characters="─",
                          style=_RULE, align="left")

    def _open_pairs(self):
        self._stage("Alignment")
        self.console.print(f"  [{DIM}]{'pair':<27}{'method':<13}{'error':>7}  "
                           f"{'routing':<11}qc[/{DIM}]")
        self._pairs_open = True

    def emit(self, ev) -> None:
        c = self.console
        sid = getattr(ev, "step_id", "")
        # per-pair chrome is folded into the compact table
        if sid.startswith(_QUIET_PREFIXES):
            if isinstance(ev, StepProgress) and self.show_progress:
                last = self._last_pct.get(sid, -1)
                if ev.pct >= last + 33 or ev.pct >= 100:
                    self._last_pct[sid] = ev.pct
                    c.print(f"    [{DIM}]· {ev.message} … {ev.pct}%[/{DIM}]")
            return

        if isinstance(ev, StepStarted):
            self._stage(ev.title)
        elif isinstance(ev, StepProgress):
            if not self.show_progress:
                return
            last = self._last_pct.get(sid, -1)
            if ev.pct >= last + 25 or ev.pct >= 100:
                self._last_pct[sid] = ev.pct
                c.print(f"    [{DIM}]· {ev.message} … {ev.pct}%[/{DIM}]")
        elif isinstance(ev, RoutingDecision):
            pass                       # folded into the pair row
        elif isinstance(ev, PairResult):
            if not self._pairs_open:
                self._open_pairs()
            pair = f"{_fit(ev.ref + ' → ' + ev.mov, 26):<27}"
            method = f"{_short_method(ev.method_label):<13}"
            err = f"{(f'{ev.score:.2f}' if ev.has_ground_truth else f'{ev.score:.2f}c'):>7}"
            if ev.in_distribution is None:
                route = "forced"
            else:
                tag = "in" if ev.in_distribution else "off"
                route = (f"{tag}·{ev.mahalanobis:.1f}"
                         if ev.mahalanobis is not None else tag)
            route = f"{route:<11}"
            qc = (f"[green]{ev.verdict}[/green]" if ev.verdict == "pass"
                  else f"[yellow]{ev.verdict}[/yellow]")
            c.print(f"  {pair}[{ACCENT}]{method}[/{ACCENT}]{err}  "
                    f"[{DIM}]{route}[/{DIM}]{qc}")
        elif isinstance(ev, StepFinished):
            c.print(f"  {_ICON.get(ev.status, '✔')} [white]{ev.summary}[/white]")
        elif isinstance(ev, Note):
            colour = {"warn": "yellow", "error": "red"}.get(ev.level, DIM)
            c.print(f"    [{colour}]{ev.text}[/{colour}]")
        elif isinstance(ev, AgentMessage):
            if ev.text.lower().startswith("on it:"):
                c.print(f"[{DIM}]{ev.text.splitlines()[0]}[/{DIM}]")
            else:
                c.print(f"\n[{ACCENT2}]{ev.text}[/{ACCENT2}]\n")
        elif isinstance(ev, BundleWritten):
            self._pairs_open = False
            c.print()
            self._completion(ev.summary)

    def _completion(self, s: dict) -> None:
        panel = completion_panel(s)
        if panel is None:
            self.console.print(f"[{DIM}]bundle: {s.get('path','')}[/{DIM}]")
        else:
            self.console.print(panel)


def completion_panel(s: dict):
    """Build the compact 'Run complete' summary card (shared by console + TUI).
    Per-pair detail already streamed above as the Alignment table, so the card
    stays a calm summary: counts, methods used, and where the bundle went.
    Returns a rich Panel, or None if there is nothing to summarise."""
    if not s or not s.get("pairs"):
        return None
    comp = ""
    if s.get("composition") == "pairwise_composition":
        comp = f"  [{DIM}](pairwise composition)[/{DIM}]"
    head = Text()
    head.append("✓ Run complete", style="bold green")
    head.append(f"   {s['job_id']}", style=DIM)
    meta = Text.from_markup(
        f"[{DIM}]sections[/{DIM}] {s['n_sections']}    "
        f"[{DIM}]pairs[/{DIM}] {s['n_pairs']}    "
        f"[{DIM}]3D points[/{DIM}] {s.get('n_points', 0):,}{comp}")
    methods = Text.from_markup(
        f"[{DIM}]methods[/{DIM}] " +
        "  ".join(f"[{ACCENT}]{m}[/{ACCENT}]" for m in s.get("methods", [])))
    foot = Text.from_markup(
        f"[{DIM}]bundle[/{DIM}] {s['path']}\n"
        f"[{ACCENT2}]▶ open in the Sutura app to view the 3D model[/{ACCENT2}]")
    body = Group(meta, methods, Text(""), foot)
    return Panel(body, title=head, title_align="left", box=box.ROUNDED,
                 border_style="green", padding=(0, 2), expand=False)
