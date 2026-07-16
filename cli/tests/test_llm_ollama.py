"""Local-LLM integration: drive the planner with a real Ollama model (no API
key). Skipped automatically if no Ollama server / model is available, so it is
safe in CI but exercises the real natural-language -> plan path when a local
model is present."""
from __future__ import annotations

import pytest

from sutura_cli.core.llm import (OllamaBackend, Reply, ToolRequest,
                                 WorkflowRequest, _ollama_models, _ollama_up,
                                 _resolve_ollama_model)

HOST = "http://localhost:11434"
UP = _ollama_up(HOST)
MODEL = _resolve_ollama_model("llama3.2:3b", _ollama_models(HOST)) if UP else None

pytestmark = pytest.mark.skipif(not MODEL, reason="no local Ollama model available")

_STATE = {"sections": [
    {"id": "s1", "name": "DLPFC_151507", "n_spots": 4226, "n_genes": 33538},
    {"id": "s2", "name": "DLPFC_151508", "n_spots": 4384, "n_genes": 33538}]}


@pytest.fixture(scope="module")
def backend():
    return OllamaBackend(MODEL, HOST)


@pytest.mark.parametrize("text,kind,check", [
    ("align the sections in ./data and reconstruct in 3D", WorkflowRequest,
     lambda d: d.args.get("path") == "./data"),
    ("redo section 2 with PASTE2", ToolRequest,
     lambda d: d.name == "realign" and d.args.get("method") == "paste2"),
    ("switch section 1 to the graph model", ToolRequest,
     lambda d: d.name == "realign" and d.args.get("method") == "sutura"),
    ("which section aligned worst?", ToolRequest, lambda d: d.name == "worst"),
    ("show me the metrics", ToolRequest, lambda d: d.name == "metrics"),
    ("explain the routing decision", ToolRequest,
     lambda d: d.name == "explain_routing"),
    ("regenerate the report", ToolRequest, lambda d: d.name == "report"),
    ("what can you do?", Reply, lambda d: bool(d.text)),
])
def test_local_model_plans_core_intents(backend, text, kind, check):
    d = backend.interpret(text, _STATE)
    assert isinstance(d, kind), f"{text!r} -> {type(d).__name__}"
    assert check(d), f"{text!r} -> {getattr(d, 'args', getattr(d, 'text', d))}"


def test_local_model_never_out_of_vocabulary(backend):
    # whatever the model emits, _finalize keeps the action space closed
    for text in ["do the thing", "help me stack these", "compare methods please"]:
        d = backend.interpret(text, _STATE)
        if isinstance(d, WorkflowRequest):
            assert d.name == "align_and_reconstruct"
        elif isinstance(d, ToolRequest):
            assert d.name in {"realign", "report", "metrics", "worst",
                              "explain_routing"}
        else:
            assert isinstance(d, Reply)
