"""Tests for the natural-language -> ExperimentSpec parser."""
import pytest

from workflow_recommend.parser import parse_experiment


def test_visium_kidney_3d():
    s = parse_experiment("3D organ mapping of human kidney, 10x Visium, 12 serial "
                         "sections, want cell types and spatial domains")
    assert s.platform == "visium"
    assert s.platform_confidence == "high"
    assert s.experiment_type == "3d_organ_mapping"
    assert s.serial_sections is True
    assert s.n_sections == 12
    assert s.tissue == "kidney"
    assert {"cell_typing", "spatial_domains", "alignment_3d"} <= s.all_goals()


@pytest.mark.parametrize("text,expected", [
    ("10x Visium HD colon, 2um bins", "visium_hd"),
    ("Visium HD of mouse brain", "visium_hd"),
    ("Xenium breast panel", "xenium"),
    ("MERSCOPE MERFISH mouse brain", "merscope"),
    ("Vizgen merscope liver", "merscope"),
    ("CosMx 6000-plex lung", "cosmx"),
    ("NanoString CosMx", "cosmx"),
    ("Stereo-seq mouse embryo", "stereo_seq"),
    ("BGI stereoseq whole embryo", "stereo_seq"),
    ("standard 10x Visium prostate", "visium"),
])
def test_platform_detection(text, expected):
    assert parse_experiment(text).platform == expected


def test_visium_hd_beats_visium():
    # 'Visium HD' must not be mis-detected as plain Visium
    assert parse_experiment("Visium HD kidney").platform == "visium_hd"


def test_unknown_platform_flagged():
    s = parse_experiment("some spatial transcriptomics of the pancreas")
    assert s.platform is None
    assert s.platform_confidence == "unknown"
    assert any("platform" in n.lower() for n in s.notes)


def test_disease_vs_control_detected():
    s = parse_experiment("Xenium lung, disease vs control comparison, 6 donors per group")
    assert s.experiment_type == "disease_vs_control"
    assert s.n_samples == 6
    assert "spatial_de" in s.all_goals()


def test_developmental_timeseries():
    s = parse_experiment("MERSCOPE developmental time series of mouse embryo, 4 timepoints")
    assert s.experiment_type == "developmental_timeseries"
    assert s.n_samples == 4


def test_atlas_building():
    s = parse_experiment("Building a cell atlas of human liver across 20 donors with Visium")
    assert s.experiment_type == "atlas_building"
    assert s.n_samples == 20


def test_reference_detection():
    assert parse_experiment("Visium with a matched scRNA reference").has_reference is True
    assert parse_experiment("Visium, no single-cell reference available").has_reference is False
    assert parse_experiment("Visium kidney").has_reference is None


def test_goal_keywords():
    s = parse_experiment("Xenium: annotate cell types, find spatial domains, and "
                         "ligand-receptor communication, plus differential expression")
    g = s.all_goals()
    assert {"cell_typing", "spatial_domains", "cell_communication", "spatial_de"} <= g


def test_serial_sections_without_count():
    s = parse_experiment("Visium serial sections of the heart for 3D reconstruction")
    assert s.serial_sections is True
    assert "alignment_3d" in s.all_goals()


def test_single_section_no_alignment_or_batch():
    s = parse_experiment("Xenium single section of skin, cell types only")
    assert s.serial_sections is False
    assert s.n_sections is None or s.n_sections == 1
    # no multi-sample integration implied
    assert "batch_correction" not in s.all_goals()


def test_empty_description_defaults():
    s = parse_experiment("hello")
    assert s.experiment_type == "general_spatial"
    assert s.all_goals()  # defaults populated
