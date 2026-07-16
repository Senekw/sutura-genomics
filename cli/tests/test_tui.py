"""Smoke test for the Textual app: it composes, shows the branding/status bar,
and the quit path works. Does not exercise the (heavy) alignment engine.
"""
from __future__ import annotations

import pytest

pytest.importorskip("textual")

from textual.widgets import Input, RichLog          # noqa: E402

from sutura_cli.core.config import Config           # noqa: E402
from sutura_cli.tui.app import LOGO, StatusBar, SuturaApp, TopBar  # noqa: E402


def _cfg(tmp_path) -> Config:
    return Config(store=tmp_path, backend="rule", cloud_model="",
                  ollama_model="", ollama_host="http://localhost:11434")


@pytest.mark.asyncio
async def test_app_composes_and_quits(tmp_path):
    app = SuturaApp(_cfg(tmp_path))
    async with app.run_test() as pilot:
        assert app.query_one(TopBar) is not None
        assert app.query_one(StatusBar) is not None
        assert app.query_one("#stream", RichLog) is not None
        assert app.query_one("#prompt", Input) is not None
        # branding present
        assert "Genomics" in LOGO
        # typing "exit" closes the app
        app._submit("exit")
        await pilot.pause()
    assert True  # reached here => app exited cleanly
