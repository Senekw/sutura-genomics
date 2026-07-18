#!/usr/bin/env python
"""Regenerate all worked examples from the current engine + knowledge base.

    python workflow/examples/generate.py

Keeps examples/*.md in sync so they never drift from the code.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from workflow_recommend.cli import main  # noqa: E402

EXAMPLES = [
    ("example_01_kidney_3d_visium.md",
     "3D organ mapping of human kidney, 10x Visium, 12 serial sections, "
     "want cell types and spatial domains"),
    ("example_02_breast_tumor_xenium.md",
     "Xenium human breast tumor, single section, want cell types, spatial niches, "
     "and ligand-receptor communication"),
    ("example_03_developmental_merscope.md",
     "MERSCOPE developmental time series of mouse brain, 4 timepoints "
     "(E12, E14, E16, P0), want cell types, spatial domains, and how expression "
     "changes over development"),
    ("example_04_disease_control_visiumhd.md",
     "Visium HD of human lung, disease vs control (IPF fibrosis), 5 donors per "
     "group, want cell types, fibrotic spatial domains, and differential "
     "expression between conditions"),
    ("example_05_liver_atlas_cosmx.md",
     "Building a spatial cell atlas of human liver with CosMx 6000-plex across 20 "
     "donors, want harmonized cell types and spatial domains, matched scRNA "
     "reference available"),
    ("example_06_whole_embryo_stereoseq.md",
     "Stereo-seq whole mouse embryo, single large section, want cell types and "
     "spatial domains across the whole organism"),
]


def run() -> None:
    for fname, desc in EXAMPLES:
        main(["-o", os.path.join(HERE, fname), desc])


if __name__ == "__main__":
    run()
