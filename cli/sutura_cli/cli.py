"""`sutura` entry point.

    sutura                       launch the full-screen TUI
    sutura -H "align ./data ..." run one instruction headless (streams to stdout)
    sutura --backend ollama      pick the LLM backend (auto|cloud|ollama|rule)
"""
from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .core.agent import Session
from .core.config import Config
from .render import ConsoleSink


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sutura",
        description="Agentic, local-first spatial-transcriptomics alignment.")
    p.add_argument("instruction", nargs="?",
                   help='natural-language task, e.g. "align ./data and reconstruct in 3D"')
    p.add_argument("-H", "--headless", action="store_true",
                   help="run without the TUI, streaming steps to stdout")
    p.add_argument("--backend", default=None,
                   choices=["auto", "cloud", "ollama", "rule"],
                   help="LLM backend for the agent loop (default: auto)")
    p.add_argument("--store", default=None,
                   help="result store root (default: ~/.sutura)")
    p.add_argument("--repo", default=None,
                   help="path to the alignment engine repo (sets SUTURA_REPO)")
    p.add_argument("--version", action="version",
                   version=f"sutura {__version__}")
    return p


def _load_config(args) -> Config:
    if args.repo:
        os.environ["SUTURA_REPO"] = args.repo
    if args.store:
        os.environ["SUTURA_HOME"] = args.store
    return Config.load(backend=args.backend)


def run_headless(instruction: str, cfg: Config) -> int:
    from .render import ACCENT2, banner
    sink = ConsoleSink()
    session = Session(cfg, sink)          # backend chosen silently; model hidden
    banner(sink.console, "local · no data egress")
    sink.console.print(f"[{ACCENT2}]▸[/{ACCENT2}] [italic]{instruction}[/italic]\n")
    try:
        session.handle(instruction)
    except Exception as e:
        sink.console.print(f"\n[red]✗ error:[/red] {e}")
        return 1
    return 0


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    cfg = _load_config(args)

    if args.headless:
        if not args.instruction:
            print("error: --headless needs an instruction", file=sys.stderr)
            return 2
        return run_headless(args.instruction, cfg)

    # default: full-screen TUI (imported lazily so headless needs no textual)
    try:
        from .tui.app import run_tui
    except Exception as e:  # pragma: no cover
        print(f"could not start the TUI ({e}).\n"
              f"Use headless mode instead:  sutura -H \"...\"", file=sys.stderr)
        return 1
    return run_tui(cfg, initial_instruction=args.instruction)


if __name__ == "__main__":
    raise SystemExit(main())
