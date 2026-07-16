"""Full-screen Sutura TUI — a calm, designed terminal assistant for spatial
alignment. Purple / black / white theme, an ASCII DNA mark top-left, stage-
separated work blocks, a compact per-pair table, and an auto/manual safety mode
that confirms before touching the user's files.

The agent loop is blocking (torch / PASTE2), so it runs in a Textual worker
thread; events are marshalled back onto the UI thread via call_from_thread.
Confirmations block the worker on a threading.Event until the user answers.
"""
from __future__ import annotations

import os as _os
import threading

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

# --- purple / black / white palette --------------------------------------- #
PURPLE = "#b78bff"      # primary accent
PURPLE_HI = "#d9c4ff"   # bright highlight
PURPLE_DK = "#2a2340"   # dividers / borders
INK = "#08080c"         # near-black background
PAPER = "#f0eefb"       # near-white text
MUTE = "#8a86a8"        # muted text
GOOD = "#7ef0b0"
WARN = "#ffcc66"
BAD = "#ff6b8a"

_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_QUIET_PREFIXES = ("route", "align:", "postqc:")

# compact ASCII DNA double-helix mark (base pairs crossing)
_LOGO = [
    "●╲ ╱●",
    " ╲╳╱ ",
    " ╱╳╲ ",
    "●╱ ╲●",
]


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
    """Fixed top-left header: ASCII DNA mark + SUTURA wordmark + tagline.
    No backend/model is shown — it runs locally under the hood."""

    def render(self):
        w = "SUTURA"
        tag = "spatial-transcriptomics alignment assistant"
        note = "local · no data egress"
        rows = [
            f"[{PURPLE}]{_LOGO[0]}[/{PURPLE}]",
            f"[{PURPLE}]{_LOGO[1]}[/{PURPLE}]   [bold {PAPER}]{w}[/bold {PAPER}]"
            f"   [{MUTE}]{tag}[/{MUTE}]",
            f"[{PURPLE}]{_LOGO[2]}[/{PURPLE}]   [{MUTE}]{note}[/{MUTE}]",
            f"[{PURPLE}]{_LOGO[3]}[/{PURPLE}]",
        ]
        return "\n".join(rows)


class StatusBar(Static):
    """Bottom bar: mode (auto/manual) + activity + spinner."""

    def __init__(self):
        super().__init__(id="status")
        self.mode = "manual"
        self.state = "ready"
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
        self.state = "working" if working else "ready"
        self.pct = None
        self.refresh()

    def set_mode(self, mode: str):
        self.mode = mode
        self.refresh()

    def render(self):
        pct = f" [{self.pct}%]" if self.pct is not None else ""
        spin = (f"[{PURPLE}]{_SPINNER[self._spin]}[/{PURPLE}] " if self.working
                else f"[{GOOD}]●[/{GOOD}] ")
        mode_col = GOOD if self.mode == "auto" else PURPLE
        mode_txt = ("auto — runs without asking" if self.mode == "auto"
                    else "manual — confirms before file access")
        return (f" [bold {mode_col}]▸ {self.mode} mode[/bold {mode_col}] "
                f"[{MUTE}]({mode_txt})[/{MUTE}]  [{PURPLE_DK}]│[/{PURPLE_DK}]  "
                f"{spin}{self.state}{pct}   [{MUTE}]f2 toggle mode[/{MUTE}]")


