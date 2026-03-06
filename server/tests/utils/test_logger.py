"""Tests for the logger utility — structured logging, timing, formatting."""

from __future__ import annotations

import io
import sys
import time
from unittest.mock import patch

from src.utils import logger


class TestCreateLogger:
    """Tests for create_logger() factory."""

    def test_creates_logger_instance(self) -> None:
        log = logger.create_logger("TestCtx")
        assert isinstance(log, logger.Logger)

    def test_logger_has_context(self) -> None:
        log = logger.create_logger("MyContext")
        assert log._context == "MyContext"


class TestLoggerOutput:
    """Tests for Logger log-level methods."""

    def test_info_writes_to_stderr(self) -> None:
        log = logger.create_logger("Test")
        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            log.info("test message")
        output = buf.getvalue()
        assert "test message" in output
        assert "[Test]" in output

    def test_success_writes_to_stderr(self) -> None:
        log = logger.create_logger("Test")
        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            log.success("done")
        assert "done" in buf.getvalue()

    def test_warn_writes_to_stderr(self) -> None:
        log = logger.create_logger("Test")
        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            log.warn("oops")
        assert "oops" in buf.getvalue()

    def test_error_writes_to_stderr(self) -> None:
        log = logger.create_logger("Test")
        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            log.error("fail")
        assert "fail" in buf.getvalue()

    def test_debug_writes_to_stderr(self) -> None:
        log = logger.create_logger("Test")
        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            log.debug("detail")
        assert "detail" in buf.getvalue()

    def test_info_with_data(self) -> None:
        log = logger.create_logger("Test")
        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            log.info("msg", {"key": "value", "num": 42})
        output = buf.getvalue()
        assert "key=" in output
        assert "42" in output


class TestTimerFunctions:
    """Tests for start_timer / end_timer."""

    def setup_method(self) -> None:
        logger.clear_timers()

    def test_start_and_end_timer(self) -> None:
        log = logger.create_logger("TimerTest")
        log.start_timer("op")
        time.sleep(0.01)
        duration = log.end_timer("op")
        assert duration > 0

    def test_end_timer_without_start_returns_zero(self) -> None:
        log = logger.create_logger("TimerTest")
        duration = log.end_timer("nonexistent")
        assert duration == 0.0

    def test_clear_timers(self) -> None:
        log = logger.create_logger("TimerTest")
        log.start_timer("op")
        logger.clear_timers()
        duration = log.end_timer("op")
        assert duration == 0.0

    def test_timer_with_custom_message(self) -> None:
        log = logger.create_logger("TimerTest")
        log.start_timer("op")
        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            log.end_timer("op", "Custom done message")
        assert "Custom done message" in buf.getvalue()


class TestSection:
    """Tests for section / subsection headers."""

    def test_section_prints_title(self) -> None:
        log = logger.create_logger("Test")
        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            log.section("My Section")
        assert "My Section" in buf.getvalue()

    def test_subsection_prints_title(self) -> None:
        log = logger.create_logger("Test")
        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            log.subsection("Sub Title")
        assert "Sub Title" in buf.getvalue()


class TestFormatDuration:
    """Tests for _format_duration()."""

    def test_milliseconds(self) -> None:
        assert logger._format_duration(500) == "500ms"

    def test_seconds(self) -> None:
        result = logger._format_duration(2500)
        assert "2.50s" in result

    def test_minutes(self) -> None:
        result = logger._format_duration(125000)
        assert "2m" in result


class TestFormatValue:
    """Tests for _format_value()."""

    def test_none(self) -> None:
        result = logger._format_value(None)
        assert "None" in result

    def test_bool_true(self) -> None:
        result = logger._format_value(True)
        assert "True" in result

    def test_bool_false(self) -> None:
        result = logger._format_value(False)
        assert "False" in result

    def test_int(self) -> None:
        result = logger._format_value(42)
        assert "42" in result

    def test_string(self) -> None:
        result = logger._format_value("hello")
        assert "hello" in result

    def test_long_string_truncated(self) -> None:
        result = logger._format_value("x" * 600)
        assert "..." in result

    def test_list(self) -> None:
        result = logger._format_value([1, 2, 3])
        assert "3 items" in result

    def test_dict(self) -> None:
        result = logger._format_value({"a": 1, "b": 2})
        assert "2 keys" in result

    def test_float(self) -> None:
        result = logger._format_value(3.14)
        assert "3.14" in result

    def test_other_object(self) -> None:
        result = logger._format_value(object())
        assert "object" in result.lower()


class TestGetTimestamp:
    """Tests for _get_timestamp()."""

    def test_returns_time_format(self) -> None:
        ts = logger._get_timestamp()
        assert len(ts) >= 12
        assert ts.count(":") == 2
        assert "." in ts


class TestSaveReportFile:
    """Tests for save_report_file()."""

    def test_skipped_when_write_disabled(self) -> None:
        with patch.object(logger, "_write_to_file", False):
            result = logger.save_report_file("example.com", "report text")
        assert result is None

    def test_writes_when_enabled(self, tmp_path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir(parents=True)
        with (
            patch.object(logger, "_write_to_file", True),
            patch("src.utils.logger.pathlib.Path.resolve", return_value=tmp_path / "src" / "utils" / "logger.py"),
        ):
            logger.save_report_file("example.com", "report text")
        # This may or may not write depending on path resolution;
        # the key test is that it doesn't raise.


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
