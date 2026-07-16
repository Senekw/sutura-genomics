"""The viewer's optional chatbot. It answers questions about ONE loaded run,
grounded strictly in that run's bundle data. It never runs alignment and never
fabricates numbers; if asked to compare a method that wasn't run, it says so and
points at the CLI. An optional local Ollama model handles free-form questions,
but it is given only the bundle facts and told to answer from them.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

_METHOD_LABELS = {
    "sutura": "Sutura (graph model)", "sutura_zeroshot": "Sutura (zero-shot)",
    "sutura_adapted": "Sutura (auto-adapted)", "paste2": "PASTE2",
}


def _pairs(run):
    return (run.get("metrics") or {}).get("pairs", []) \
        or (run.get("metadata") or {}).get("pairs", [])


def _score_txt(p):
    if p.get("has_ground_truth"):
        return f"{p['score']:.2f} spot-pitch median error"
    return f"{p['score']:.2f} footprint coverage"


def _methods_answer(run):
    out = ["Methods used in this run (each pair labelled with what produced it):"]
    for p in _pairs(run):
        out.append(f"  • {p['ref']} → {p['mov']}: {p['method_label']} "
                   f"— {_score_txt(p)}")
    return "\n".join(out)


def _why_answer(run):
    out = ["Why each method was chosen:"]
    for p in _pairs(run):
        out.append(f"  • {p['ref']} → {p['mov']}: {p.get('reason','(forced by user)')}")
    return "\n".join(out)


def _worst_answer(run):
    ps = _pairs(run)
    if not ps:
        return "This run has no aligned pairs."
    key = lambda p: p["score"] if p.get("has_ground_truth") else -p["score"]
    worst = max(ps, key=key)
    best = min(ps, key=key)
    msg = (f"Worst-aligned pair: {worst['ref']} → {worst['mov']} "
           f"({worst['method_label']}, {_score_txt(worst)}).")
    if best is not worst:
        msg += (f" Best: {best['ref']} → {best['mov']} "
                f"({best['method_label']}, {_score_txt(best)}).")
    return msg


def _compare_answer(run):
    """How PASTE2 / other methods compare - strictly from the bundle."""
    out = ["Method comparison (from what the orchestrator actually computed):"]
    for p in _pairs(run):
        cands = [(n, v) for n, v in (p.get("candidates") or [])
                 if n in _METHOD_LABELS]
        if len(cands) >= 2:
            lower_better = p.get("has_ground_truth", True)
            best = (min if lower_better else max)(cands, key=lambda kv: kv[1])[0]
            parts = [f"{_METHOD_LABELS[n]} {v:.2f}"
                     + ("  ← kept" if n == best else "") for n, v in cands]
            out.append(f"  • {p['ref']} → {p['mov']}: " + ", ".join(parts))
        else:
            out.append(
                f"  • {p['ref']} → {p['mov']}: only {p['method_label']} ran here "
                f"({_score_txt(p)}, in-distribution). PASTE2 was not run on this "
                f"pair. To compare it, run \"redo {p['mov']} with PASTE2\" in the "
                f"Sutura CLI — this viewer does not run alignment.")
    return "\n".join(out)


def _recon_answer(run):
    r = run.get("reconstruction") or {}
    if not r.get("n_points"):
        return "This run has no 3D reconstruction."
    comp = ("an exact 2-section stack" if r.get("composition") ==
            "exact_single_reference"
            else "a pairwise composition (per-pair transforms chained to the "
                 "first section's frame — not a global simultaneous solve)")
    return (f"The 3D reconstruction stacks {r['n_sections']} sections "
            f"({r['n_points']} points) as {comp}. z encodes section order, "
            f"spacing {r.get('z_spacing')}.")


def _summary_answer(run):
    m = run.get("metadata", {})
    ps = _pairs(run)
    methods = ", ".join(sorted({p["method_label"] for p in ps})) or "n/a"
    return (f"Run {m.get('job_id','?')}: {len(m.get('sections',[]))} sections, "
            f"{len(ps)} pair(s), methods: {methods}. Ask me things like "
            f"“which method and why?”, “which pair aligned worst?”, or “how does "
            f"PASTE2 compare?”.")


_INTENTS = [
    (re.compile(r"\b(compare|comparison|paste ?2|other method|versus|vs\b|how would)", re.I), _compare_answer),
    (re.compile(r"\b(why|reason|routing|choose|chose|pick)\b", re.I), _why_answer),
    (re.compile(r"\b(worst|best|which (pair|section))\b", re.I), _worst_answer),
    (re.compile(r"\b(method|methods|what.*used|which model)\b", re.I), _methods_answer),
    (re.compile(r"\b(3d|reconstruct|stack|points|volume)\b", re.I), _recon_answer),
    (re.compile(r"\b(metric|metrics|score|error|accuracy|how well|how good)\b", re.I), _methods_answer),
    (re.compile(r"\b(summary|overview|what is this|tell me about)\b", re.I), _summary_answer),
]


def answer(run: dict, question: str, use_ollama: bool = True,
           ollama_host: str = "http://localhost:11434",
           ollama_model: str | None = None) -> dict:
    """Answer a question about `run`. Returns {text, grounded, source}."""
    q = (question or "").strip()
    if not q:
        return {"text": _summary_answer(run), "source": "rules"}
    if re.search(r"\b(re-?run|re-?align|redo|align again|run alignment)\b", q, re.I):
        return {"text": "This is a display-only viewer — it doesn't run "
                        "alignment. Use the Sutura CLI to (re)align, then reopen "
                        "the run here.", "source": "rules"}
    for rx, fn in _INTENTS:
        if rx.search(q):
            return {"text": fn(run), "source": "rules"}
    # free-form: try a local model grounded in the bundle facts, else summarise
    if use_ollama:
        got = _ollama_answer(run, q, ollama_host, ollama_model)
        if got:
            return {"text": got, "source": "ollama"}
    return {"text": _summary_answer(run), "source": "rules"}


def _facts(run) -> str:
    m = run.get("metadata", {})
    facts = {
        "job_id": m.get("job_id"), "status": m.get("status"),
        "sections": [s.get("name") for s in m.get("sections", [])],
        "pairs": [{"ref": p["ref"], "mov": p["mov"],
                   "method": p.get("method_label"), "why": p.get("reason"),
                   "score": p.get("score"), "metric": p.get("metric"),
                   "candidates": p.get("candidates")} for p in _pairs(run)],
        "reconstruction": {k: (run.get("reconstruction") or {}).get(k)
                           for k in ("composition", "n_sections", "n_points")},
    }
    return json.dumps(facts, default=str)


def _ollama_answer(run, question, host, model):
    if not model:
        model = _first_model(host)
    if not model:
        return None
    system = ("You answer questions about ONE spatial-alignment run for a "
              "display-only viewer. Use ONLY the JSON facts provided. Never "
              "invent numbers. If a method wasn't run, say so and suggest the "
              "Sutura CLI. Be concise. Always name the method that produced a "
              "result. You cannot run alignment.")
    payload = {"model": model, "stream": False,
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content":
                             f"Facts:\n{_facts(run)}\n\nQuestion: {question}"}]}
    try:
        req = urllib.request.Request(
            f"{host.rstrip('/')}/api/chat", method="POST",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.loads(r.read().decode())
        return (body.get("message", {}).get("content") or "").strip() or None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _first_model(host):
    try:
        with urllib.request.urlopen(f"{host.rstrip('/')}/api/tags", timeout=2) as r:
            models = json.loads(r.read().decode()).get("models", [])
        # prefer a small instruct model
        names = [m.get("name", "") for m in models]
        for pref in ("llama3.2", "qwen2.5", "gemma3", "llama3.1"):
            for n in names:
                if n.startswith(pref):
                    return n
        return names[0] if names else None
    except (urllib.error.URLError, OSError, ValueError):
        return None
