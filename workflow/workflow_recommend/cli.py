"""workflow-recommend CLI.

Examples
--------
    workflow-recommend "3D organ mapping of human kidney, 10x Visium, 12 serial sections, want cell types and spatial domains"
    workflow-recommend --format text "Xenium breast tumor, one section, cell types and niches"
    echo "MERSCOPE developmental time series, 4 timepoints" | workflow-recommend -
    workflow-recommend --spec-only "CosMx lung, disease vs control, 6 donors"
    workflow-recommend --list-tools
    workflow-recommend --list-platforms
"""
from __future__ import annotations

import argparse
import json
import sys

from .knowledge_base import load_kb
from .parser import parse_experiment
from .recommender import build_pipeline
from .render import render


def _pipeline_to_dict(pipe) -> dict:
    return {
        "spec": pipe.spec.to_dict(),
        "warnings": pipe.warnings,
        "steps": [
            {
                "step_id": s.step_id,
                "name": s.name,
                "order": s.order,
                "reason": s.reason,
                "expert_judgment": s.expert_judgment,
                "unsolved": s.unsolved,
                "expert_note": s.expert_note,
                "primary": s.primary.id if s.primary else None,
                "refinements": [r.id for r in s.refinements],
                "alternatives": [a.id for a in s.alternatives],
                "warnings": s.warnings,
            }
            for s in pipe.steps
        ],
    }


def _list_tools() -> str:
    kb = load_kb()
    lines = ["Knowledge-base tools (by step):", ""]
    for step_id in kb.ordered_step_ids():
        tools = kb.tools_for_step(step_id)
        if not tools:
            continue
        lines.append(f"{kb.steps[step_id]['name']}:")
        for t in tools:
            plats = ", ".join(t.get("platforms", []))
            lines.append(f"  - {t['name']:28s} [{t.get('maturity','?'):11s}] platforms: {plats}")
        lines.append("")
    return "\n".join(lines)


def _list_platforms() -> str:
    kb = load_kb()
    lines = ["Supported platforms:", ""]
    for pid, p in kb.platforms.items():
        seg = "segmentation" if p.get("needs_segmentation") else "no-segmentation"
        dec = p.get("needs_deconvolution")
        dec = "deconvolution" if dec is True else ("deconv-optional" if dec == "optional" else "no-deconv")
        lines.append(f"  {pid:12s} {p['name']:28s} ({p['modality']}; {seg}; {dec})")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="workflow-recommend",
        description="Recommend a concrete, honest spatial/single-cell analysis pipeline "
                    "for a described experiment. Grounded in real, existing tools.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("description", nargs="?",
                   help="Experiment description in natural language. Use '-' to read from stdin.")
    p.add_argument("-f", "--format", choices=["markdown", "md", "text", "txt", "json"],
                   default="markdown", help="Output format (default: markdown).")
    p.add_argument("--spec-only", action="store_true",
                   help="Only print the parsed experiment spec (what the tool understood).")
    p.add_argument("--list-tools", action="store_true", help="List knowledge-base tools and exit.")
    p.add_argument("--list-platforms", action="store_true", help="List supported platforms and exit.")
    p.add_argument("-o", "--output", help="Write the report to a file instead of stdout.")
    return p


def main(argv: list[str] | None = None) -> int:
    # Markdown reports contain a couple of decorative non-ASCII glyphs. On a legacy
    # Windows console (cp1252) printing them would crash, so make stdout tolerant.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    args = build_parser().parse_args(argv)

    if args.list_tools:
        print(_list_tools())
        return 0
    if args.list_platforms:
        print(_list_platforms())
        return 0

    description = args.description
    if description == "-" or (description is None and not sys.stdin.isatty()):
        description = sys.stdin.read()
    if not description or not description.strip():
        build_parser().print_help()
        return 2

    spec = parse_experiment(description)

    if args.spec_only:
        out = json.dumps(spec.to_dict(), indent=2)
    else:
        pipe = build_pipeline(spec)
        if args.format == "json":
            out = json.dumps(_pipeline_to_dict(pipe), indent=2)
        else:
            fmt = "text" if args.format in ("text", "txt") else "markdown"
            out = render(pipe, fmt=fmt)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(out + ("\n" if not out.endswith("\n") else ""))
        print(f"wrote {args.output}")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
