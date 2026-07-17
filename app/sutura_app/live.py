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
import os
import queue
import threading
import time

_TARGET_PTS = 1600          # downsample per section for smooth animation

# --- live-run watchdog defaults (overridable via env) ------------------- #
# No event from the pipeline for this many seconds => the current stage is
# considered stalled and an error is surfaced (instead of hanging forever).
# Kept ABOVE the per-pair alignment timeout (SUTURA_ALIGN_TIMEOUT, default 150s)
# so a single wedged pair is skipped-and-continued first; this is the backstop
# for a stall that a per-pair skip can't reach (e.g. a one-pair run, or a hang
# in load/QC/reconstruct).
_STAGE_TIMEOUT = float(os.environ.get("SUTURA_LIVE_STAGE_TIMEOUT", "240"))
# Hard cap on the whole run, a backstop for a pipeline that never returns.
_RUN_TIMEOUT = float(os.environ.get("SUTURA_LIVE_RUN_TIMEOUT", "5400"))
# How often the supervisor emits a heartbeat (browser + terminal liveness).
_HEARTBEAT_EVERY = float(os.environ.get("SUTURA_LIVE_HEARTBEAT", "10"))

# SSE queue / history bounds. Large enough that realistic runs never drop an
# event; the evict-oldest path in publish() is only a last-resort safety valve.
_QUEUE_MAX = 8192
_HISTORY_MAX = 20000


def _put_drop_oldest(q: "queue.Queue", msg: dict) -> None:
    """Deliver msg, evicting the oldest queued item if the subscriber is full.
    The previous code silently dropped the NEWEST message on overflow, which
    could lose the terminal 'done'/'end' and freeze the browser on the last
    stage. Dropping the oldest keeps the stream converging to the latest state."""
    try:
        q.put_nowait(msg)
    except queue.Full:
        try:
            q.get_nowait()
        except queue.Empty:
            pass
        try:
            q.put_nowait(msg)
        except queue.Full:
            pass


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
            if len(self.history) > _HISTORY_MAX:
                # trim oldest; 'done'/'end' live at the tail so replay keeps them
                del self.history[:-_HISTORY_MAX]
            subs = list(self._subs)
        for q in subs:
            _put_drop_oldest(q, msg)

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=_QUEUE_MAX)
        with self._lock:
            for msg in self.history:      # replay backlog first
                _put_drop_oldest(q, msg)
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


class MultiSink:
    """Fan one event stream out to several EventSinks (e.g. the browser hub AND
    the terminal console renderer). A failure in one sink must not stop the
    others or the pipeline."""

    def __init__(self, sinks):
        self.sinks = [s for s in sinks if s is not None]

    def emit(self, ev):
        for s in self.sinks:
            try:
                s.emit(ev)
            except Exception:
                pass


class WatchedSink:
    """Wraps a sink and records a monotonic timestamp + current stage on every
    event, so a supervisor thread can tell 'still making progress' from
    'stalled'. Heartbeats are published OUT OF BAND (not through this sink), so
    they never reset the stall timer."""

    def __init__(self, inner, state: dict):
        self.inner = inner
        self.state = state          # shared {"t": monotonic, "stage": str, ...}

    def emit(self, ev):
        kind = getattr(ev, "kind", "")
        if kind == "step_started":
            self.state["stage"] = _stage_key(getattr(ev, "step_id", ""),
                                             getattr(ev, "title", ""))
        elif kind == "step_progress":
            self.state["stage"] = _stage_key(getattr(ev, "step_id", ""), "")
        self.state["t"] = time.monotonic()
        self.state["events"] = self.state.get("events", 0) + 1
        self.inner.emit(ev)


def run_live(instruction: str, cfg, hub: LiveHub, extra_sinks=None,
             stage_timeout: float = _STAGE_TIMEOUT,
             run_timeout: float = _RUN_TIMEOUT,
             on_status=None):
    """Run the real CLI pipeline, streaming everything to the hub AND to any
    extra_sinks (e.g. the terminal console renderer), under a watchdog.

    The pipeline runs in a worker thread; this function supervises it:
      * emits a periodic heartbeat so the browser and terminal show liveness;
      * if no pipeline event arrives for `stage_timeout` s, or the whole run
        exceeds `run_timeout` s, it surfaces an error (browser + terminal) and
        returns instead of hanging silently.

    on_status(str) is an optional callback for terminal-side status lines
    (heartbeats, stall/abort notices). Returns a dict describing the outcome."""
    from sutura_cli.core.agent import Session

    hub.reset()
    hub.publish({"type": "start", "instruction": instruction})

    state = {"t": time.monotonic(), "stage": "load", "events": 0}
    sink = WatchedSink(MultiSink([LiveSink(hub), *(extra_sinks or [])]), state)

    done = threading.Event()
    outcome = {"status": "running", "error": None}

    def _work():
        try:
            session = Session(cfg, sink)
            session.mode = "auto"
            session.handle(instruction)
            outcome["status"] = "complete"
        except Exception as e:            # never let the worker die silently
            outcome["status"] = "error"
            outcome["error"] = f"{type(e).__name__}: {e}"
            hub.publish({"type": "error", "text": outcome["error"]})
        finally:
            done.set()

    worker = threading.Thread(target=_work, name="sutura-live-pipeline",
                              daemon=True)
    worker.start()

    start = time.monotonic()
    last_beat = start
    while not done.wait(timeout=1.0):
        now = time.monotonic()
        since_event = now - state["t"]
        elapsed = now - start

        # 1) stage stall: no pipeline event for too long
        if since_event > stage_timeout:
            msg = (f"stage '{state['stage']}' stalled — no progress for "
                   f"{int(since_event)}s. Aborting the live view (the alignment "
                   f"thread may still be running in the background).")
            hub.publish({"type": "error", "text": msg})
            outcome["status"] = "stalled"
            outcome["error"] = msg
            if on_status:
                on_status(f"✗ {msg}")
            break

        # 2) global backstop
        if elapsed > run_timeout:
            msg = (f"run exceeded the {int(run_timeout)}s limit while in stage "
                   f"'{state['stage']}'. Aborting the live view.")
            hub.publish({"type": "error", "text": msg})
            outcome["status"] = "timeout"
            outcome["error"] = msg
            if on_status:
                on_status(f"✗ {msg}")
            break

        # 3) heartbeat (browser liveness + terminal keepalive on long stages)
        if now - last_beat >= _HEARTBEAT_EVERY:
            last_beat = now
            hub.publish({"type": "heartbeat", "stage": state["stage"],
                         "elapsed": int(elapsed),
                         "idle": round(since_event, 1)})
            if on_status and since_event > _HEARTBEAT_EVERY:
                on_status(f"… still in '{state['stage']}' "
                          f"({int(elapsed)}s elapsed, {int(since_event)}s since "
                          f"the last step)")

    hub.publish({"type": "end", "status": outcome["status"]})
    with hub._lock:
        hub.running = False
    return outcome
