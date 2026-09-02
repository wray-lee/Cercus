"""Tests for GroundTruthLogger — bounded buffering, drop tracking, critical event preservation,
FIFO ordering, session lifecycle, and thread shutdown safety.

Seam: GroundTruthLogger (open_session, log_event, log_kinematics_batch, advance_trial, flush, close, shutdown)
"""
import os
import tempfile
import time
from typing import List

import pytest
from src.core.logger import DEFAULT_MAX_KINEMATICS_BATCHES, GroundTruthLogger


def test_logger_async_open_session_and_logging() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = GroundTruthLogger(tmpdir)
        headers = ["sys_time", "ard_time", "dx", "dy", "dz", "stim_state", "g_id"]

        logger.open_session("subject_test", 1, headers)
        assert logger.is_open() is True

        logger.log_event("trial_start", 1.0, trial_type="looming")
        logger.log_kinematics_batch([
            ["1.000000", 100, 1.0, 2.0, 0.0, 0, 1]
        ])

        logger.flush()
        logger.close()
        logger.shutdown()

        event_file = os.path.join(tmpdir, "subject_test_session_1_events.csv")
        kin_file = os.path.join(tmpdir, "subject_test_session_1_kinematics.csv")

        assert os.path.exists(event_file)
        assert os.path.exists(kin_file)

        with open(event_file, "r", encoding="utf-8-sig") as f:
            content = f.read()
            assert "trial_start" in content
            assert "looming" in content

        with open(kin_file, "r", encoding="utf-8-sig") as f:
            content = f.read()
            assert "sys_time" in content
            assert "100" in content


def test_bounded_kinematics_buffering_and_drop_tracking() -> None:
    """Verify that kinematics buffer is bounded and tracks drops under backpressure.

    Tradeoff: Under sustained unrecoverable disk stall, kinematics batches are
    dropped to bound memory and keep the stimulus loop nonblocking.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Small bound to trigger drop behavior deterministically
        logger = GroundTruthLogger(tmpdir, max_kinematics_batches=3)
        headers = ["sys_time", "ard_time", "dx", "dy", "dz", "stim_state", "g_id"]
        logger.open_session("subject_drop_test", 1, headers)

        assert logger.dropped_kinematics_batches == 0
        assert logger.dropped_kinematics_rows == 0

        # Temporarily acquire lock or flood batches before writer thread can write
        # In fact, let's flood 50 batches of 5 rows each
        # Even if writer is fast, sending 50 batches instantaneously with bound 3
        # should either drop or writer will process, but if we test with bound 1 and lock held:
        with logger._lock:
            # Fill the kinematics queue to capacity
            for i in range(10):
                logger.log_kinematics_batch([[f"{i}.0", 100, 1.0, 2.0, 0.0, 0, 1]] * 4)

            # Inside lock, buffer reached max_kinematics_batches (3), remaining 7 batches dropped
            assert logger.dropped_kinematics_batches == 7
            assert logger.dropped_kinematics_rows == 28  # 7 batches * 4 rows

        logger.flush()
        logger.shutdown()

        # Observable drop stats remain accessible after flush/shutdown
        assert logger.dropped_kinematics_batches == 7
        assert logger.dropped_kinematics_rows == 28


def test_critical_events_preserved_during_kinematics_overflow() -> None:
    """Verify that critical events are never dropped even when kinematics overflow.

    Control/event channel is separated from bulk kinematics channel.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = GroundTruthLogger(tmpdir, max_kinematics_batches=2)
        headers = ["sys_time", "ard_time", "dx", "dy", "dz", "stim_state", "g_id"]
        logger.open_session("subject_event_preservation", 1, headers)

        # Flood kinematics under simulated stall
        with logger._lock:
            for i in range(20):
                logger.log_kinematics_batch([[f"{i}.0", 100, 1.0, 2.0, 0.0, 0, 1]])

            # Log critical lifecycle and paradigm events during the overflow
            logger.log_event("trial_start", 1.0, trial_idx=1, stim_type="looming")
            logger.log_event("stimulus_onset", 1.5, angle=90.0)
            logger.log_event("trial_stop", 2.5)
            logger.log_event("trial_verdict", 2.6, verdict="escape", latency=0.25)

        # Confirm drops happened in kinematics channel
        assert logger.dropped_kinematics_batches == 18

        logger.flush()
        logger.shutdown()

        event_file = os.path.join(tmpdir, "subject_event_preservation_session_1_events.csv")
        assert os.path.exists(event_file)
        with open(event_file, "r", encoding="utf-8-sig") as f:
            content = f.read()
            assert "trial_start" in content
            assert "stimulus_onset" in content
            assert "trial_stop" in content
            assert "trial_verdict" in content
            assert "escape" in content


