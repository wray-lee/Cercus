"""Tests for GroundTruthLogger — thread synchronization, async session opening.

Seam: GroundTruthLogger.open_session / log_event / log_kinematics_batch / flush / close
"""
import os
import tempfile
import pytest
from src.core.logger import GroundTruthLogger


def test_logger_async_open_session_and_logging():
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
