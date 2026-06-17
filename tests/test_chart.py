"""Tests for porra/chart.py — render_evolution_png writes a valid PNG."""

from __future__ import annotations

import os
import struct

import pytest


def _is_png(path: str) -> bool:
    """Check the PNG magic bytes signature."""
    try:
        with open(path, "rb") as f:
            header = f.read(8)
        return header == b"\x89PNG\r\n\x1a\n"
    except Exception:
        return False


class TestRenderEvolutionPng:
    def test_multi_date_history_writes_non_empty_png(self, tmp_path):
        from worldcup_bot.porra.chart import render_evolution_png

        history = {
            "2026-06-13": {
                "alice": {"pos": 1, "pts": 3.0, "name": "Alice"},
                "bob": {"pos": 2, "pts": 2.0, "name": "Bob"},
            },
            "2026-06-14": {
                "alice": {"pos": 2, "pts": 4.0, "name": "Alice"},
                "bob": {"pos": 1, "pts": 5.0, "name": "Bob"},
            },
            "2026-06-15": {
                "alice": {"pos": 1, "pts": 6.0, "name": "Alice"},
                "bob": {"pos": 2, "pts": 5.5, "name": "Bob"},
            },
        }
        out = str(tmp_path / "evolucion.png")
        result = render_evolution_png(history, out)
        assert result == out
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0
        assert _is_png(out)

    def test_single_checkpoint_degenerate_case(self, tmp_path):
        """One date → single column of markers. Should still write a valid PNG."""
        from worldcup_bot.porra.chart import render_evolution_png

        history = {
            "2026-06-13": {
                "alice": {"pos": 1, "pts": 3.0, "name": "Alice"},
                "bob": {"pos": 2, "pts": 2.0, "name": "Bob"},
                "carlos": {"pos": 3, "pts": 1.5, "name": "Carlos"},
            }
        }
        out = str(tmp_path / "single.png")
        render_evolution_png(history, out)
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0
        assert _is_png(out)

    def test_empty_history_writes_file(self, tmp_path):
        """Empty history should gracefully produce a file (message chart)."""
        from worldcup_bot.porra.chart import render_evolution_png

        out = str(tmp_path / "empty.png")
        render_evolution_png({}, out)
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0
        assert _is_png(out)

    def test_empty_dates_but_no_users(self, tmp_path):
        """A history with dates but empty user dicts."""
        from worldcup_bot.porra.chart import render_evolution_png

        history = {"2026-06-13": {}, "2026-06-14": {}}
        out = str(tmp_path / "nousers.png")
        render_evolution_png(history, out)
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0

    def test_many_participants_fits_in_file(self, tmp_path):
        """12 participants × 5 dates should still render cleanly."""
        from worldcup_bot.porra.chart import render_evolution_png

        users = [f"user{i}" for i in range(1, 13)]
        dates = ["2026-06-13", "2026-06-14", "2026-06-15", "2026-06-16", "2026-06-17"]
        history = {}
        for j, d in enumerate(dates):
            history[d] = {u: {"pos": (i + j) % 12 + 1, "pts": float(j + 1), "name": u.title()} for i, u in enumerate(users)}

        out = str(tmp_path / "many.png")
        render_evolution_png(history, out)
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0
        assert _is_png(out)

    def test_returns_out_path(self, tmp_path):
        from worldcup_bot.porra.chart import render_evolution_png

        out = str(tmp_path / "ret.png")
        result = render_evolution_png({"2026-06-13": {"u": {"pos": 1, "pts": 1.0, "name": "U"}}}, out)
        assert result == out

    def test_no_gui_window_opened(self, tmp_path):
        """Importing chart module and rendering must not attempt to open a display."""
        import matplotlib
        # The backend should be Agg (set at module import time)
        import worldcup_bot.porra.chart as chart_mod  # noqa: F401
        assert matplotlib.get_backend().lower() == "agg"

    def test_chart_title_has_no_emoji(self, tmp_path, monkeypatch):
        """render_evolution_png title must NOT contain emoji (DejaVu has no emoji glyph)."""
        import matplotlib.axes
        from worldcup_bot.porra.chart import render_evolution_png

        titles: list[str] = []
        _orig = matplotlib.axes.Axes.set_title

        def spy(self, label, *args, **kwargs):
            titles.append(label)
            return _orig(self, label, *args, **kwargs)

        monkeypatch.setattr(matplotlib.axes.Axes, "set_title", spy)

        out = str(tmp_path / "emoji_check.png")
        render_evolution_png(
            {"2026-06-13": {"u": {"pos": 1, "pts": 1.0, "name": "U"}}}, out
        )

        assert titles, "set_title should have been called"
        assert all("📈" not in t for t in titles), (
            f"Emoji found in chart title(s): {titles}"
        )

    def test_x_labels_are_short_date_format(self, tmp_path, monkeypatch):
        """X-axis tick labels should be DD/MM (short friendly form), not YYYY-MM-DD."""
        import matplotlib.axes
        from worldcup_bot.porra.chart import render_evolution_png

        captured: list[str] = []
        _orig = matplotlib.axes.Axes.set_xticklabels

        def spy(self, labels, *args, **kwargs):
            captured.extend(list(labels))
            return _orig(self, labels, *args, **kwargs)

        monkeypatch.setattr(matplotlib.axes.Axes, "set_xticklabels", spy)

        out = str(tmp_path / "xlabels.png")
        render_evolution_png(
            {
                "2026-06-13": {"u": {"pos": 1, "pts": 1.0, "name": "U"}},
                "2026-06-14": {"u": {"pos": 2, "pts": 2.0, "name": "U"}},
            },
            out,
        )

        assert "13/06" in captured
        assert "14/06" in captured
        # Old YYYY-MM-DD format must not appear
        assert "2026-06-13" not in captured
        assert "2026-06-14" not in captured
