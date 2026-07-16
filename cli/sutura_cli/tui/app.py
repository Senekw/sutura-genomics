"""Full-screen Sutura TUI, styled after Claude Code: a calm, scannable interface.

Top-left header carries the SUTURA mark and the active backend/model. The work
area presents each stage (Load / QC / Alignment / 3D / Report) as a visually
separated block, with per-pair results in a compact aligned table rather than a
wall of text. A bottom mode/status bar and a natural-language prompt complete it.

The agent loop is blocking (torch / PASTE2), so it runs in a Textual worker
thread; events are marshalled back onto the UI thread via call_from_thread.
"""
from __future__ import annotations

import os as _os

from rich.rule import Rule
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.widgets import Input, RichLog, Static

from .. import __version__
from ..core.agent import Session
from ..core.config import Config
from ..core.events import (AgentMessage, BundleWritten, Note, PairResult,
                           RoutingDecision, StepFinished, StepProgress,
                           StepStarted)
from ..render import completion_panel

_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_ACCENT = "#a78bfa"
_ACCENT2 = "#6ee7ff"
_RULE = "#34344a"

# step_ids whose per-event chrome is suppressed in the log (shown via the status
# bar and folded into the compact Alignment table instead)
_QUIET_PREFIXES = ("route", "align:", "postqc:")


def _backend_line(backend) -> str:
    name = getattr(backend, "name", "rule")
    model = getattr(backend, "model", None)
    if name == "ollama":
        return f"ollama · {model} · local, no data egress"
    if name == "cloud":
        return f"cloud · {model} · Anthropic API (metadata only)"
    return "offline rule planner · no LLM, local only"


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


class Brand(Static):
    """Fixed top-left header: SUTURA mark + active backend/model."""

    def __init__(self):
        super().__init__(id="brand")
        self.backend_line = "starting the local planner…"

    def set_backend(self, line: str):
        self.backend_line = line
        self.refresh()

    def render(self):
        return (f" [bold {_ACCENT2}]◗[/bold {_ACCENT2}] "
                f"[bold {_ACCENT}]SUTURA[/bold {_ACCENT}]  "
                f"[dim]spatial-transcriptomics alignment · v{__version__}[/dim]\n"
                f"   [dim]{self.backend_line}[/dim]")


class StatusBar(Static):
    """Bottom mode/status bar: arrow + mode + current activity + spinner."""

    def __init__(self):
        super().__init__(id="status")
        self.mode = "manual mode"
        self.state = "idle"
        self.pct = None
        self._spin = 0
        self.working = False

    def set_state(self, state: str, pct=None):
        self.state = state
        self.pct = pct
        self._spin = (self._spin + 1) % len(_SPINNER)
        self.refresh()

    def set_working(self, working: bool):
        self.working = working
        self.state = "working" if working else "idle"
        self.pct = None
        self.refresh()

    def render(self):
        pct = f" [{self.pct}%]" if self.pct is not None else ""
        spin = (f"[{_ACCENT}]{_SPINNER[self._spin]}[/{_ACCENT}] " if self.working
                else "[green]●[/green] ")
        return (f" [bold {_ACCENT2}]▷[/bold {_ACCENT2}] [bold]{self.mode}[/bold] "
                f"[dim]│[/dim] {spin}{self.state}{pct}")


