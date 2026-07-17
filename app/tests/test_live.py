"""Tests for the live-progress plumbing: the SSE hub and event serialization.
Hermetic — no engine, no browser."""
from __future__ import annotations

import queue

from sutura_app import live


def test_hub_publish_subscribe_and_replay():
    hub = live.LiveHub()
    hub.publish({"type": "a"})
    q = hub.subscribe()                    # late subscriber gets the backlog
    assert q.get_nowait() == {"type": "a"}
    hub.publish({"type": "b"})             # and live updates
    assert q.get_nowait() == {"type": "b"}
    hub.unsubscribe(q)
    hub.publish({"type": "c"})             # no longer delivered
    try:
        q.get_nowait(); assert False
    except queue.Empty:
        pass


def test_serialize_stage_and_routing():
    class S:
        kind = "step_started"; step_id = "load_data"; title = "Load data"; detail = "scanning"
    m = live.serialize(S())
    assert m["type"] == "stage" and m["stage"] == "load" and m["phase"] == "start"

    class R:
        kind = "routing"; pair = "A -> B"; method = "Sutura"; reason = "in-dist"
        in_distribution = True; confidence = .9; mahalanobis = 0.85; gene_overlap = 1.0
    m = live.serialize(R())
    assert m["type"] == "routing" and m["method"] == "Sutura" and m["in_distribution"]


def test_serialize_pair_carries_real_geometry():
    import numpy as np

    class P:
        kind = "pair_result"; ref = "A"; mov = "B"
        method_label = "Sutura (graph model)"; score = 1.29; metric = "median_error_pitch"
        has_ground_truth = True; verdict = "pass"; in_distribution = True; mahalanobis = 0.85
        reason = "in-dist"
        ref_coords = np.random.rand(9000, 2) * 100
        mov_coords = np.random.rand(8000, 2) * 100      # before (torn)
        aligned_coords = np.random.rand(8000, 2) * 100  # after (real output)
        ref_layers = ["Layer1"] * 9000
        mov_layers = ["Layer2"] * 8000
    m = live.serialize(P())
    assert m["type"] == "pair" and m["method"] == "Sutura (graph model)"
    g = m["geom"]
    assert g is not None
    # a large cloud is downsampled; mov and aligned keep matching lengths
    assert len(g["mov"]) == len(g["aligned"])
    assert len(g["mov"]) < 8000 // 2 and len(g["ref"]) < 9000 // 2   # real reduction
    assert len(g["mov_layers"]) == len(g["mov"])
    assert all(len(p) == 2 for p in g["mov"])


def test_serialize_pair_without_geometry():
    class P:
        kind = "pair_result"; ref = "A"; mov = "B"; method_label = "PASTE2"
        score = 3.4; metric = "median_error_pitch"; has_ground_truth = True
        verdict = "pass"; in_distribution = False; mahalanobis = 4.7; reason = "off"
        ref_coords = None; mov_coords = None; aligned_coords = None
        ref_layers = None; mov_layers = None
    m = live.serialize(P())
    assert m["type"] == "pair" and m["geom"] is None


# --- overflow / backpressure --------------------------------------------- #
def test_publish_evicts_oldest_not_newest_on_overflow():
    """A slow/full subscriber must keep the NEWEST events (incl. done/end),
    dropping the oldest — the previous code dropped the newest and could lose
    the terminal event, freezing the browser on the last stage."""
    hub = live.LiveHub()
    q = hub.subscribe()
    # shrink this subscriber's queue to force overflow deterministically
    small = queue.Queue(maxsize=3)
    with hub._lock:
        hub._subs.discard(q); hub._subs.add(small)
    for i in range(10):
        hub.publish({"type": "n", "i": i})
    got = []
    try:
        while True:
            got.append(small.get_nowait()["i"])
    except queue.Empty:
        pass
    assert got == [7, 8, 9], got            # newest survive, oldest evicted


# --- watchdog / heartbeat (hermetic: fake Session, no engine) ------------- #
def _fake_session(monkeypatch, handle):
    import sutura_cli.core.agent as agentmod

    class Fake:
        def __init__(self, cfg, sink): self.sink = sink; self.mode = "manual"
        def handle(self, instruction): handle(self.sink)
    monkeypatch.setattr(agentmod, "Session", Fake)


def _collect(hub, seconds):
    import threading, time
    box = {"m": []}

    def drain():
        q = hub.subscribe(); t0 = time.time()
        while time.time() - t0 < seconds:
            try:
                box["m"].append(q.get(timeout=0.1))
            except queue.Empty:
                pass
    t = threading.Thread(target=drain, daemon=True); t.start()
    return box, t


def test_watchdog_surfaces_error_on_stall(monkeypatch):
    import time
    _fake_session(monkeypatch, lambda sink: time.sleep(30))   # never emits
    hub = live.LiveHub()
    box, t = _collect(hub, 6)
    time.sleep(0.1)
    t0 = time.time()
    outcome = live.run_live("x", None, hub, stage_timeout=1.5, run_timeout=20)
    dur = time.time() - t0
    t.join()
    assert outcome["status"] == "stalled"
    assert dur < 5                                # did NOT hang
    errs = [m for m in box["m"] if m.get("type") == "error"]
    assert errs and "stalled" in errs[0]["text"]
    assert any(m.get("type") == "end" for m in box["m"])


def test_watchdog_clean_completion(monkeypatch):
    import time

    def handle(sink):
        class E: kind = "step_started"; step_id = "load_data"; title = "Load"; detail = ""
        sink.emit(E()); time.sleep(0.2)
    _fake_session(monkeypatch, handle)
    hub = live.LiveHub()
    box, t = _collect(hub, 3)
    time.sleep(0.1)
    outcome = live.run_live("x", None, hub, stage_timeout=5, run_timeout=20)
    t.join()
    assert outcome["status"] == "complete"
    assert any(m.get("type") == "end" and m.get("status") == "complete"
               for m in box["m"])


def test_multisink_tees_and_isolates_failures():
    seen_a, seen_b = [], []

    class A:
        def emit(self, ev): seen_a.append(ev)

    class Boom:
        def emit(self, ev): raise RuntimeError("sink b is broken")

    class C:
        def emit(self, ev): seen_b.append(ev)

    ms = live.MultiSink([A(), Boom(), C()])
    ms.emit("x")                               # Boom must not stop A or C
    assert seen_a == ["x"] and seen_b == ["x"]
