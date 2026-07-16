"""generate_report: turn an accumulated Bundle into report.md.

The report is deliberately honest: it names the method that produced each pair's
alignment and why, and it never claims Sutura beats every method everywhere.
"""
from __future__ import annotations

from .bundle import Bundle
from .events import EventSink, StepFinished, StepStarted


_CAND_LABEL = {
    "sutura": "Sutura (graph model)", "sutura_zeroshot": "Sutura (zero-shot)",
    "sutura_adapted": "Sutura (auto-adapted)", "paste2": "PASTE2",
}


def _fmt_score(p: dict) -> str:
    if p.get("has_ground_truth"):
        return f"{p['score']:.2f} spot-pitch median error (measured vs ground truth)"
    return f"{p['score']:.2f} footprint coverage (no ground truth; proxy)"


def _candidate_lines(p: dict) -> list[str]:
    """Honest breakdown of the methods the orchestrator compared for a pair."""
    cands = p.get("candidates") or []
    methods = [(n, v) for n, v in cands if n in _CAND_LABEL]
    epochs = next((v for n, v in cands if n == "auto_adapt_epochs"), None)
    if len(methods) < 2:      # nothing to compare (in-distribution single method)
        return []
    lower_better = p.get("has_ground_truth", True)
    best = (min if lower_better else max)(methods, key=lambda kv: kv[1])[0]
    unit = "spot-pitch error" if lower_better else "coverage"
    out = ["- **Methods compared** (best kept):"]
    if epochs is not None:
        out.append(f"    - auto-adapt fine-tuned the model for {epochs} epochs on your data")
    for name, val in methods:
        mark = "  <- kept" if name == best else ""
        out.append(f"    - {_CAND_LABEL[name]}: {val:.2f} {unit}{mark}")
    return out


def build_report_md(bundle: Bundle) -> str:
    L = []
    L.append(f"# Sutura alignment report\n")
    L.append(f"- **Job:** `{bundle.job_id}`")
    L.append(f"- **Created:** {bundle.created}")
    L.append(f"- **Agent backend:** {bundle.backend}")
    if bundle.instruction:
        L.append(f"- **Request:** {bundle.instruction}")
    L.append(f"- **Sections:** {len(bundle.sections)}"
             f"  |  **Pairs aligned:** {len(bundle.pairs)}")
    L.append("")

    L.append("## Sections\n")
    L.append("| # | name | format | spots | genes | layers |")
    L.append("|---|------|--------|------:|------:|:------:|")
    for i, s in enumerate(bundle.sections, 1):
        L.append(f"| {i} | {s['name']} | {s['format']} | {s['n_spots']} | "
                 f"{s['n_genes']} | {'yes' if s['has_layers'] else 'no'} |")
    L.append("")

    L.append("## Alignment (method used per pair)\n")
    for p in bundle.pairs:
        L.append(f"### {p['ref']} -> {p['mov']}")
        L.append(f"- **Method:** {p['method_label']}")
        L.append(f"- **Why:** {p.get('reason','')}")
        L.append(f"- **Result:** {_fmt_score(p)}")
        L.extend(_candidate_lines(p))
        if p.get("in_distribution") is not None:
            L.append(f"- **Routing:** "
                     f"{'in-distribution' if p['in_distribution'] else 'off-distribution'}"
                     f" (confidence {p.get('in_dist_confidence')})")
        pq = p.get("post_qc") or {}
        if pq:
            L.append(f"- **Post-QC:** {pq.get('verdict','?')} - {pq.get('basis','')}")
        if p.get("retry"):
            L.append("- **Note:** a post-QC retry changed the chosen method.")
        L.append("")

    rec = bundle.reconstruction or {}
    if rec.get("n_points"):
        L.append("## 3D reconstruction\n")
        L.append(f"- **Kind:** {rec.get('kind')} - {rec.get('note','')}")
        L.append(f"- **Sections stacked:** {rec.get('n_sections')}  |  "
                 f"**points:** {rec.get('n_points')}  |  "
                 f"**z-spacing:** {rec.get('z_spacing')}")
        L.append("")

    L.append("## Honesty note\n")
    L.append("Alignment quality is bounded by the orchestrator. Sutura's graph "
             "model wins in-distribution; PASTE2 is preferred off-distribution. "
             "Each result above is labelled with the method that actually "
             "produced it. This tool automates *best-available* alignment; it "
             "does not claim to beat every method on every tissue.")
    L.append("")
    L.append(f"Open this job in the Sutura app: `{bundle.root}`")
    return "\n".join(L) + "\n"


def generate_report(bundle: Bundle, sink: EventSink) -> str:
    sid = "report"
    sink.emit(StepStarted(step_id=sid, title="Generate report",
                          detail="summarising results"))
    md = build_report_md(bundle)
    bundle.report_md = md
    sink.emit(StepFinished(step_id=sid, status="ok",
                           summary=f"report.md ({len(md.splitlines())} lines)"))
    return md