def test_fifo_ordering_and_multi_session_lifecycle() -> None:
    """Verify FIFO ordering within channels and clean multi-session lifecycle."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = GroundTruthLogger(tmpdir)
        headers = ["sys_time", "ard_time", "dx", "dy", "dz", "stim_state", "g_id"]

        # Session 1
        logger.open_session("subject_fifo", 1, headers)
        logger.log_event("s1_start", 1.0)
        logger.log_kinematics_batch([["1.100000", 1, 0.1, 0.1, 0.0, 0, 1]])
        logger.log_event("s1_mid", 2.0)
        logger.log_kinematics_batch([["2.100000", 2, 0.2, 0.2, 0.0, 0, 1]])
        logger.log_event("s1_stop", 3.0)
        logger.close()

        # Session 2
        logger.open_session("subject_fifo", 2, headers)
        logger.log_event("s2_start", 10.0)
        logger.log_kinematics_batch([["10.100000", 10, 0.5, 0.5, 0.0, 0, 2]])
        logger.log_event("s2_stop", 12.0)
        logger.close()

        logger.shutdown()

        # Verify Session 1 files
        s1_event_file = os.path.join(tmpdir, "subject_fifo_session_1_events.csv")
        s1_kin_file = os.path.join(tmpdir, "subject_fifo_session_1_kinematics.csv")
        with open(s1_event_file, "r", encoding="utf-8-sig") as f:
            lines = [line.strip() for line in f if line.strip()]
            assert len(lines) == 4  # Header + 3 events
            assert "s1_start" in lines[1]
            assert "s1_mid" in lines[2]
            assert "s1_stop" in lines[3]
        with open(s1_kin_file, "r", encoding="utf-8-sig") as f:
            kin_lines = [line.strip() for line in f if line.strip()]
            assert len(kin_lines) == 3  # Header + 2 kin rows
            assert "1.100000" in kin_lines[1]
            assert "2.100000" in kin_lines[2]

        # Verify Session 2 files
        s2_event_file = os.path.join(tmpdir, "subject_fifo_session_2_events.csv")
        s2_kin_file = os.path.join(tmpdir, "subject_fifo_session_2_kinematics.csv")
        with open(s2_event_file, "r", encoding="utf-8-sig") as f:
            lines = [line.strip() for line in f if line.strip()]
            assert len(lines) == 3  # Header + 2 events
            assert "s2_start" in lines[1]
            assert "s2_stop" in lines[2]


def test_shutdown_and_flush_completion_no_deadlock() -> None:
    """Verify flush and shutdown complete without deadlock or thread leak."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = GroundTruthLogger(tmpdir)
        headers = ["sys_time", "ard_time", "dx", "dy", "dz", "stim_state", "g_id"]
        logger.open_session("subject_shutdown", 1, headers)

        for i in range(20):
            logger.log_kinematics_batch([[f"{i}.000", i, 0.0, 0.0, 0.0, 0, 1]])
            logger.log_event("evt", float(i), idx=i)

        assert logger.flush(timeout=5.0) is True
        logger.shutdown(timeout=5.0)

        # Thread must be stopped
        assert not logger._writer_thread.is_alive()


def test_advance_trial_and_cache_preservation() -> None:
    """Verify trial advancement increments IDs and saves trial cache to disk."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = GroundTruthLogger(tmpdir)
        headers = ["sys_time", "ard_time", "dx", "dy", "dz", "stim_state", "g_id"]
        logger.open_session("subject_cache", 1, headers)

        assert logger.global_trial_id == 0
        assert logger.trial_in_session == 0

        logger.advance_trial()
        assert logger.global_trial_id == 1
        assert logger.trial_in_session == 1

        logger.advance_trial()
        assert logger.global_trial_id == 2
        assert logger.trial_in_session == 2

        logger.flush()
        logger.shutdown()

        # Cache file must have been written
        cache_path = os.path.join(tmpdir, ".trial_cache.txt")
        assert os.path.exists(cache_path)
        with open(cache_path, "r") as f:
            assert f.read().strip() == "2"

        # New logger instance must load cached global_trial_id
        logger2 = GroundTruthLogger(tmpdir)
        assert logger2.global_trial_id == 2
        logger2.shutdown()
