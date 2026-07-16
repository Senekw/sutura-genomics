"""Live-progress plumbing: stream the real CLI pipeline to the browser.

A LiveHub is an in-process pub/sub with history. The CLI's event stream is
translated to small JSON messages (LiveSink) and published; the browser
subscribes over Server-Sent Events and animates each stage as it happens.

Everything shown is the REAL pipeline output — the per-pair geometry sent for the
before->after animation is the actual moving-spot coordinates (torn) and the
actual aligned coordinates the orchestrator computed. Nothing is fabricated.
"""
from __future__ import annotations

import json
import queue
import threading

_TARGET_PTS = 1600          # downsample per section for smooth animation


def _as_xy(coords):
    if coords is None:
        return None
    try:
        import numpy as np
        a = np.asarray(coords, float)
        if a.ndim != 2 or a.shape[1] < 2:
            return None
        return a[:, :2]
    except Exception:
        return None


def _idx(n, target=_TARGET_PTS):
    if n <= target:
        return list(range(n))
    step = max(1, n // target)
    return list(range(0, n, step))


def _round_list(a, idx):
    return [[round(float(a[i][0]), 1), round(float(a[i][1]), 1)] for i in idx]


def _layers_at(layers, idx):
    if layers is None:
        return None
    return [str(layers[i]) if i < len(layers) and layers[i] is not None else "NA"
            for i in idx]


class LiveHub:
    """Thread-safe SSE fan-out with replayable history for late subscribers."""

    def __init__(self):
        self._lock = threading.Lock()
        self._subs: set[queue.Queue] = set()
        self.history: list[dict] = []
        self.running = False

    def reset(self):
        with self._lock:
            self.history = []
            self.running = True

    def publish(self, msg: dict):
        with self._lock:
            self.history.append(msg)
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            for msg in self.history:      # replay backlog first
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    break
            self._subs.add(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._lock:
            self._subs.discard(q)


# canonical stage keys for the timeline
def _stage_key(step_id: str, title: str) -> str:
    s = (step_id or "").lower()
    t = (title or "").lower()
    if s.startswith("load") or "load" in t:
        return "load"
    if s.startswith("qc") or "quality" in t:
        return "qc"
    if s.startswith("route") or "distribution" in t or "routing" in t:
        return "route"
    if s.startswith("align") or t == "align":
        return "align"
    if s.startswith("postqc") or "post-align" in t:
        return "postqc"
    if s.startswith("reconstruct") or "reconstruction" in t:
        return "reconstruct"
    if s.startswith("report") or "report" in t:
        return "report"
    return s or t or "step"


def serialize(ev) -> dict | None:
    """Translate a core Event into a small JSON message for the browser."""
    kind = getattr(ev, "kind", "")
    if kind == "step_started":
        return {"type": "stage", "stage": _stage_key(ev.step_id, ev.title),
                "phase": "start", "title": ev.title, "detail": ev.detail}
    if kind == "step_finished":
        return {"type": "stage", "stage": _stage_key(ev.step_id, ""),
                "phase": "done", "status": ev.status, "summary": ev.summary,
                "step_id": ev.step_id}
    if kind == "step_progress":
        return {"type": "progress", "stage": _stage_key(ev.step_id, ""),
                "pct": ev.pct, "message": ev.message}
    if kind == "routing":
        return {"type": "routing", "pair": ev.pair, "method": ev.method,
                "in_distribution": ev.in_distribution,
                "mahalanobis": round(ev.mahalanobis, 2),
                "gene_overlap": round(ev.gene_overlap, 3), "reason": ev.reason}
    if kind == "pair_result":
        ref = _as_xy(ev.ref_coords)
        mov = _as_xy(ev.mov_coords)
        aln = _as_xy(ev.aligned_coords)
        geom = None
        if ref is not None and mov is not None and aln is not None \
                and len(mov) == len(aln):
            ri = _idx(len(ref))
            mi = _idx(len(mov))
            geom = {
                "ref": _round_list(ref, ri),
                "mov": _round_list(mov, mi),          # before (torn)
                "aligned": _round_list(aln, mi),      # after (real output)
                "ref_layers": _layers_at(ev.ref_layers, ri),
                "mov_layers": _layers_at(ev.mov_layers, mi),
            }
        return {"type": "pair", "ref": ev.ref, "mov": ev.mov,
                "method": ev.method_label, "score": round(float(ev.score), 2),
                "metric": ev.metric, "has_ground_truth": ev.has_ground_truth,
                "verdict": ev.verdict, "in_distribution": ev.in_distribution,
                "mahalanobis": (round(ev.mahalanobis, 2)
                                if ev.mahalanobis is not None else None),
                "geom": geom}
    if kind == "note":
        return {"type": "note", "level": ev.level, "text": ev.text}
    if kind == "agent_message":
        return {"type": "message", "text": ev.text}
    if kind == "bundle_written":
        return {"type": "done", "job_id": ev.job_id, "path": ev.path,
                "summary": ev.summary}
    return None


class LiveSink:
    """EventSink that serialises core events and publishes them to a LiveHub."""

    def __init__(self, hub: LiveHub):
        self.hub = hub

    def emit(self, ev):
        msg = serialize(ev)
        if msg is not None:
            self.hub.publish(msg)


def run_live(instruction: str, cfg, hub: LiveHub):
    """Run the real CLI pipeline, streaming everything to the hub. Runs in a
    worker thread started by the server; auto mode so it never blocks on a
    terminal confirmation."""
    from sutura_cli.core.agent import Session
    hub.reset()
    hub.publish({"type": "start", "instruction": instruction})
    sink = LiveSink(hub)
    try:
        session = Session(cfg, sink)
        session.mode = "auto"
        session.handle(instruction)
    except Exception as e:
        hub.publish({"type": "error", "text": f"{type(e).__name__}: {e}"})
    finally:
        hub.publish({"type": "end"})
        with hub._lock:
            hub.running = False
