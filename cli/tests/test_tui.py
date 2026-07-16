"""Smoke test for the Textual app: it composes, shows the branding/status bar,
toggles auto/manual mode, and quits. Does not exercise the alignment engine.
"""
from __future__ import annotations

import pytest

pytest.importorskip("textual")

from textual.widgets import Input, RichLog          # noqa: E402

from sutura_cli.core.config import Config           # noqa: E402
from sutura_cli.tui.app import (Brand, StatusBar, SuturaApp, _LOGO,  # noqa: E402
                                _short_method)


def _cfg(tmp_path) -> Config:
    return Config(store=tmp_path, backend="rule", cloud_model="",
                  ollama_model="", ollama_host="http://localhost:11434")


@pytest.mark.asyncio
async def test_app_composes_toggles_mode_and_quits(tmp_path):
    app = SuturaApp(_cfg(tmp_path))
    async with app.run_test() as pilot:
        assert app.query_one(Brand) is not None            # top-left header
        assert app.query_one(StatusBar) is not None
        assert app.query_one("#stream", RichLog) is not None
        assert app.query_one("#prompt", Input) is not None
        # starts in manual mode; f2 toggles to auto and back
        assert app.mode == "manual"
        app.action_toggle_mode()
        assert app.mode == "auto"
        app._set_mode("manual")
        assert app.mode == "manual"
        app._submit("exit")
        await pilot.pause()
    assert True  # reached here => app exited cleanly


def test_logo_is_ascii_dna_mark():
    assert len(_LOGO) == 4 and all(isinstance(r, str) for r in _LOGO)
    # no model/backend name leaks into the mark
    assert not any("llama" in r or "ollama" in r for r in _LOGO)


def test_short_method_labels():
    assert _short_method("Sutura (graph model)") == "Sutura"
    assert _short_method("Sutura (auto-adapted to your data)") == "Sutura·adapt"
    assert _short_method("PASTE2") == "PASTE2"
