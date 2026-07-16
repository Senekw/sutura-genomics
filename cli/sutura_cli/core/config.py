"""Runtime configuration: where the shared store lives and which LLM backend
drives the agent loop. All of this is local; nothing here causes data egress.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def default_store() -> Path:
    """The shared result store the viewer app reads from (~/.sutura)."""
    env = os.environ.get("SUTURA_HOME")
    return Path(env).expanduser() if env else (Path.home() / ".sutura")


@dataclass
class Config:
    store: Path                    # ~/.sutura (bundles under store/results/)
    backend: str                   # "auto" | "cloud" | "ollama" | "rule"
    cloud_model: str
    ollama_model: str
    ollama_host: str

    @property
    def results_dir(self) -> Path:
        return self.store / "results"

    @classmethod
    def load(cls, backend: str | None = None) -> "Config":
        return cls(
            store=default_store(),
            backend=(backend or os.environ.get("SUTURA_BACKEND", "auto")).lower(),
            cloud_model=os.environ.get("SUTURA_CLOUD_MODEL", "claude-sonnet-5"),
            ollama_model=os.environ.get("SUTURA_OLLAMA_MODEL", "llama3.1"),
            ollama_host=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
        )

    def ensure_dirs(self) -> None:
        self.results_dir.mkdir(parents=True, exist_ok=True)
