"""Sutura viewer app - a local, display-only companion to the Sutura CLI.

Reads the result bundles the CLI writes to ~/.sutura/results/<job_id>/ (bundle
schema v1.0) and renders them: the 3D reconstruction, which method produced each
pair and why, all metrics, QC, and a clean summary. It NEVER runs alignment or
reconstruction - it only displays what the CLI produced, and it is honest about
which method produced each result.
"""

__version__ = "0.1.0"

# Bundle schema this viewer reads. Kept in step with the CLI's SCHEMA_VERSION.
READS_SCHEMA = "1.0"
