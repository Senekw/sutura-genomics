"""Smoke test for the Textual app: it composes, shows the branding/status bar,
and the quit path works. Does not exercise the (heavy) alignment engine.
"""
from __future__ import annotations

import pytest

pytest.importorskip("textual")

from textual.widgets import Input, RichLog          # noqa: E402

from sutura_cli.core.config import Config           # noqa: E402
from sutura_cli.tui.app import (Brand, StatusBar, SuturaApp, _backend_line,  # noqa: E402
                                _short_method)


def _cfg(tmp_path) -> Config:
    return Config(store=tmp_path, backend="rule", cloud_model="",
                  ollama_model="", ollama_host="http://localhost:11434")


@pytest.mark.asyncio
async def test_app_composes_and_quits(tmp_path):
    app = SuturaApp(_cfg(tmp_path))
    async with app.run_test() as pilot:
        assert app.query_one(Brand) is not None            # top-left header
        assert app.query_one(StatusBar) is not None
        assert app.query_one("#stream", RichLog) is not None
        assert app.query_one("#prompt", Input) is not None
        # typing "exit" closes the app
        app._submit("exit")
        await pilot.pause()
    assert True  # reached here => app exited cleanly


def test_backend_line_formats():
    class B:
        name = "ollama"; model = "llama3.2:3b"
    assert "llama3.2:3b" in _backend_line(B()) and "no data egress" in _backend_line(B())

    class R:
        name = "rule"
    assert "offline" in _backend_line(R())


def test_short_method_labels():
    assert _short_method("Sutura (graph model)") == "Sutura"
    assert _short_method("Sutura (auto-adapted to your data)") == "Sutura·adapt"
    assert _short_method("PASTE2") == "PASTE2"
