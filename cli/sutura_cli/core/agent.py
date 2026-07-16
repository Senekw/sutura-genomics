"""The agent loop.

interpret (LLM/rule) -> plan -> call tools -> stream events -> write bundle.
A Session owns a WorkContext (raw data, local) and the current result Bundle.
The same Session drives both the TUI and the headless/test runner.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from . import engine, reporting, tools
from .bundle import Bundle
from .config import Config
from .context import WorkContext
from .events import (AgentMessage, BundleWritten, EventSink, Note, StepFinished,
                     StepStarted)
from .llm import Reply, ToolRequest, WorkflowRequest, select_backend
from .reconstruct import build_pointcloud


class Session:
    def __init__(self, cfg: Config, sink: EventSink, backend=None):
        self.cfg = cfg
        self.sink = sink
        cfg.ensure_dirs()
        self.ctx = WorkContext(Path(tempfile.mkdtemp(prefix="sutura-work-")))
        if backend is None:
            backend, notes = select_backend(cfg)
            for n in notes:
                sink.emit(Note(text=n, level="info"))
        self.backend = backend
        self.bundle: Bundle | None = None
        self._results: dict[int, dict] = {}   # pair index -> align result (coords)

    # ------------------------------------------------------------------ #
    def handle(self, instruction: str) -> Bundle | None:
        """Interpret one instruction and act on it. Returns the active bundle."""
        try:
            decision = self.backend.interpret(instruction, self.ctx.state_view())
        except Exception as e:
            self.sink.emit(Note(text=f"planner error ({e}); using rule backend",
                                level="warn"))
            from .llm import RuleBackend
            decision = RuleBackend().interpret(instruction, self.ctx.state_view())

        if isinstance(decision, WorkflowRequest):
            return self._workflow(instruction, decision.args)
        if isinstance(decision, ToolRequest):
            if decision.name == "realign":
                return self._realign(**decision.args)
            if decision.name == "report":
                return self._report_only()
            if decision.name == "metrics":
                return self._metrics()
            if decision.name == "worst":
                return self._worst()
            if decision.name == "explain_routing":
                return self._explain_routing(**decision.args)
            self.sink.emit(Note(text=f"unknown tool {decision.name!r}", level="warn"))
            return self.bundle
        if isinstance(decision, Reply):
            self.sink.emit(AgentMessage(text=decision.text))
            return self.bundle
        return self.bundle

    # ------------------------------------------------------------------ #
    def _workflow(self, instruction: str, args: dict) -> Bundle:
        path = args.get("path")
        self.sink.emit(AgentMessage(
            text="Planning: load sections -> QC -> routing -> align each pair "
                 "-> post-QC -> 3D reconstruct -> report. Everything runs "
                 "locally; the model only sees metadata."))

        # 1. load (skip if a path is absent but sections already loaded)
        if path or not self.ctx.sections:
            if not path:
                raise ValueError("no data path given and nothing is loaded yet")
            tools.load_data(self.ctx, self.sink, path)

        sections = self.ctx.ordered()
        if len(sections) < 2:
            n = len(sections)
            what = (f"Only {n} section loaded" if n
                    else "No sections loaded")
            self.sink.emit(AgentMessage(
                text=f"{what}. Alignment needs at least 2 adjacent sections. "
                     "Point me at a folder containing 2+ .h5ad files (or Space "
                     "Ranger outputs), e.g. "
                     '"align the sections in ./my_data and reconstruct in 3D".'))
            return self.bundle

        # start a fresh bundle for this job
        self.bundle = Bundle.create(self.cfg.results_dir, self.backend.name,
                                    engine.engine_versions(), instruction)
        self.bundle.sections = [s.meta() for s in sections]
        self.bundle.inputs = [{"path": s.source, "format": s.fmt,
                               "n_spots": s.n_spots, "n_genes": s.n_genes}
                              for s in sections]
        self._results = {}

        # 2. QC
        qc_res = tools.qc(self.ctx, self.sink)
        self.bundle.qc = qc_res["results"]
        if not qc_res["all_pass"]:
            self.bundle.warnings.append("one or more sections failed input QC")

        # 3. align each adjacent pair (one bad pair must not sink the whole job)
        for i in range(len(sections) - 1):
            ref, mov = sections[i], sections[i + 1]
            try:
                route = tools.distribution_check(self.ctx, self.sink, ref.id, mov.id)
                self.bundle.routing.append(route)
                pdir = self.bundle.pair_dir(i, ref.name, mov.name)
                result = tools.align(self.ctx, self.sink, ref.id, mov.id, out_dir=pdir)
                pq = tools.post_qc(self.ctx, self.sink, result, ref.id, mov.id)
                self._record_pair(i, ref, mov, result, pq, pdir)
            except (tools.LoaderError, tools.AlignError) as e:
                msg = f"pair {ref.name} -> {mov.name} skipped: {e}"
                self.sink.emit(Note(text=msg, level="error"))
                self.bundle.warnings.append(msg)

        if not self._results:
            self.bundle.status = "failed"
            self._finalise()
            self.sink.emit(AgentMessage(
                text="No pairs could be aligned - see the warnings above. "
                     "The bundle records what was attempted."))
            return self.bundle

        # 4. reconstruct + 5. report
        self._reconstruct()
        reporting.generate_report(self.bundle, self.sink)

        self.bundle.status = "complete"
        return self._finalise()

    # ------------------------------------------------------------------ #
    def _record_pair(self, index, ref, mov, result, post_qc, pdir):
        self._results[index] = {**result, "_ref_id": ref.id, "_mov_id": mov.id}
        rel = (pdir / "aligned.h5ad").relative_to(self.bundle.root).as_posix()
        self.bundle.add_pair({
            "index": index, "ref": ref.name, "mov": mov.name,
            "method": result["method"], "method_label": result["method_label"],
            "reason": result["reason"], "metric": result["metric"],
            "score": result["score"], "has_ground_truth": result["has_ground_truth"],
            "in_distribution": result["in_distribution"],
            "in_dist_confidence": result["in_dist_confidence"],
            "mahalanobis": result["mahalanobis"], "gene_overlap": result["gene_overlap"],
            "footprint_coverage": result["footprint_coverage"],
            "retry": result["retry"], "runtime_seconds": result["runtime_seconds"],
            "candidates": result["candidates"], "aligned_file": rel,
            "post_qc": post_qc,
        })

    def _reconstruct(self):
        idxs = sorted(self._results)
        # reconstruct the contiguous chain from the first successful pair; a gap
        # (a skipped pair) breaks frame composition, so stop the stack there
        chain = [idxs[0]]
        for i in idxs[1:]:
            if i == chain[-1] + 1:
                chain.append(i)
            else:
                break
        dropped = [i for i in idxs if i not in chain]

        pairs = []
        for i in chain:
            r = self._results[i]
            mov = self.ctx.resolve(r["_mov_id"])
            mov_coords = (mov.adata.obsm["spatial"] if mov is not None else None)
            pairs.append({
                "ref_name": r["ref_name"], "mov_name": r["mov_name"],
                "ref_coords": r["ref_coords"], "aligned_coords": r["aligned_coords"],
                "mov_coords": mov_coords,
                "ref_layers": r.get("ref_layers"), "mov_layers": r.get("mov_layers"),
                "pitch": r.get("_pitch"), "method": r["method_label"],
            })
        sid = "reconstruct"
        detail = ("stacking aligned sections" if len(chain) == 1
                  else f"composing {len(chain)}-pair chain into one frame")
        self.sink.emit(StepStarted(step_id=sid, title="3D reconstruction",
                                   detail=detail))
        rec = build_pointcloud(pairs)
        if dropped:
            gap = (f"{len(dropped)} downstream pair(s) omitted from the 3D stack: "
                   f"a pair failed and broke the chain composition")
            rec["note"] += f"; {gap}"
            rec["dropped_pairs"] = dropped
            self.bundle.warnings.append(gap)
            self.sink.emit(Note(text=gap, level="warn"))
        self.bundle.reconstruction = rec
        comp = "" if rec.get("composition") == "exact_single_reference" \
            else f" ({rec.get('composition')})"
        self.sink.emit(StepFinished(
            step_id=sid, status="ok",
            summary=f"{rec['n_sections']} sections, {rec['n_points']} points{comp}"))

    def _finalise(self) -> Bundle:
        root = self.bundle.write()
        self.sink.emit(BundleWritten(job_id=self.bundle.job_id, path=str(root),
                                     summary=self.bundle.summary()))
        methods = ", ".join(self.bundle.summary()["methods"]) or "n/a"
        self.sink.emit(AgentMessage(
            text=f"Results written to {root}\nMethods used: {methods}. "
                 f"Open in the Sutura app to view the 3D model. "
                 f'You can also say e.g. "redo section 2 with PASTE2".'))
        return self.bundle

    # ------------------------------------------------------------------ #
    def _realign(self, section: str | None = None, method: str | None = None) -> Bundle:
        if self.bundle is None or not self._results:
            self.sink.emit(AgentMessage(
                text="Nothing has been aligned yet - run an alignment first."))
            return self.bundle

        # find the target pair (by the moving section, else the last pair)
        idx = None
        if section is not None:
            tgt = self.ctx.resolve(section)
            for i, r in self._results.items():
                if tgt is not None and r["_mov_id"] == tgt.id:
                    idx = i
                    break
                if r["mov_name"] == section or r["ref_name"] == section:
                    idx = i
                    break
        if idx is None:
            idx = max(self._results)

        cur = self._results[idx]
        if method is None:      # switch to the other method
            method = "sutura" if "PASTE2" in cur["method_label"] else "paste2"
        ref_id, mov_id = cur["_ref_id"], cur["_mov_id"]
        ref, mov = self.ctx.resolve(ref_id), self.ctx.resolve(mov_id)
        self.sink.emit(AgentMessage(
            text=f"Re-aligning {ref.name} -> {mov.name} with "
                 f"{method.upper()} (was {cur['method_label']})."))

        pdir = self.bundle.pair_dir(idx, ref.name, mov.name)
        result = tools.align(self.ctx, self.sink, ref_id, mov_id,
                             out_dir=pdir, force_method=method)
        pq = tools.post_qc(self.ctx, self.sink, result, ref_id, mov_id)
        self._record_pair(idx, ref, mov, result, pq, pdir)
        self._reconstruct()
        reporting.generate_report(self.bundle, self.sink)
        self.bundle.status = "complete"
        return self._finalise()

    def _report_only(self) -> Bundle:
        if self.bundle is None:
            self.sink.emit(AgentMessage(text="No job to report on yet."))
            return self.bundle
        reporting.generate_report(self.bundle, self.sink)
        self.bundle.write()
        self.sink.emit(AgentMessage(text=f"Report refreshed: "
                                    f"{self.bundle.root / 'report.md'}"))
        return self.bundle

    # --- read-only queries over the current job (no re-run) ------------- #
    def _no_job(self) -> bool:
        if self.bundle is None or not self.bundle.pairs:
            self.sink.emit(AgentMessage(
                text="No alignment job yet - run one first, e.g. "
                     '"align the sections in ./data and reconstruct in 3D".'))
            return True
        return False

    @staticmethod
    def _score_txt(p: dict) -> str:
        if p.get("has_ground_truth"):
            return f"{p['score']:.2f} spot-pitch median error (measured vs ground truth)"
        return f"{p['score']:.2f} footprint coverage (proxy; no ground truth)"

    def _metrics(self) -> Bundle:
        if self._no_job():
            return self.bundle
        lines = [f"Metrics for job {self.bundle.job_id} "
                 f"({len(self.bundle.pairs)} pair(s)):"]
        for p in self.bundle.pairs:
            pq = (p.get("post_qc") or {}).get("verdict", "?")
            lines.append(f"  - {p['ref']} -> {p['mov']}: {p['method_label']} | "
                         f"{self._score_txt(p)} | post-QC: {pq}")
        self.sink.emit(AgentMessage(text="\n".join(lines)))
        return self.bundle

    def _worst(self) -> Bundle:
        if self._no_job():
            return self.bundle

        def badness(p):
            # higher = worse. error: bigger is worse; coverage: smaller is worse.
            return p["score"] if p.get("has_ground_truth") else -p["score"]

        ordered = sorted(self.bundle.pairs, key=badness, reverse=True)
        worst, best = ordered[0], ordered[-1]
        msg = [f"Worst-aligned pair: {worst['ref']} -> {worst['mov']} "
               f"({worst['method_label']}, {self._score_txt(worst)})."]
        if best is not worst:
            msg.append(f"Best-aligned pair: {best['ref']} -> {best['mov']} "
                       f"({best['method_label']}, {self._score_txt(best)}).")
        if not worst.get("has_ground_truth"):
            msg.append("Note: no ground truth for these pairs, so 'worst' is by "
                       "footprint-coverage proxy, not measured error.")
        self.sink.emit(AgentMessage(text=" ".join(msg)))
        return self.bundle

    def _explain_routing(self, section: str | None = None) -> Bundle:
        if self._no_job():
            return self.bundle
        pairs = self.bundle.pairs
        if section is not None:
            tgt = self.ctx.resolve(section)
            sel = [p for p in pairs
                   if (tgt and tgt.name in (p["ref"], p["mov"]))
                   or section in (p["ref"], p["mov"])]
            pairs = sel or pairs
        lines = ["Routing decisions (why each method was chosen):"]
        for p in pairs:
            if p.get("in_distribution") is None:
                lines.append(f"  - {p['ref']} -> {p['mov']}: {p['method_label']} "
                             f"was forced by you (routing bypassed).")
                continue
            maha, thr = p.get("mahalanobis"), 2.5
            overlap = p.get("gene_overlap")
            if p["in_distribution"]:
                why = (f"in-distribution for the pretrained Sutura model "
                       f"(Mahalanobis {maha:.2f} < {thr}); the graph model is most "
                       f"accurate here, so Sutura was used.")
            else:
                why = (f"off-distribution (Mahalanobis {maha:.2f} >= {thr}"
                       + (f", gene overlap {int(overlap*100)}%" if overlap is not None else "")
                       + "); the pretrained model is not trusted here, so the "
                       "orchestrator kept the best of auto-adapted Sutura and PASTE2.")
            lines.append(f"  - {p['ref']} -> {p['mov']}: routed to "
                         f"{p['method_label']} because it is {why}")
        self.sink.emit(AgentMessage(text="\n".join(lines)))
        return self.bundle
