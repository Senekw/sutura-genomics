"""Full-screen Sutura TUI, styled after Claude Code: a persistent interface with
the Sutura Genomics logo top-right, a live-streaming work area, a bottom
mode/status bar, and a natural-language prompt.

The agent loop is blocking (torch / PASTE2), so it runs in a Textual worker
thread; events are marshalled back onto the UI thread via call_from_thread.
"""
from __future__ import annotations

from textual import work
from textual.app import App, ComposeResult
from textual.widgets import Input, RichLog, Static

from .. import __version__
from ..core.agent import Session
from ..core.config import Config
from ..core.events import (AgentMessage, BundleWritten, Note, RoutingDecision,
                           StepFinished, StepProgress, StepStarted)

LOGO = "S U T U R A  Genomics"

WELCOME = (
    "[bold]Welcome to Sutura[/bold] - local-first spatial-transcriptomics alignment.\n"
    "Your data never leaves this machine; the model only ever sees metadata.\n\n"
    'Try: [italic]align the sections in ./data and reconstruct in 3D[/italic]\n'
    "Then follow up, e.g. [italic]redo section 2 with PASTE2[/italic].\n"
    "Type [bold]exit[/bold] (or Ctrl-C) to quit."
)


class TopBar(Static):
    def __init__(self, cfg: Config):
        super().__init__(id="topbar")
        self._cfg = cfg

    def render(self):
        left = f"[bold]Sutura[/bold] [dim]v{__version__}[/dim]"
        right = f"[bold #6ee7ff]{LOGO}[/bold #6ee7ff]"
        # pad so the logo sits at the top-right
        width = max(self.size.width, 40)
        plain_left = f"Sutura v{__version__}"
        plain_right = LOGO
        gap = max(1, width - len(plain_left) - len(plain_right) - 2)
        return f" {left}{' ' * gap}{right} "


class StatusBar(Static):
    """Bottom mode/status bar: arrow + mode + current activity."""

    def __init__(self):
        super().__init__(id="status")
        self.mode = "manual mode"
        self.state = "idle"
        self.pct = None

    def set_state(self, state: str, pct=None):
        self.state = state
        self.pct = pct
        self.refresh()

    def render(self):
        pct = f" [{self.pct}%]" if self.pct is not None else ""
        return (f" [bold #6ee7ff]>[/bold #6ee7ff] [bold]{self.mode}[/bold] "
                f"[dim]|[/dim] {self.state}{pct}")


class SuturaApp(App):
    CSS = """
    Screen { layout: vertical; background: $surface; }
    #topbar { height: 1; background: $panel; color: $text; }
    #stream { height: 1fr; padding: 0 1; background: $surface;
              border: round $primary-darken-2; }
    #status { height: 1; background: $panel; color: $text; }
    #prompt { height: 3; border: round $primary; }
    """
    BINDINGS = [("ctrl+c", "quit", "Quit")]

    def __init__(self, cfg: Config, initial_instruction: str | None = None):
        super().__init__()
        self.cfg = cfg
        self.initial = initial_instruction
        self.session: Session | None = None

    def compose(self) -> ComposeResult:
        yield TopBar(self.cfg)
        yield RichLog(id="stream", wrap=True, markup=True, highlight=False)
        yield StatusBar()
        yield Input(id="prompt",
                    placeholder="tell Sutura what to do with your local data...")

    def on_mount(self):
        log = self.query_one("#stream", RichLog)
        log.write(WELCOME)
        log.write("")
        self.query_one("#prompt", Input).focus()
        if self.initial:
            self.call_after_refresh(self._submit, self.initial)

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
        log.write(f"[bold #a0f0d0]you>[/bold #a0f0d0] {text}")
        self.query_one("#prompt", Input).disabled = True
        self.query_one(StatusBar).set_state("working")
        self._run(text)

    # --- worker: blocking agent loop ------------------------------------ #
    @work(thread=True, exclusive=True)
    def _run(self, instruction: str):
        if self.session is None:
            self.session = Session(self.cfg, self._Sink(self))
        try:
            self.session.handle(instruction)
        except Exception as e:
            self.call_from_thread(self._render, Note(text=f"error: {e}", level="error"))
        self.call_from_thread(self._done)

    def _done(self):
        self.query_one("#prompt", Input).disabled = False
        self.query_one("#prompt", Input).focus()
        self.query_one(StatusBar).set_state("idle")

    # --- event rendering (UI thread) ------------------------------------ #
    class _Sink:
        def __init__(self, app: "SuturaApp"):
            self._app = app

        def emit(self, ev):
            self._app.call_from_thread(self._app._render, ev)

    def _render(self, ev):
        log = self.query_one("#stream", RichLog)
        status = self.query_one(StatusBar)
        if isinstance(ev, StepStarted):
            det = f" [dim]- {ev.detail}[/dim]" if ev.detail else ""
            log.write(f"[bold]> {ev.title}[/bold]{det}")
            status.set_state(ev.title.lower())
        elif isinstance(ev, StepProgress):
            status.set_state(ev.message, ev.pct)
        elif isinstance(ev, RoutingDecision):
            tag = "in-distribution" if ev.in_distribution else "off-distribution"
            log.write(f"  [cyan]route -> {ev.method}[/cyan] [dim]({tag}; "
                      f"maha {ev.mahalanobis:.2f}, overlap "
                      f"{int(ev.gene_overlap*100)}%)[/dim]")
        elif isinstance(ev, StepFinished):
            mark = {"ok": "[green]v[/green]", "warn": "[yellow]![/yellow]",
                    "error": "[red]x[/red]"}.get(ev.status, "v")
            log.write(f"{mark} {ev.summary}")
        elif isinstance(ev, Note):
            colour = {"warn": "yellow", "error": "red"}.get(ev.level, "dim")
            log.write(f"  [{colour}]{ev.text}[/{colour}]")
        elif isinstance(ev, AgentMessage):
            log.write(f"[bold cyan]{ev.text}[/bold cyan]")
        elif isinstance(ev, BundleWritten):
            log.write(f"[bold green]* bundle written:[/bold green] [dim]{ev.path}[/dim]")


def run_tui(cfg: Config, initial_instruction: str | None = None) -> int:
    SuturaApp(cfg, initial_instruction).run()
    return 0
