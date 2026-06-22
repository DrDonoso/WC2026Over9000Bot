"""Tests for worldcup_bot.data.tongo — GIF listing."""

from __future__ import annotations

from pathlib import Path

import pytest

from worldcup_bot.data.gifs import list_tongo_gifs


class TestListTongoGifs:
    def test_returns_gif_and_mp4(self, tmp_path):
        """Supported suffixes are returned; txt is excluded."""
        (tmp_path / "a.gif").write_bytes(b"GIF89a")
        (tmp_path / "b.mp4").write_bytes(b"\x00")
        (tmp_path / "c.txt").write_text("skip me")
        result = list_tongo_gifs(tmp_path)
        names = [p.name for p in result]
        assert "a.gif" in names
        assert "b.mp4" in names
        assert "c.txt" not in names

    def test_result_is_sorted(self, tmp_path):
        """Files come back in sorted order."""
        (tmp_path / "z.gif").write_bytes(b"GIF89a")
        (tmp_path / "a.mp4").write_bytes(b"\x00")
        result = list_tongo_gifs(tmp_path)
        assert result == sorted(result)

    def test_nonexistent_dir_returns_empty(self):
        """Missing directory is tolerated — returns []."""
        result = list_tongo_gifs(Path("/nonexistent/dir/tongo_gifs_xyz"))
        assert result == []

    def test_empty_dir_returns_empty(self, tmp_path):
        """Empty directory returns []."""
        result = list_tongo_gifs(tmp_path)
        assert result == []

    def test_webp_included(self, tmp_path):
        """.webp files are included in the pool."""
        (tmp_path / "anim.webp").write_bytes(b"\x52\x49\x46\x46")
        result = list_tongo_gifs(tmp_path)
        assert len(result) == 1
        assert result[0].suffix == ".webp"

    def test_uppercase_suffix_included(self, tmp_path):
        """Suffix check is case-insensitive (.GIF → included)."""
        (tmp_path / "BIG.GIF").write_bytes(b"GIF89a")
        result = list_tongo_gifs(tmp_path)
        assert len(result) == 1