class SuturaApp(App):
    CSS = f"""
    Screen {{ layout: vertical; background: {INK}; color: {PAPER}; }}
    #brand {{ height: 5; padding: 1 0 0 2; background: {INK}; color: {PAPER}; }}
    #stream {{ height: 1fr; padding: 0 2; margin: 0 1; background: {INK};
               color: {PAPER}; scrollbar-color: {PURPLE_DK}; }}
    #status {{ height: 1; background: #100e18; color: {PAPER}; }}
    #prompt {{ height: 3; border: round {PURPLE_DK}; background: {INK};
               color: {PAPER}; margin: 0 1 1 1; }}
    #prompt:focus {{ border: round {PURPLE}; }}
    """
    BINDINGS = [("ctrl+c", "quit", "Quit"), ("f2", "toggle_mode", "Mode")]

    def __init__(self, cfg: Config, initial_instruction: str | None = None):
        super().__init__()
        self.cfg = cfg
        self.initial = initial_instruction
        self.session: Session | None = None
        self.mode = "manual"
        self._pairs_open = False
        self._planned = False
        self._confirm_ev: threading.Event | None = None
        self._confirm_result = False

    def compose(self) -> ComposeResult:
        yield Brand()
        yield RichLog(id="stream", wrap=True, markup=True, highlight=False)
        yield StatusBar()
        yield Input(id="prompt",
                    placeholder="tell your alignment assistant what to do  "
                                "(e.g. align these sections and reconstruct in 3D)")

    def on_mount(self):
        log = self.query_one("#stream", RichLog)
        log.write(f"[{PAPER}]I'm your spatial-transcriptomics alignment "
                  f"assistant.[/{PAPER}] [{MUTE}]Everything runs on this machine; "
                  f"your data never leaves it.[/{MUTE}]")
        log.write(f"[{MUTE}]Working folder[/{MUTE}]  {_os.getcwd()}")
        log.write(f"[{MUTE}]Just name a file or folder and tell me what to do — "
                  f"e.g.[/{MUTE}] [{PURPLE_HI}]align these sections and reconstruct "
                  f"in 3D[/{PURPLE_HI}][{MUTE}].  Type[/{MUTE}] [bold]exit[/bold] "
                  f"[{MUTE}]to quit.[/{MUTE}]")
        log.write("")
        self.query_one("#prompt", Input).disabled = True
        self.query_one(StatusBar).set_mode(self.mode)
        self._init_session()
        if self.initial:
            self.call_after_refresh(self._submit, self.initial)

    # --- session init (off the UI thread) ------------------------------- #
    @work(thread=True, exclusive=False)
    def _init_session(self):
        from ..core.llm import select_backend
        backend, _notes = select_backend(self.cfg)          # silent; model hidden
        self.session = Session(self.cfg, self._Sink(self), backend=backend)
        self.session.mode = self.mode
        self.session.on_confirm = self._confirm
        self.call_from_thread(self._session_ready)

    def _session_ready(self):
        inp = self.query_one("#prompt", Input)
        inp.disabled = False
        inp.focus()

    # --- mode toggle ---------------------------------------------------- #
    def action_toggle_mode(self):
        self._set_mode("auto" if self.mode == "manual" else "manual")

    def _set_mode(self, mode: str):
        self.mode = mode
        if self.session:
            self.session.mode = mode
        self.query_one(StatusBar).set_mode(mode)
        self.query_one("#stream", RichLog).write(
            f"[{PURPLE}]▸[/{PURPLE}] switched to [bold]{mode} mode[/bold]" +
            (f" [{MUTE}]— I'll run without asking[/{MUTE}]" if mode == "auto"
             else f" [{MUTE}]— I'll confirm before reading your files[/{MUTE}]"))

    # --- input handling ------------------------------------------------- #
    def on_input_submitted(self, event: Input.Submitted):
        text = event.value.strip()
        event.input.value = ""
        # answering a pending confirmation
        if self._confirm_ev is not None:
            self._confirm_result = text.lower().startswith("y")
            self.query_one("#stream", RichLog).write(
                f"[{MUTE}]▸ {text or 'n'}[/{MUTE}]")
            self.query_one("#prompt", Input).disabled = True
            self._confirm_ev.set()
            return
        if text:
            self._submit(text)

    def _submit(self, text: str):
        low = text.lower().strip()
        if low in {"exit", "quit", ":q"}:
            self.exit()
            return
        if low in {"auto", "auto mode", "/auto"}:
            self._set_mode("auto")
            return
        if low in {"manual", "manual mode", "/manual"}:
            self._set_mode("manual")
            return
        log = self.query_one("#stream", RichLog)
        log.write("")
        log.write(f"[bold {PURPLE_HI}]▸ you[/bold {PURPLE_HI}]  {text}")
        self._pairs_open = False
        self._planned = False
        self.query_one("#prompt", Input).disabled = True
        self.query_one(StatusBar).set_working(True)
        self._run(text)

    # --- confirmation (called from worker thread) ----------------------- #
    def _confirm(self, prompt: str) -> bool:
        ev = threading.Event()
        self._confirm_ev = ev
        self._confirm_result = False
        self.call_from_thread(self._ask_confirm, prompt)
        ev.wait()
        self._confirm_ev = None
        return self._confirm_result

    def _ask_confirm(self, prompt: str):
        log = self.query_one("#stream", RichLog)
        log.write(f"[{PURPLE}]?[/{PURPLE}] [{PAPER}]{prompt}[/{PAPER}] "
                  f"[{MUTE}]\\[y/n][/{MUTE}]")
        self.query_one(StatusBar).set_state("waiting for confirmation — y / n")
        inp = self.query_one("#prompt", Input)
        inp.disabled = False
        inp.focus()

    # --- worker: blocking agent loop ------------------------------------ #
    @work(thread=True, exclusive=True)
    def _run(self, instruction: str):
        import time
        while self.session is None:
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
            Rule(Text(f" {title} ", style=f"bold {PURPLE}"),
                 characters="─", style=PURPLE_DK, align="left"))

    def _open_pairs(self):
        log = self.query_one("#stream", RichLog)
        self._stage("Alignment")
        log.write(f"  [{MUTE}]{'pair':<27}{'method':<13}{'error':>7}  "
                  f"{'routing':<11}qc[/{MUTE}]")
        self._pairs_open = True

    def _render(self, ev):
        log = self.query_one("#stream", RichLog)
        status = self.query_one(StatusBar)
        sid = getattr(ev, "step_id", "")
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
            status.set_state(f"routing {ev.pair}")
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
            qc = (f"[{GOOD}]{ev.verdict}[/{GOOD}]" if ev.verdict == "pass"
                  else f"[{WARN}]{ev.verdict}[/{WARN}]")
            log.write(f"  {pair}[{PURPLE}]{method}[/{PURPLE}]{err}  "
                      f"[{MUTE}]{route}[/{MUTE}]{qc}")
        elif isinstance(ev, StepFinished):
            mark = {"ok": f"[{GOOD}]✓[/{GOOD}]", "warn": f"[{WARN}]⚠[/{WARN}]",
                    "error": f"[{BAD}]✗[/{BAD}]"}.get(ev.status, f"[{GOOD}]✓[/{GOOD}]")
            log.write(f"  {mark} {ev.summary}")
        elif isinstance(ev, Note):
            colour = {"warn": WARN, "error": BAD}.get(ev.level, MUTE)
            log.write(f"  [{colour}]{ev.text}[/{colour}]")
        elif isinstance(ev, AgentMessage):
            self._agent_message(log, ev.text)
        elif isinstance(ev, BundleWritten):
            panel = completion_panel(ev.summary)
            log.write("")
            if panel is not None:
                log.write(panel)
            else:
                log.write(f"[{GOOD}]✓ bundle:[/{GOOD}] [{MUTE}]{ev.path}[/{MUTE}]")

    def _agent_message(self, log, text: str):
        if text.lower().startswith("on it:"):
            if not self._planned:
                self._planned = True
                log.write(f"[{MUTE}]{text.splitlines()[0]}[/{MUTE}]")
            return
        log.write("")
        for line in text.splitlines():
            log.write(f"[{PURPLE_HI}]{line}[/{PURPLE_HI}]" if line else "")


def run_tui(cfg: Config, initial_instruction: str | None = None) -> int:
    SuturaApp(cfg, initial_instruction).run()
    return 0
