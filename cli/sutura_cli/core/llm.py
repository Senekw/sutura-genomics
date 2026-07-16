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
# Keep the vocabulary TINY and explicit: small local models only stay reliable
# when the action space is closed. Any out-of-vocabulary action the model emits
# is caught by _finalize() and replaced with the deterministic rule planner.
ACTION_SPEC = """\
You are the planner for Sutura, a local spatial-transcriptomics alignment tool.
You see ONLY dataset metadata (names, spot/gene counts, formats) - never raw
expression. Reply with a SINGLE JSON object and NOTHING else.

Use EXACTLY one of these four shapes. Do not invent other "action" or "name"
values, and do not add other keys:

  {"action":"workflow","name":"align_and_reconstruct","args":{"path":"<dir-or-file>"}}
      The full pipeline: load -> QC -> route -> align each adjacent pair ->
      post-QC -> 3D reconstruct -> report. Use whenever the user wants to align,
      register, stack, or reconstruct sections. Omit "path" only if sections are
      already loaded.

  {"action":"tool","name":"realign","args":{"section":"<name-or-number>","method":"paste2"}}
      Re-run ONE already-aligned pair with a forced method. "method" must be
      exactly "paste2" or "sutura"; omit it to switch to the other method.
      Example: "redo section 2 with PASTE2".

  {"action":"tool","name":"report","args":{}}
      Regenerate the report for the current job only.

  {"action":"tool","name":"metrics","args":{}}
      Show the alignment metrics (method + score per pair) for the current job.

  {"action":"tool","name":"worst","args":{}}
      Say which pair/section aligned worst (and best) in the current job.

  {"action":"tool","name":"explain_routing","args":{"section":"<name-or-number>"}}
      Explain why a method was chosen for a pair (omit "section" to explain all).

  {"action":"reply","text":"..."}
      Answer a question or ask for clarification. Use this for "what can you do?".

Rules: a workflow "name" is always "align_and_reconstruct". A tool "name" is one
of: realign, report, metrics, worst, explain_routing. Never invent other names
(no "redo_section", "align", "pdf", "show_worst").

Examples (instruction -> JSON):
  "align the sections in ./data and reconstruct in 3D"
      {"action":"workflow","name":"align_and_reconstruct","args":{"path":"./data"}}
  "stack my slices into a 3D model"
      {"action":"workflow","name":"align_and_reconstruct","args":{}}
  "redo section 2 with PASTE2"
      {"action":"tool","name":"realign","args":{"section":"2","method":"paste2"}}
  "switch section 1 to the graph model"
      {"action":"tool","name":"realign","args":{"section":"1","method":"sutura"}}
  "re-run that pair with a different method"
      {"action":"tool","name":"realign","args":{}}
  "regenerate the report"
      {"action":"tool","name":"report","args":{}}
  "show me the metrics" / "how well did it align?"
      {"action":"tool","name":"metrics","args":{}}
  "which section aligned worst?"
      {"action":"tool","name":"worst","args":{}}
  "explain the routing decision" / "why did it pick that method?"
      {"action":"tool","name":"explain_routing","args":{}}
  "what can you do?"
      {"action":"reply","text":"I align local spatial sections and build a 3D reconstruction, entirely on your machine."}
"""

_PASTE = re.compile(r"\bpaste\s*2?\b", re.I)
_SUTURA = re.compile(r"\b(sutura|graph model|our model)\b", re.I)
_RECON = re.compile(r"\b(align|reconstruct|stack|register|run|build|3d|assemble)\b", re.I)
_REDO = re.compile(r"\b(redo|re-?run|re-?align|again|switch|change)\b", re.I)
_REPORT = re.compile(r"\breport\b", re.I)
_HELP = re.compile(r"\b(help|what can you|what do you|how do i|usage|who are you)\b", re.I)
_SECTION_REF = re.compile(r"\b(?:section|slice|pair)\s+([A-Za-z0-9_.-]+)", re.I)
_METRICS = re.compile(r"\b(metrics?|scores?|accuracy|errors?|quality|how (?:well|good|accurate))\b", re.I)
_WORST = re.compile(r"\b(worst|best|which (?:section|slice|pair))\b", re.I)
_EXPLAIN = re.compile(r"\b(explain|why)\b.*\b(rout|method|choose|chose|pick|decision|dist)", re.I)
_ROUTING = re.compile(r"\brouting\b", re.I)
_QUESTION = re.compile(r"\?|\b(how|which|what|why|did|was|were|does|do|is|are)\b", re.I)


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


# --- the closed action vocabulary (for validating LLM output) ------------- #
_WORKFLOWS = {"align_and_reconstruct"}
_TOOL_ALIASES = {          # map anything a weak model emits onto a real tool
    "realign": "realign", "redo": "realign", "redo_section": "realign",
    "rerun": "realign", "re_align": "realign", "re-align": "realign",
    "switch_method": "realign", "change_method": "realign", "align_again": "realign",
    "report": "report", "generate_report": "report", "make_report": "report",
    "regenerate_report": "report",
    "metrics": "metrics", "show_metrics": "metrics", "scores": "metrics",
    "score": "metrics", "results": "metrics",
    "worst": "worst", "worst_pair": "worst", "worst_section": "worst",
    "best": "worst", "which_worst": "worst", "show_worst": "worst",
    "explain_routing": "explain_routing", "explain": "explain_routing",
    "routing": "explain_routing", "why": "explain_routing",
    "explain_route": "explain_routing", "routing_decision": "explain_routing",
}
# tools that take no meaningful args (used by _canonicalize)
_SIMPLE_TOOLS = {"report", "metrics", "worst"}


