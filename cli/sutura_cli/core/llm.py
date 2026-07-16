"""LLM backends that drive the agent loop.

The backend's only job is to turn a natural-language instruction plus the current
METADATA state into a structured Decision. It NEVER sees raw expression values -
`state` is WorkContext.state_view() (counts, names, formats only).

Three backends:
  - RuleBackend  : deterministic keyword intent parser. No network, no key.
                   Always available; this is what the offline e2e test uses.
  - CloudBackend : Anthropic API (key from env). Metadata-only prompt.
  - OllamaBackend: local Ollama server. Metadata-only prompt. Best for PHI.

select_backend() picks one based on config + availability, falling back to Rule.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Union


# --- decisions ------------------------------------------------------------ #
@dataclass
class WorkflowRequest:
    name: str
    args: dict = field(default_factory=dict)


@dataclass
class ToolRequest:
    name: str
    args: dict = field(default_factory=dict)


@dataclass
class Reply:
    text: str


Decision = Union[WorkflowRequest, ToolRequest, Reply]


# Compact description of what the agent can do (shared by cloud/ollama prompts).
ACTION_SPEC = """\
You are the planner for Sutura, a local spatial-transcriptomics alignment tool.
You see ONLY dataset metadata (names, spot/gene counts, formats) - never raw
expression. Decide the next action and reply with a SINGLE JSON object, no prose:

  {"action":"workflow","name":"align_and_reconstruct","args":{"path":"<dir-or-file>"}}
      Run the full pipeline: load -> QC -> route -> align each adjacent pair ->
      post-QC -> 3D reconstruct -> report. Use when the user wants to align and/or
      reconstruct sections. "path" may be omitted if sections are already loaded.

  {"action":"tool","name":"realign","args":{"section":"<name|index>","method":"paste2|sutura"}}
      Re-run one already-aligned pair with a forced method (e.g. "redo section 3
      with PASTE2"). Omit "method" to switch to the other method.

  {"action":"tool","name":"report","args":{}}     Regenerate the report only.

  {"action":"reply","text":"..."}                  Ask a clarifying question or answer.
"""

_PASTE = re.compile(r"\bpaste\s*2?\b", re.I)
_SUTURA = re.compile(r"\b(sutura|graph model|our model)\b", re.I)
_RECON = re.compile(r"\b(align|reconstruct|stack|register|run|build|3d|assemble)\b", re.I)
_REDO = re.compile(r"\b(redo|re-?run|re-?align|again|switch|change)\b", re.I)
_REPORT = re.compile(r"\breport\b", re.I)
_HELP = re.compile(r"\b(help|what can you|how do i|usage)\b", re.I)
_SECTION_REF = re.compile(r"\bsection\s+([A-Za-z0-9_.-]+)", re.I)


def _extract_path(text: str):
    # quoted path first
    m = re.search(r'["\']([^"\']+)["\']', text)
    if m and ("/" in m.group(1) or "\\" in m.group(1) or m.group(1).endswith(".h5ad")):
        return m.group(1)
    # windows drive, unix/relative path, or a bare .h5ad token
    m = re.search(r"([A-Za-z]:\\[^\s\"']+|\.{0,2}[/\\][^\s\"']+|[^\s\"']+\.h5ad)", text)
    if m:
        return m.group(1)
    # "in <word>" / "from <word>" fallback (bare directory name)
    m = re.search(r"\b(?:in|from|at|under)\s+([^\s\"']+)", text, re.I)
    if m and m.group(1).lower() not in {"the", "a", "an", "3d", "my"}:
        return m.group(1)
    return None


class RuleBackend:
    name = "rule"

    def interpret(self, instruction: str, state: dict) -> Decision:
        t = instruction.strip()
        if not t:
            return Reply("Tell me what to do, e.g. "
                         '"align the sections in ./my_data and reconstruct in 3D".')
        if _HELP.search(t):
            return Reply(
                "I align local spatial-transcriptomics sections and build a 3D "
                "reconstruction, entirely on this machine. Try: "
                '"align the sections in ./data and reconstruct in 3D", then '
                '"redo section 2 with PASTE2".')

        method = "paste2" if _PASTE.search(t) else ("sutura" if _SUTURA.search(t) else None)

        if _REDO.search(t) or (method and _SECTION_REF.search(t)):
            sref = _SECTION_REF.search(t)
            args = {}
            if sref:
                args["section"] = sref.group(1)
            if method:
                args["method"] = method
            return ToolRequest("realign", args)

        if _REPORT.search(t) and not _RECON.search(t):
            return ToolRequest("report", {})

        if _RECON.search(t):
            path = _extract_path(t)
            args = {"path": path} if path else {}
            return WorkflowRequest("align_and_reconstruct", args)

        # sections already loaded and an ambiguous "go" -> run workflow
        if state.get("sections"):
            return WorkflowRequest("align_and_reconstruct", {})
        return Reply('I did not catch a data path. Try: "align the sections in '
                     './my_data and reconstruct in 3D".')


class _JSONLLMBackend:
    """Shared parsing for cloud/ollama: prompt -> JSON -> Decision."""

    def _decision_from_json(self, raw: str, state: dict) -> Decision:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return Reply(raw.strip() or "I could not plan that; please rephrase.")
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return Reply(raw.strip())
        act = obj.get("action")
        if act == "workflow":
            return WorkflowRequest(obj.get("name", "align_and_reconstruct"),
                                   obj.get("args", {}) or {})
        if act == "tool":
            return ToolRequest(obj.get("name", ""), obj.get("args", {}) or {})
        return Reply(obj.get("text", "").strip() or "Please clarify.")

    def _user_msg(self, instruction: str, state: dict) -> str:
        return (f"Dataset metadata (no expression values):\n"
                f"{json.dumps(state, indent=2)}\n\n"
                f"User instruction: {instruction}\n\nRespond with one JSON object.")


class CloudBackend(_JSONLLMBackend):
    name = "cloud"

    def __init__(self, model: str):
        self.model = model
        import anthropic  # lazy; only when actually selected
        self._client = anthropic.Anthropic()  # key from ANTHROPIC_API_KEY

    def interpret(self, instruction: str, state: dict) -> Decision:
        msg = self._client.messages.create(
            model=self.model, max_tokens=400, system=ACTION_SPEC,
            messages=[{"role": "user",
                       "content": self._user_msg(instruction, state)}])
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return self._decision_from_json(text, state)


class OllamaBackend(_JSONLLMBackend):
    name = "ollama"

    def __init__(self, model: str, host: str):
        self.model = model
        self.host = host.rstrip("/")

    def interpret(self, instruction: str, state: dict) -> Decision:
        payload = {
            "model": self.model, "stream": False, "format": "json",
            "messages": [
                {"role": "system", "content": ACTION_SPEC},
                {"role": "user", "content": self._user_msg(instruction, state)}],
        }
        req = urllib.request.Request(
            f"{self.host}/api/chat", method="POST",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            body = json.loads(r.read().decode())
        return self._decision_from_json(body.get("message", {}).get("content", ""), state)


def _ollama_up(host: str) -> bool:
    try:
        with urllib.request.urlopen(f"{host.rstrip('/')}/api/tags", timeout=1.5):
            return True
    except (urllib.error.URLError, OSError):
        return False


def select_backend(cfg) -> tuple[Any, list[str]]:
    """Return (backend, notes). Honours cfg.backend, falls back to rule."""
    notes = []
    want = cfg.backend
    if want in ("cloud", "auto") and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return CloudBackend(cfg.cloud_model), notes
        except Exception as e:            # missing sdk / bad key
            notes.append(f"cloud backend unavailable ({e}); falling back")
    elif want == "cloud":
        notes.append("cloud backend requested but ANTHROPIC_API_KEY is not set")

    if want in ("ollama", "auto") and _ollama_up(cfg.ollama_host):
        return OllamaBackend(cfg.ollama_model, cfg.ollama_host), notes
    elif want == "ollama":
        notes.append(f"ollama not reachable at {cfg.ollama_host}; falling back")

    if want not in ("rule", "auto") and not notes:
        notes.append(f"unknown backend {want!r}; using rule backend")
    notes.append("using offline rule-based backend (no LLM; deterministic planning)")
    return RuleBackend(), notes
