"""Render a recommended Pipeline into human-readable markdown or plain text."""
from __future__ import annotations

from .knowledge_base import load_kb
from .pipeline import Pipeline, PipelineStep, ToolChoice


def _tool_block(choice: ToolChoice, md: bool) -> list[str]:
    t = choice.tool
    lines: list[str] = []
    tag = {"primary": "Recommended", "alternative": "Alternative", "refinement": "Optional refinement"}[choice.role]
    head = f"{tag}: {t['name']}  ({t.get('language', '?')}, maturity: {t.get('maturity', '?')})"
    lines.append(f"**{head}**" if md else head)
    if choice.context_note:
        lines.append(f"  - Scope: {choice.context_note}")
    if choice.role == "primary":
        lines.append(f"  - Why: {t.get('why', '').strip()}")
        lines.append(f"  - Install: `{t.get('install', 'n/a')}`" if md else f"  - Install: {t.get('install', 'n/a')}")
        code = t.get("code", "").rstrip()
        if code:
            if md:
                lang = t.get("language", "")
                lang = {"python": "python", "r": "r", "julia": "julia", "rust": "bash"}.get(lang, "")
                lines.append("  - Run:")
                lines.append("")
                lines.append("```" + lang)
                lines.append(code)
                lines.append("```")
            else:
                lines.append("  - Run:")
                for cl in code.splitlines():
                    lines.append("      " + cl)
        lines.append(f"  - Expected runtime: {t.get('runtime', 'unknown')}")
        lines.append(f"  - Known limitations: {t.get('limitations', '').strip()}")
        if t.get("url") and t["url"] != "internal":
            lines.append(f"  - Docs: {t['url']}")
    else:
        # concise for alternatives/refinements
        note = t.get("why", "").strip()
        if choice.role == "alternative":
            lines.append(f"  - {note}")
            lines.append(f"    Install: `{t.get('install', 'n/a')}`" if md else f"    Install: {t.get('install', 'n/a')}")
    return lines


def _step_block(idx: int, step: PipelineStep, md: bool) -> list[str]:
    lines: list[str] = []
    flags = []
    if step.unsolved:
        flags.append("UNSOLVED — expert judgment required")
    elif step.expert_judgment:
        flags.append("expert judgment required")
    flag_str = f"  [{'; '.join(flags)}]" if flags else ""

    title = f"Step {idx}: {step.name}{flag_str}"
    lines.append(f"### {title}" if md else f"{'=' * 70}\n{title}\n{'=' * 70}")
    lines.append("")
    lines.append(f"_Purpose:_ {step.purpose}" if md else f"Purpose: {step.purpose}")
    lines.append(f"_Why here:_ {step.reason}" if md else f"Why here: {step.reason}")
    lines.append("")

    if step.expert_note:
        prefix = "> **HONESTY:** " if md else "!! HONESTY: "
        lines.append(prefix + step.expert_note)
        lines.append("")

    if step.primary:
        lines.extend(_tool_block(step.primary, md))
        lines.append("")
    for r in step.refinements:
        lines.extend(_tool_block(r, md))
        lines.append("")
    if step.alternatives:
        lines.append("_Alternatives:_" if md else "Alternatives:")
        for a in step.alternatives:
            lines.extend(_tool_block(a, md))
        lines.append("")
    if not step.primary and not step.alternatives:
        lines.append("_(No tool in the knowledge base matched this step for this platform.)_")
        lines.append("")

    for w in step.warnings:
        lines.append((f"> ⚠️ {w}") if md else f"  [!] {w}")
    if step.warnings:
        lines.append("")
    return lines