def _norm_method(m):
    """Normalise a possibly-garbled method string to 'paste2' / 'sutura' / None."""
    if not m:
        return None
    s = re.sub(r"[\s._-]+", "", str(m).lower())
    if s in {"paste2", "paste", "pase2", "paste2bio", "pastebio", "p2"} or "paste" in s:
        return "paste2"
    if s in {"sutura", "graph", "graphmodel", "ours", "arca"} or "sutura" in s or "graph" in s:
        return "sutura"
    return None


def _canon_tool(name):
    if not name:
        return None
    return _TOOL_ALIASES.get(re.sub(r"[\s.-]+", "_", str(name).strip().lower()))


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

        # explain a routing decision (before generic recon, since it mentions method)
        if _EXPLAIN.search(t) or _ROUTING.search(t):
            sref = _SECTION_REF.search(t)
            return ToolRequest("explain_routing",
                               {"section": sref.group(1)} if sref else {})

        if _REDO.search(t) or (method and _SECTION_REF.search(t)):
            sref = _SECTION_REF.search(t)
            args = {}
            if sref:
                args["section"] = sref.group(1)
            if method:
                args["method"] = method
            return ToolRequest("realign", args)

        # read-only queries on the current job
        if _WORST.search(t):
            return ToolRequest("worst", {})
        # a quality question ("how well did it align?") is metrics, not a command,
        # even though it contains "align"
        if _METRICS.search(t) and (_QUESTION.search(t) or not _RECON.search(t)):
            return ToolRequest("metrics", {})
        if _REPORT.search(t) and not _RECON.search(t):
            return ToolRequest("report", {})

        if _RECON.search(t):
            path = _extract_path(t)
            args = {"path": path} if path else {}
            return WorkflowRequest("align_and_reconstruct", args)

        # explicit "go ahead" with sections already loaded -> run workflow
        if state.get("sections") and re.search(
                r"\b(go|proceed|do it|continue|yes|start|begin)\b", t, re.I):
            return WorkflowRequest("align_and_reconstruct", {})
        # otherwise don't guess an expensive re-run: ask for clarification
        return Reply('I did not catch a clear instruction. Try: "align the '
                     'sections in ./my_data and reconstruct in 3D", or ask '
                     '"how well did it align?" / "which section aligned worst?".')


class _JSONLLMBackend:
    """Shared logic for cloud/ollama: prompt -> JSON -> validated Decision.

    Small local models are unreliable planners, so we never trust raw model
    output. _finalize() normalises it against the closed action vocabulary and,
    when the model produces something out-of-vocabulary or under-acts on a clear
    command, defers to the deterministic RuleBackend. This is what lets a 1-3B
    model drive the loop safely: the model handles phrasing, the rules guarantee
    the action space.
    """

    def _decision_from_json(self, raw: str, state: dict) -> Decision:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return Reply(raw.strip() or "")
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return Reply(raw.strip())
        act = (obj.get("action") or "").lower()
        if act == "workflow":
            return WorkflowRequest(obj.get("name", "align_and_reconstruct"),
                                   obj.get("args", {}) or {})
        if act == "tool":
            return ToolRequest(obj.get("name", ""), obj.get("args", {}) or {})
        if act == "reply":
            return Reply(obj.get("text", "").strip())
        # unknown/absent action but valid JSON: let _finalize decide via rules
        return Reply(obj.get("text", "").strip())

    @staticmethod
    def _canonicalize(d: Decision):
        """Return an in-vocabulary Decision, or None if the model went off-script."""
        if isinstance(d, WorkflowRequest):
            name = str(d.name or "").strip().lower()
            if name in _WORKFLOWS or "align" in name or "reconstruct" in name:
                return WorkflowRequest("align_and_reconstruct", dict(d.args or {}))
            return None
        if isinstance(d, ToolRequest):
            canon = _canon_tool(d.name)
            if canon == "realign":
                args = dict(d.args or {})
                if "method" in args:
                    m = _norm_method(args.get("method"))
                    if m:
                        args["method"] = m
                    else:
                        args.pop("method", None)
                return ToolRequest("realign", args)
            if canon == "explain_routing":
                args = dict(d.args or {})
                return ToolRequest("explain_routing",
                                   {"section": args["section"]} if args.get("section") else {})
            if canon in _SIMPLE_TOOLS:
                return ToolRequest(canon, {})
            return None
        if isinstance(d, Reply):
            return d if d.text else None
        return None

    def _finalize(self, decision: Decision, instruction: str, state: dict) -> Decision:
        """Adjudicate the model's plan against the deterministic rule planner.

        The rule planner is precise for this tiny closed vocabulary, so it wins
        any action-TYPE disagreement (a weak model that turns "switch section 1"
        into a full workflow gets corrected). Otherwise the model's plan stands,
        with missing args filled in from the rules. The model still handles
        phrasings the keyword rules can't parse (rule abstains with a Reply)."""
        canon = self._canonicalize(decision)
        rule = RuleBackend().interpret(instruction, state)
        rule_is_action = not isinstance(rule, Reply)

        if canon is None:                       # off-vocabulary / empty -> rules
            return rule
        if isinstance(canon, Reply):            # model only replied
            return rule if rule_is_action else canon
        # canon is a concrete action (Workflow or Tool)
        if rule_is_action and type(rule) is not type(canon):
            return rule                         # action-type conflict -> trust rules
        # same action type (or rule abstained): keep the model plan, fill gaps
        if isinstance(canon, WorkflowRequest):
            if not canon.args.get("path") and isinstance(rule, WorkflowRequest) \
                    and rule.args.get("path"):
                canon.args["path"] = rule.args["path"]
        elif isinstance(canon, ToolRequest) and canon.name == "realign" \
                and isinstance(rule, ToolRequest) and rule.name == "realign":
            for k in ("section", "method"):
                if not canon.args.get(k) and rule.args.get(k):
                    canon.args[k] = rule.args[k]
        return canon

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
        try:
            msg = self._client.messages.create(
                model=self.model, max_tokens=400, system=ACTION_SPEC,
                messages=[{"role": "user",
                           "content": self._user_msg(instruction, state)}])
            text = "".join(b.text for b in msg.content
                           if getattr(b, "type", "") == "text")
            decision = self._decision_from_json(text, state)
        except Exception:
            decision = Reply("")     # any API failure -> rule fallback in _finalize
        return self._finalize(decision, instruction, state)


