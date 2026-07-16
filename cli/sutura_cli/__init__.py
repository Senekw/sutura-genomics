"""Sutura - agentic, local-first CLI for spatial transcriptomics alignment.

Two products share this repo: this CLI (the engine) writes structured result
bundles under ~/.sutura/results/<job_id>/; the separate viewer app reads them.
The CLI never uploads data - everything runs on the local machine. The LLM that
drives the agent loop only ever sees metadata, never raw expression values.
"""

__version__ = "0.1.0"

# Bundle schema version. Bump when the on-disk result bundle layout changes.
# The viewer app checks this. See docs/BUNDLE_SCHEMA.md.
SCHEMA_VERSION = "1.0"
