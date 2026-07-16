"""In-memory working state for a session.

Raw AnnData objects (which contain expression values) live here and NEVER leave
this process. Only the small metadata in `StateView` is handed to the LLM
backend. Tools resolve sections by id/name against this context.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class Section:
    id: str                      # stable handle, e.g. "s1"
    name: str                    # human name, e.g. "DLPFC_151507"
    fmt: str                     # h5ad | spaceranger | xenium
    h5ad_path: Path              # on-disk .h5ad the engine reads (may be a copy)
    source: str                  # original user-facing path
    adata: Any = None            # AnnData, expression stays local
    n_spots: int = 0
    n_genes: int = 0
    has_spatial: bool = False
    has_layers: bool = False

    def meta(self) -> dict:
        """Metadata-only view (safe for the LLM / bundle)."""
        return {
            "id": self.id, "name": self.name, "format": self.fmt,
            "n_spots": self.n_spots, "n_genes": self.n_genes,
            "has_spatial": self.has_spatial, "has_layers": self.has_layers,
            "source": self.source,
        }


class WorkContext:
    def __init__(self, workdir: Path) -> None:
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.sections: dict[str, Section] = {}
        self._n = 0
        # cached heavy engine objects (built once per session)
        self._projector = None
        self._basis = None

    def add_section(self, sec: Section) -> Section:
        self.sections[sec.id] = sec
        return sec

    def new_id(self) -> str:
        self._n += 1
        return f"s{self._n}"

    def resolve(self, ref: str) -> Optional[Section]:
        """Resolve a section by id, name, or 1-based index (as string)."""
        if ref in self.sections:
            return self.sections[ref]
        for s in self.sections.values():
            if s.name == ref:
                return s
        if ref.isdigit():
            idx = int(ref) - 1
            ordered = list(self.sections.values())
            if 0 <= idx < len(ordered):
                return ordered[idx]
        return None

    def ordered(self) -> list[Section]:
        return list(self.sections.values())

    def state_view(self) -> dict:
        """Everything the LLM backend is allowed to see (metadata only)."""
        return {"sections": [s.meta() for s in self.sections.values()]}
