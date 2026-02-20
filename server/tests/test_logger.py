"""Tests for the logger utility — agent thread file naming."""

from __future__ import annotations

from unittest.mock import patch

from src.utils import logger


class TestSaveAgentThread:
    """Tests for save_agent_thread file naming."""

    def test_microsecond_precision_prevents_collision(self, tmp_path) -> None:
        """Two calls in the same second should produce different file names."""
        run_dir = tmp_path / "agents" / "test_run"
        run_dir.mkdir(parents=True)

        token = logger._agents_run_dir_var.set(run_dir)
        try:
            with patch.object(logger, "_write_to_file", True):
                path_a = logger.save_agent_thread("TestAgent", {"call": 1})
                path_b = logger.save_agent_thread("TestAgent", {"call": 2})

            assert path_a is not None
            assert path_b is not None
            assert path_a != path_b
            # Both files should exist on disk.
            assert len(list(run_dir.glob("TestAgent_*.json"))) == 2
        finally:
            logger._agents_run_dir_var.reset(token)

    def test_filename_contains_microseconds(self, tmp_path) -> None:
        """File names should contain microsecond-precision timestamps."""
        run_dir = tmp_path / "agents" / "test_run"
        run_dir.mkdir(parents=True)

        token = logger._agents_run_dir_var.set(run_dir)
        try:
            with patch.object(logger, "_write_to_file", True):
                path = logger.save_agent_thread("TestAgent", {"key": "value"})

            assert path is not None
            # %Y-%m-%d_%H-%M-%S-%f → e.g. 2026-02-20_09-48-14-123456
            # Should have 6 digit microsecond suffix after the last dash.
            name = path.rsplit("/", 1)[-1]  # TestAgent_2026-...json
            stem = name.removesuffix(".json")
            parts = stem.split("_", 1)  # ["TestAgent", "2026-..."]
            ts = parts[1]
            # The microsecond suffix is the last group after the final dash.
            # e.g. "2026-02-20_10-52-47-173051" → last segment is "173051"
            segments = ts.split("-")
            microseconds = segments[-1]
            assert len(microseconds) == 6, f"Expected 6-digit microseconds, got '{microseconds}'"
            assert microseconds.isdigit(), f"Expected digits, got '{microseconds}'"
        finally:
            logger._agents_run_dir_var.reset(token)

    def test_skipped_when_write_disabled(self) -> None:
        """Should return None when WRITE_TO_FILE is not enabled."""
        with patch.object(logger, "_write_to_file", False):
            result = logger.save_agent_thread("TestAgent", {"key": "value"})
        assert result is None

    def test_skipped_when_no_run_dir(self) -> None:
        """Should return None when no run directory is set."""
        token = logger._agents_run_dir_var.set(None)
        try:
            with patch.object(logger, "_write_to_file", True):
                result = logger.save_agent_thread("TestAgent", {"key": "value"})
            assert result is None
        finally:
            logger._agents_run_dir_var.reset(token)