def _spec_summary(pipe: Pipeline, md: bool) -> list[str]:
    s = pipe.spec
    kb = load_kb()
    plat = kb.platforms.get(s.platform, {}).get("name", s.platform or "unknown")
    etype = kb.experiment_types.get(s.experiment_type, {}).get("name", s.experiment_type)
    goals = sorted(s.goals)
    inferred = sorted(s.goals_inferred)
    ref = {True: "yes", False: "no", None: "not stated"}[s.has_reference]

    rows = [
        ("Platform", f"{plat} (confidence: {s.platform_confidence})"),
        ("Experiment type", f"{etype} (confidence: {s.experiment_type_confidence})"),
        ("Tissue", s.tissue or "not detected"),
        ("Serial sections", f"yes ({s.n_sections})" if s.serial_sections else "no"),
        ("Samples/donors/conditions", str(s.n_samples) if s.n_samples else "not detected"),
        ("Stated goals", ", ".join(goals) if goals else "none explicit"),
        ("Inferred goals", ", ".join(inferred) if inferred else "none"),
        ("Single-cell reference", ref),
    ]
    lines = []
    if md:
        lines.append("## What we understood from your description")
        lines.append("")
        lines.append("| Field | Value |")
        lines.append("|---|---|")
        for k, v in rows:
            lines.append(f"| {k} | {v} |")
    else:
        lines.append("WHAT WE UNDERSTOOD FROM YOUR DESCRIPTION")
        lines.append("-" * 70)
        for k, v in rows:
            lines.append(f"  {k:28s}: {v}")
    lines.append("")
    if s.notes:
        lines.append("_Parse notes:_" if md else "Parse notes:")
        for n in s.notes:
            lines.append(f"- {n}" if md else f"  - {n}")
        lines.append("")
    return lines


def render(pipe: Pipeline, fmt: str = "markdown") -> str:
    md = fmt in ("markdown", "md")
    out: list[str] = []

    if md:
        out.append("# Recommended pipeline")
        out.append("")
        out.append(f"> Input: _{pipe.spec.raw_text.strip()}_")
        out.append("")
    else:
        out.append("RECOMMENDED PIPELINE")
        out.append("=" * 70)
        out.append(f"Input: {pipe.spec.raw_text.strip()}")
        out.append("")

    out.extend(_spec_summary(pipe, md))

    # ordered step overview
    if md:
        out.append("## Pipeline at a glance")
        out.append("")
        for i, st in enumerate(pipe.steps, 1):
            tool = st.primary.name if st.primary else "(no tool)"
            flag = " ⚠️" if (st.unsolved or st.expert_judgment) else ""
            out.append(f"{i}. **{st.name}** → {tool}{flag}")
        out.append("")
    else:
        out.append("PIPELINE AT A GLANCE")
        out.append("-" * 70)
        for i, st in enumerate(pipe.steps, 1):
            tool = st.primary.name if st.primary else "(no tool)"
            flag = " [expert]" if (st.unsolved or st.expert_judgment) else ""
            out.append(f"  {i}. {st.name} -> {tool}{flag}")
        out.append("")

    if pipe.warnings:
        out.append("## Read this first" if md else "READ THIS FIRST")
        if not md:
            out.append("-" * 70)
        out.append("")
        for w in pipe.warnings:
            out.append(f"> ⚠️ {w}" if md else f"  [!] {w}")
        out.append("")

    out.append("## Detailed steps" if md else "DETAILED STEPS")
    if not md:
        out.append("")
    out.append("")
    for i, st in enumerate(pipe.steps, 1):
        out.extend(_step_block(i, st, md))

    # closing honesty footer
    footer = (
        "This recommendation orchestrates existing, real tools; it does not replace them or "
        "guarantee their output. Segmentation, batch correction, alignment, annotation, and "
        "deconvolution all have failure modes flagged above and require expert visual QC. Treat "
        "this as a starting scaffold, validate each step against your biology, and confirm tool "
        "versions/APIs before running."
    )
    if md:
        out.append("---")
        out.append(f"_{footer}_")
    else:
        out.append("=" * 70)
        out.append(footer)
    return "\n".join(out).rstrip() + "\n"
