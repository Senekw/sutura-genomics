"""Tests for rendering and the CLI surface."""
import json

from workflow_recommend.cli import main
from workflow_recommend.recommender import recommend
from workflow_recommend.render import render


def test_markdown_render_has_core_sections():
    pipe = recommend("Xenium breast tumor, single section, cell types and niches")
    md = render(pipe, fmt="markdown")
    assert "# Recommended pipeline" in md
    assert "## What we understood" in md
    assert "## Detailed steps" in md
    assert "Install:" in md
    assert "Expected runtime:" in md
    assert "Known limitations:" in md


def test_text_render_is_ascii():
    pipe = recommend("Visium kidney, 12 serial sections, cell types and domains")
    txt = render(pipe, fmt="text")
    assert txt.isascii(), "text report must be ASCII-clean for any console"
    assert "RECOMMENDED PIPELINE" in txt
    assert "PIPELINE AT A GLANCE" in txt


def test_render_includes_honesty_footer():
    pipe = recommend("Xenium breast, cell types")
    for fmt in ("markdown", "text"):
        out = render(pipe, fmt=fmt)
        assert "does not replace them" in out
        assert "expert visual QC" in out


def test_render_flags_unsolved_segmentation_visibly():
    pipe = recommend("Xenium breast, cell types")
    md = render(pipe, fmt="markdown")
    assert "UNSOLVED" in md


def test_cli_markdown(capsys):
    rc = main(["Xenium breast tumor, cell types and niches"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Recommended pipeline" in out


def test_cli_json_parses(capsys):
    rc = main(["--format", "json", "Visium kidney, 12 serial sections, cell types"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["spec"]["platform"] == "visium"
    assert any(s["step_id"] == "alignment_3d" for s in payload["steps"])


def test_cli_spec_only(capsys):
    rc = main(["--spec-only", "Xenium lung, disease vs control, 6 donors"])
    assert rc == 0
    spec = json.loads(capsys.readouterr().out)
    assert spec["experiment_type"] == "disease_vs_control"


def test_cli_list_tools(capsys):
    rc = main(["--list-tools"])
    assert rc == 0
    assert "Scanpy" in capsys.readouterr().out


def test_cli_list_platforms(capsys):
    rc = main(["--list-platforms"])
    assert rc == 0
    assert "Xenium" in capsys.readouterr().out


def test_cli_empty_returns_usage(capsys):
    rc = main([""])
    assert rc == 2