class OllamaBackend(_JSONLLMBackend):
    name = "ollama"

    def __init__(self, model: str, host: str):
        self.model = model
        self.host = host.rstrip("/")

    def interpret(self, instruction: str, state: dict) -> Decision:
        payload = {
            "model": self.model, "stream": False, "format": "json",
            "options": {"temperature": 0.0},        # deterministic planning
            "messages": [
                {"role": "system", "content": ACTION_SPEC},
                {"role": "user", "content": self._user_msg(instruction, state)}],
        }
        try:
            req = urllib.request.Request(
                f"{self.host}/api/chat", method="POST",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                body = json.loads(r.read().decode())
            raw = body.get("message", {}).get("content", "")
            decision = self._decision_from_json(raw, state)
        except Exception:
            decision = Reply("")     # server/model failure -> rule fallback
        return self._finalize(decision, instruction, state)


def _ollama_models(host: str) -> list[str]:
    try:
        with urllib.request.urlopen(f"{host.rstrip('/')}/api/tags", timeout=2.0) as r:
            data = json.loads(r.read().decode())
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    except (urllib.error.URLError, OSError, ValueError):
        return []


def _ollama_up(host: str) -> bool:
    try:
        with urllib.request.urlopen(f"{host.rstrip('/')}/api/tags", timeout=1.5):
            return True
    except (urllib.error.URLError, OSError):
        return False


def _resolve_ollama_model(want: str, installed: list[str]) -> str | None:
    """Pick a usable installed model: the requested one, else a sensible default.
    Small models (<=1B) are deprioritised - they are unreliable planners."""
    if not installed:
        return None
    if want in installed:
        return want
    base = want.split(":")[0]
    for m in installed:                       # same family, any tag
        if m.split(":")[0] == base:
            return m
    # preference order among common capable-but-small local planners
    for pref in ("qwen2.5", "llama3.2", "llama3.1", "mistral", "gemma3", "gemma2",
                 "phi3", "qwen2"):
        cands = [m for m in installed if m.split(":")[0] == pref]
        if cands:
            # avoid the 1b tag if a larger one exists in the same family
            larger = [c for c in cands if not c.endswith((":1b", ":0.5b"))]
            return (larger or cands)[0]
    return installed[0]


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

    if want in ("ollama", "auto"):
        if _ollama_up(cfg.ollama_host):
            installed = _ollama_models(cfg.ollama_host)
            model = _resolve_ollama_model(cfg.ollama_model, installed)
            if model:
                if model != cfg.ollama_model:
                    notes.append(f"ollama model {cfg.ollama_model!r} not installed; "
                                 f"using {model!r} (installed: {', '.join(installed)})")
                notes.append(f"local ollama backend: model {model} at "
                             f"{cfg.ollama_host} (no API key, no data egress); "
                             f"out-of-vocabulary plans fall back to rules")
                return OllamaBackend(model, cfg.ollama_host), notes
            notes.append("ollama is running but has no models installed "
                         "(try: ollama pull llama3.2); falling back")
        elif want == "ollama":
            notes.append(f"ollama not reachable at {cfg.ollama_host}; falling back")

    if want not in ("rule", "auto") and not notes:
        notes.append(f"unknown backend {want!r}; using rule backend")
    notes.append("using offline rule-based backend (no LLM; deterministic planning)")
    return RuleBackend(), notes
