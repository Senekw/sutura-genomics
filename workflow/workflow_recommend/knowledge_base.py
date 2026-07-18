"""Load and index the structured knowledge base (JSON under kb/).

The knowledge base is deliberately plain JSON so it is easy to audit, diff, and
extend without touching code. This module just loads it and builds a few lookup
indexes. It has ZERO third-party dependencies (stdlib json only).
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

_KB_DIR = os.path.join(os.path.dirname(__file__), "kb")


def _load(name: str) -> dict[str, Any]:
    path = os.path.join(_KB_DIR, name)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class KnowledgeBase:
    """In-memory view of the tool / step / platform / experiment-type knowledge base."""

    def __init__(self) -> None:
        self.platforms: dict[str, Any] = _load("platforms.json")["platforms"]
        self.experiment_types: dict[str, Any] = _load("experiment_types.json")["experiment_types"]
        self._steps_list: list[dict] = _load("steps.json")["steps"]
        self.tools: list[dict] = _load("tools.json")["tools"]

        # index steps by id, preserving canonical order
        self.steps: dict[str, Any] = {s["id"]: s for s in self._steps_list}
        self._step_order = {s["id"]: s["order"] for s in self._steps_list}

        # index tools by id
        self.tools_by_id: dict[str, dict] = {t["id"]: t for t in self.tools}

    # ---- lookups -------------------------------------------------------

    def step_order(self, step_id: str) -> int:
        return self._step_order.get(step_id, 9999)

    def ordered_step_ids(self) -> list[str]:
        return [s["id"] for s in sorted(self._steps_list, key=lambda s: s["order"])]

    def tools_for_step(self, step_id: str, platform: str | None = None) -> list[dict]:
        """All tools that serve a step and are compatible with the platform.

        Returned sorted by descending priority (with a small platform-specific boost),
        so the first element is the default recommendation.
        """
        out = []
        for t in self.tools:
            if step_id not in t.get("steps", []):
                continue
            plats = t.get("platforms", [])
            if platform and "all" not in plats and platform not in plats:
                continue
            out.append(t)
        return sorted(out, key=lambda t: self._rank(t, platform), reverse=True)

    def _rank(self, tool: dict, platform: str | None) -> float:
        score = float(tool.get("priority", 0))
        # boost tools that explicitly and exclusively target this platform
        plats = tool.get("platforms", [])
        if platform and platform in plats and "all" not in plats:
            score += 5.0
            if len(plats) == 1:
                # a tool built for exactly this platform (e.g. Stereopy for
                # Stereo-seq, bin2cell for Visium HD) should win over generic
                # backbones, since it often handles a format others cannot read.
                score += 30.0
        return score

    def get_tool(self, tool_id: str) -> dict | None:
        return self.tools_by_id.get(tool_id)


@lru_cache(maxsize=1)
def load_kb() -> KnowledgeBase:
    """Cached singleton KnowledgeBase."""
    return KnowledgeBase()