class SuturaApp(App):
    CSS = """
    Screen { layout: vertical; background: $surface; }
    #brand { height: 3; padding: 1 1 0 2; background: $surface; color: $text; }
    #stream { height: 1fr; padding: 0 2; margin: 1 1 0 1; background: $surface; }
    #status { height: 1; background: $panel; color: $text; }
    #prompt { height: 3; border: round #34344a; background: $surface; margin: 0 1 1 1; }
    #prompt:focus { border: round #a78bfa; }
    """
    BINDINGS = [("ctrl+c", "quit", "Quit")]

    def __init__(self, cfg: Config, initial_instruction: str | None = None):
        super().__init__()
        self.cfg = cfg
        self.initial = initial_instruction
        self.session: Session | None = None
        self._pairs_open = False       # has the Alignment table header been shown
        self._planned = False          # suppress repeated planning chatter

    def compose(self) -> ComposeResult:
        yield Brand()
        yield RichLog(id="stream", wrap=True, markup=True, highlight=False)
        yield StatusBar()
        yield Input(id="prompt",
                    placeholder="tell Sutura what to do  (e.g. align these sections and reconstruct in 3D)")

    def on_mount(self):
        log = self.query_one("#stream", RichLog)
        log.write(f"[dim]Working folder[/dim]  {_os.getcwd()}")
        log.write("[dim]Talk to me in plain language — I'll use this folder by "
                  "default. Type[/dim] [bold]exit[/bold] [dim]to quit.[/dim]")
        log.write("")
        self.query_one("#prompt", Input).disabled = True
        self._init_session()
        if self.initial:
            self.call_after_refresh(self._submit, self.initial)

    # --- session init (off the UI thread; sets the backend line) -------- #
    @work(thread=True, exclusive=False)
    def _init_session(self):
        from ..core.llm import select_backend
        backend, _notes = select_backend(self.cfg)
        self.session = Session(self.cfg, self._Sink(self), backend=backend)
        self.call_from_thread(self._session_ready, _backend_line(backend))

    def _session_ready(self, line: str):
        self.query_one(Brand).set_backend(line)
        inp = self.query_one("#prompt", Input)
        inp.disabled = False
        inp.focus()

    # --- input handling ------------------------------------------------- #
    def on_input_submitted(self, event: Input.Submitted):
        text = event.value.strip()
        event.input.value = ""
        if text:
            self._submit(text)

    def _submit(self, text: str):
        if text.lower() in {"exit", "quit", ":q"}:
            self.exit()
            return
        log = self.query_one("#stream", RichLog)
        log.write("")
        log.write(f"[bold #a0f0d0]▸ you[/bold #a0f0d0]  {text}")
        self._pairs_open = False
        self._planned = False
        self.query_one("#prompt", Input).disabled = True
        self.query_one(StatusBar).set_working(True)
        self._run(text)

    # --- worker: blocking agent loop ------------------------------------ #
    @work(thread=True, exclusive=True)
    def _run(self, instruction: str):
        while self.session is None:      # session still initialising
            import time
            time.sleep(0.05)
        try:
            self.session.handle(instruction)
        except Exception as e:
            self.call_from_thread(self._render, Note(text=f"error: {e}", level="error"))
        self.call_from_thread(self._done)

    def _done(self):
        self.query_one("#prompt", Input).disabled = False
        self.query_one("#prompt", Input).focus()
        self.query_one(StatusBar).set_working(False)

    # --- event rendering (UI thread) ------------------------------------ #
    class _Sink:
        def __init__(self, app: "SuturaApp"):
            self._app = app

        def emit(self, ev):
            self._app.call_from_thread(self._app._render, ev)

    def _stage(self, title: str):
        self.query_one("#stream", RichLog).write(
            Rule(Text(f" {title} ", style=f"bold {_ACCENT}"),
                 characters="─", style=_RULE, align="left"))

    def _open_pairs(self):
        log = self.query_one("#stream", RichLog)
        self._stage("Alignment")
        log.write(f"  [dim]{'pair':<27}{'method':<13}{'error':>7}  "
                  f"{'routing':<11}qc[/dim]")
        self._pairs_open = True

    def _render(self, ev):
        log = self.query_one("#stream", RichLog)
        status = self.query_one(StatusBar)
        sid = getattr(ev, "step_id", "")

        # per-pair chrome is folded into the compact table; keep it out of the log
        if sid.startswith(_QUIET_PREFIXES):
            if isinstance(ev, StepProgress):
                status.set_state(ev.message, ev.pct)
            elif isinstance(ev, StepStarted):
                status.set_state(ev.detail or ev.title.lower())
            return

        if isinstance(ev, StepStarted):
            self._stage(ev.title)
            status.set_state(ev.title.lower())
        elif isinstance(ev, StepProgress):
            status.set_state(ev.message, ev.pct)
        elif isinstance(ev, RoutingDecision):
            status.set_state(f"routing {ev.pair}")          # detail goes in the row
        elif isinstance(ev, PairResult):
            if not self._pairs_open:
                self._open_pairs()
            pair = f"{_fit(ev.ref + ' → ' + ev.mov, 26):<27}"
            method = f"{_short_method(ev.method_label):<13}"
            err = (f"{ev.score:.2f}" if ev.has_ground_truth else f"{ev.score:.2f}c")
            err = f"{err:>7}"
            if ev.in_distribution is None:
                route = "forced"
            else:
                tag = "in" if ev.in_distribution else "off"
                route = f"{tag}·{ev.mahalanobis:.1f}" if ev.mahalanobis is not None else tag
            route = f"{route:<11}"
            qc = (f"[green]{ev.verdict}[/green]" if ev.verdict == "pass"
                  else f"[yellow]{ev.verdict}[/yellow]")
            log.write(f"  {pair}[{_ACCENT}]{method}[/{_ACCENT}]{err}  "
                      f"[dim]{route}[/dim]{qc}")
        elif isinstance(ev, StepFinished):
            mark = {"ok": "[green]✓[/green]", "warn": "[yellow]⚠[/yellow]",
                    "error": "[red]✗[/red]"}.get(ev.status, "[green]✓[/green]")
            log.write(f"  {mark} {ev.summary}")
        elif isinstance(ev, Note):
            colour = {"warn": "yellow", "error": "red"}.get(ev.level, "dim")
            log.write(f"  [{colour}]{ev.text}[/{colour}]")
        elif isinstance(ev, AgentMessage):
            self._agent_message(log, ev.text)
        elif isinstance(ev, BundleWritten):
            panel = completion_panel(ev.summary)
            log.write("")
            if panel is not None:
                log.write(panel)
            else:
                log.write(f"[green]✓ bundle:[/green] [dim]{ev.path}[/dim]")

    def _agent_message(self, log, text: str):
        # the "On it:" planning line is folded into a single calm dim line;
        # everything else (answers, questions) renders as an accented block
        if text.lower().startswith("on it:"):
            if not self._planned:
                self._planned = True
                log.write(f"[dim]{text.split(chr(10))[0]}[/dim]")
            return
        log.write("")
        for line in text.splitlines():
            log.write(f"[{_ACCENT2}]{line}[/{_ACCENT2}]" if line else "")


def run_tui(cfg: Config, initial_instruction: str | None = None) -> int:
    SuturaApp(cfg, initial_instruction).run()
    return 0
