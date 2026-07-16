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
