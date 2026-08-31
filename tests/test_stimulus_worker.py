"""Tests for stimulus_worker — IPC queues, lifecycle, abort handling, and execution.

Seam: src.workers.stimulus_worker -> GenericWorker, worker_entry, create_ipc_queues
"""
import multiprocessing as mp
import os
import queue
import signal
import sys
import tempfile
import time
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.core.hardware import MockSerialDaemon
from src.core.kinematics import KinematicEngine
from src.workers.stimulus_worker import (
    ABORT_KEY,
    ExperimentAbort,
    GenericWorker,
    HardwareDisconnectError,
    _shutdown_event,
    _term_handler,
    create_ipc_queues,
    worker_entry,
)



def _make_config(tmp_dir: str, **overrides: Any) -> Dict[str, Any]:
    """Helper to build a valid worker configuration dictionary."""
    base_config: Dict[str, Any] = {
        "Paradigm Class": "Looming",
        "Subject ID": "sub_test",
        "Session Number": 1,
        "Total Sessions": 1,
        "Experiment Pattern": "Baseline Visual",
        "Number of Repetitions": 1,
        "Execution Mode": "Auto",
        "Serial Port": "mock",
        "Debug Mode": True,
        "Screen Width (px)": 800,
        "Screen Height (px)": 600,
        "Stimulus Screen ID": 0,
        "ITI Range (sec)": "0-0",
        "ISI Range (sec)": "0-0",
        "Random Seed": 42,
        "_output_dir": tmp_dir,
    }
    base_config.update(overrides)
    return base_config



class FakeClock:
    """Mock PsychoPy Clock with controllable time."""

    def __init__(self, start_time: float = 0.0, step: float = 0.2) -> None:
        self.curr_time = start_time
        self.step = step

    def getTime(self) -> float:
        t = self.curr_time
        self.curr_time += self.step
        return t


class FakeEvent:
    """Mock PsychoPy event module."""

    def __init__(
        self,
        key_queue: Any = None,
        auto_space: bool = False,
        default_key: Any = None,
    ) -> None:
        self.key_queue: List[str] = list(key_queue or [])
        self.globalKeys = MagicMock()
        self.cleared = False
        self.auto_space = auto_space
        self.default_key = default_key

    def getKeys(self) -> List[str]:
        if self.key_queue:
            return [self.key_queue.pop(0)]
        if self.default_key:
            return [self.default_key]
        if self.auto_space:
            return ["space"]
        return []

    def clearEvents(self) -> None:
        self.cleared = True




def test_create_ipc_queues() -> None:
    """Verify create_ipc_queues allocates expected queue capacities."""
    cmd_q, tel_q = create_ipc_queues()
    assert isinstance(cmd_q, mp.queues.Queue)
    assert isinstance(tel_q, mp.queues.Queue)
    cmd_q.cancel_join_thread()
    tel_q.cancel_join_thread()


def test_term_handler_and_exceptions() -> None:
    """Verify signal term handler sets event and exceptions instantiate."""
    _shutdown_event.clear()
    assert not _shutdown_event.is_set()
    _term_handler(signal.SIGTERM, None)
    assert _shutdown_event.is_set()
    _shutdown_event.clear()

    e1 = ExperimentAbort("abort message")
    assert str(e1) == "abort message"

    e2 = HardwareDisconnectError("disconnect message")
    assert str(e2) == "disconnect message"


def test_sanitize_metrics() -> None:
    """Verify _sanitize_metrics formats arrays, lists, dicts, and scalars."""
    raw_metrics = {
        "short_arr": np.array([1, 2, 3]),
        "long_arr": np.zeros((10, 10)),
        "short_list": [1, 2, 3],
        "long_list": list(range(20)),
        "sub_dict": {"a": 1},
        "scalar_int": 42,
        "scalar_str": "hello",
    }
    sanitized = GenericWorker._sanitize_metrics(raw_metrics)
    assert sanitized["short_arr"] == [1, 2, 3]
    assert sanitized["long_arr"] == "[array:(10, 10)]"
    assert sanitized["short_list"] == [1, 2, 3]
    assert sanitized["long_list"] == "[list:20]"
    assert sanitized["sub_dict"] == "[dict:1]"
    assert sanitized["scalar_int"] == 42
    assert sanitized["scalar_str"] == "hello"


def test_worker_init_and_calib_matrix() -> None:
    """Verify GenericWorker initialization and calibration matrix setup."""
    with tempfile.TemporaryDirectory() as tmpdir:
        matrix = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        cfg = _make_config(tmpdir, calib_matrix=matrix, calib_factors={"dx": 1.0})
        cmd_q = mp.Queue()
        tel_q = mp.Queue()
        worker = GenericWorker(cfg, cmd_q, tel_q)

        assert worker.config == cfg
        assert worker.abort_flag is False
        assert worker._ard_time_idx >= 0
        cmd_q.cancel_join_thread()
        tel_q.cancel_join_thread()


def test_push_and_push_debounced() -> None:
    """Verify telemetry pushing with debouncing, force push, and queue error handling."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = _make_config(tmpdir)
        cmd_q = mp.Queue()
        tel_q = mp.Queue(maxsize=2)
        worker = GenericWorker(cfg, cmd_q, tel_q)

        # First debounced push
        worker._push_telemetry_debounced(1, 0, 1, {"phase": "Adapt"}, hw_tel={"dx": 1.0})
        item = tel_q.get(timeout=0.5)
        assert item["action"] == "telemetry"

        # Immediate second push gets debounced (skipped)
        worker._push_telemetry_debounced(1, 0, 1, {"phase": "Adapt"})
        with pytest.raises(queue.Empty):
            tel_q.get(timeout=0.05)

        # Force push bypassing debounce
        worker._push({"action": "forced_msg"}, force=True)
        forced = tel_q.get(timeout=0.5)
        assert forced["action"] == "forced_msg"

        # Force push on full queue sets abort_flag
        mock_full_q = MagicMock()
        mock_full_q.put.side_effect = queue.Full()
        worker.telemetry_queue = mock_full_q
        worker._push({"action": "forced_full"}, force=True)
        assert worker.abort_flag is True

        # BrokenPipe sets abort_flag
        mock_broken_q = MagicMock()
        mock_broken_q.put_nowait.side_effect = BrokenPipeError()
        worker.telemetry_queue = mock_broken_q
        worker.abort_flag = False
        worker._last_telemetry_push = 0.0
        worker._push_telemetry_debounced(1, 0, 1, {"phase": "Adapt"})
        assert worker.abort_flag is True

        cmd_q.cancel_join_thread()
        tel_q.cancel_join_thread()


def test_sync_state_abort_scenarios() -> None:
    """Verify _sync_state detects shutdown event, abort flag, and queue commands."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = _make_config(tmpdir)
        cmd_q = queue.Queue()
        tel_q = queue.Queue()
        worker = GenericWorker(cfg, cmd_q, tel_q)  # type: ignore
        fake_event = FakeEvent()
        worker.event = fake_event

        # 1. Normal sync state
        worker._sync_state(clear_keys=True)

        # 2. _shutdown_event set -> raises ExperimentAbort
        _shutdown_event.set()
        with pytest.raises(ExperimentAbort, match="Received abort command"):
            worker._sync_state()
        _shutdown_event.clear()

        # 3. abort_flag set -> raises ExperimentAbort
        worker.abort_flag = True
        with pytest.raises(ExperimentAbort, match="Received abort command"):
            worker._sync_state()
        worker.abort_flag = False

        # 4. Command queue ABORT -> raises ExperimentAbort
        cmd_q.put({"action": "ABORT"})
        with pytest.raises(ExperimentAbort, match="Received abort command"):
            worker._sync_state()
        worker.abort_flag = False

        # 5. Command queue POISON_PILL -> raises ExperimentAbort
        cmd_q.put({"action": "POISON_PILL"})
        with pytest.raises(ExperimentAbort, match="Received abort command"):
            worker._sync_state()



def test_drain_hardware_and_kinematics_injection() -> None:
    """Verify _drain_hardware processes telemetry rows and updates kinematics."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = _make_config(tmpdir)
        cmd_q = mp.Queue()
        tel_q = mp.Queue()
        worker = GenericWorker(cfg, cmd_q, tel_q)
        worker.kinematic_engine.reset()

        mock_hw = MagicMock()
        mock_hw.drain_queue.return_value = [
            (1.0, "100,5,0,0,0"),
            (1.05, "150,5,0,0,0"),
        ]
        mock_logger = MagicMock()
        mock_logger.is_open.return_value = True
        mock_logger.global_trial_id = 1

        hw_tel = worker._drain_hardware(mock_logger, mock_hw)
        assert hw_tel["k_disp"] > 0.0
        assert mock_logger.log_kinematics_batch.called

        worker._kinematic_error_handler("timing_error", "test msg", (1.0, 2.0))
        cmd_q.cancel_join_thread()
        tel_q.cancel_join_thread()


def test_worker_run_full_execution() -> None:
    """Verify GenericWorker.run full lifecycle in Auto mode."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = _make_config(tmpdir, **{"Execution Mode": "Auto"})
        cmd_q = mp.Queue()
        tel_q = mp.Queue()
        worker = GenericWorker(cfg, cmd_q, tel_q)

        fake_clock = FakeClock(step=0.2)
        fake_event = FakeEvent(auto_space=True)

        mock_psychopy = MagicMock()
        mock_psychopy.core.Clock.return_value = fake_clock
        mock_psychopy.event = fake_event

        mock_renderer = MagicMock()
        mock_logger = MagicMock()
        mock_logger.is_open.return_value = True

        with patch.dict(sys.modules, {"psychopy": mock_psychopy, "psychopy.core": mock_psychopy.core, "psychopy.event": fake_event}):
            with patch("src.workers.stimulus_worker.CoreRenderer", return_value=mock_renderer):
                with patch("src.workers.stimulus_worker.GroundTruthLogger", return_value=mock_logger):
                    with patch("src.workers.stimulus_worker.adaption_duration", 0.02):
                        with patch("src.workers.stimulus_worker.initial_baseline_dur", 0.02):
                            worker.run()

        # Collect emitted telemetry actions
        actions = []
        errors = []
        while not tel_q.empty():
            item = tel_q.get_nowait()
            actions.append(item.get("action"))
            if "error" in item:
                errors.append(item["error"])

        if errors:
            print(f"DEBUG WORKER ERRORS: {errors}")

        assert "worker_done" in actions
        assert "trial_verdict" in actions
        assert mock_renderer.close.called
        assert mock_logger.shutdown.called

        cmd_q.cancel_join_thread()
        tel_q.cancel_join_thread()




def test_worker_run_abort_handling() -> None:
    """Verify GenericWorker.run handles abort exception cleanly and pushes worker_abort."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = _make_config(tmpdir, **{"Execution Mode": "Auto"})
        cmd_q = mp.Queue()
        tel_q = mp.Queue()
        worker = GenericWorker(cfg, cmd_q, tel_q)

        fake_clock = FakeClock()
        fake_event = FakeEvent()

        mock_psychopy = MagicMock()
        mock_psychopy.core.Clock.return_value = fake_clock
        mock_psychopy.event = fake_event

        mock_renderer = MagicMock()
        mock_logger = MagicMock()

        # Inject ABORT key immediately during adaptation
        fake_event.keys_to_return = [ABORT_KEY]

        with patch.dict(sys.modules, {"psychopy": mock_psychopy, "psychopy.core": mock_psychopy.core, "psychopy.event": fake_event}):
            with patch("src.workers.stimulus_worker.CoreRenderer", return_value=mock_renderer):
                with patch("src.workers.stimulus_worker.GroundTruthLogger", return_value=mock_logger):
                    with patch.object(worker, "_sync_state", side_effect=ExperimentAbort("Aborted")):
                        worker.run()

        actions = []
        while not tel_q.empty():
            actions.append(tel_q.get_nowait()["action"])

        assert "worker_abort" in actions

        cmd_q.cancel_join_thread()
        tel_q.cancel_join_thread()


def test_worker_run_hardware_disconnect_and_general_exception() -> None:
    """Verify GenericWorker.run handles hardware disconnect error and general exceptions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = _make_config(tmpdir, **{"Serial Port": "COM99"})
        cmd_q = mp.Queue()
        tel_q = mp.Queue()
        worker = GenericWorker(cfg, cmd_q, tel_q)

        fake_clock = FakeClock()
        fake_event = FakeEvent()

        mock_psychopy = MagicMock()
        mock_psychopy.core.Clock.return_value = fake_clock
        mock_psychopy.event = fake_event

        mock_renderer = MagicMock()
        mock_logger = MagicMock()
        mock_serial = MagicMock()
        mock_serial.is_alive.return_value = True

        with patch.dict(sys.modules, {"psychopy": mock_psychopy, "psychopy.core": mock_psychopy.core, "psychopy.event": fake_event}):
            with patch("src.workers.stimulus_worker.SerialDaemon", return_value=mock_serial):
                with patch("src.workers.stimulus_worker.CoreRenderer", return_value=mock_renderer):
                    with patch("src.workers.stimulus_worker.GroundTruthLogger", return_value=mock_logger):
                        with patch.object(worker, "_sync_state", side_effect=RuntimeError("Hardware failure")):
                            worker.run()

        actions = []
        while not tel_q.empty():
            item = tel_q.get_nowait()
            actions.append((item.get("action"), item.get("error")))

        assert any(a[0] == "worker_error" and "Hardware failure" in (a[1] or "") for a in actions)

        cmd_q.cancel_join_thread()
        tel_q.cancel_join_thread()


def test_worker_run_manual_and_kinematic_phases() -> None:
    """Verify GenericWorker.run execution in Manual and Kinematic wait modes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = _make_config(
            tmpdir,
            **{
                "Execution Mode": "Manual",
                "Kinematic Trigger": True,
                "Kinematic Threshold Dist (mm)": 5.0,
            }
        )
        cmd_q = mp.Queue()
        tel_q = mp.Queue()
        worker = GenericWorker(cfg, cmd_q, tel_q)

        fake_clock = FakeClock(step=0.2)
        fake_event = FakeEvent(auto_space=True)

        mock_psychopy = MagicMock()
        mock_psychopy.core.Clock.return_value = fake_clock
        mock_psychopy.event = fake_event

        mock_renderer = MagicMock()
        mock_logger = MagicMock()
        mock_logger.is_open.return_value = True

        with patch.dict(sys.modules, {"psychopy": mock_psychopy, "psychopy.core": mock_psychopy.core, "psychopy.event": fake_event}):
            with patch("src.workers.stimulus_worker.CoreRenderer", return_value=mock_renderer):
                with patch("src.workers.stimulus_worker.GroundTruthLogger", return_value=mock_logger):
                    with patch("src.workers.stimulus_worker.adaption_duration", 0.01):
                        with patch("src.workers.stimulus_worker.initial_baseline_dur", 0.01):
                            # Force kinematic engine trigger to True
                            with patch.object(KinematicEngine, "evaluate_trigger", return_value=True):
                                worker.run()

        actions = []
        while not tel_q.empty():
            actions.append(tel_q.get_nowait()["action"])

        assert "worker_done" in actions

        cmd_q.cancel_join_thread()
        tel_q.cancel_join_thread()




def test_worker_run_multi_session_with_iti_and_isi() -> None:
    """Verify GenericWorker.run multi-session loop with ITI, ISI, and hw_cmd."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = _make_config(
            tmpdir,
            **{
                "Session Number": 1,
                "Total Sessions": 2,
                "ITI Range (sec)": "0.01-0.01",
                "ISI Range (sec)": "0.01-0.01",
            }
        )
        cmd_q = mp.Queue()
        tel_q = mp.Queue()
        worker = GenericWorker(cfg, cmd_q, tel_q)

        fake_clock = FakeClock(step=0.2)
        fake_event = FakeEvent(auto_space=True)

        mock_psychopy = MagicMock()
        mock_psychopy.core.Clock.return_value = fake_clock
        mock_psychopy.event = fake_event

        mock_renderer = MagicMock()
        mock_logger = MagicMock()
        mock_logger.is_open.return_value = True

        # Custom paradigm frame processing injecting a hw_cmd
        orig_process = worker.paradigm.process_frame

        def _custom_process(elap: float, trial: dict, hw_tel: dict) -> Any:
            is_done, cmds, tel = orig_process(elap, trial, hw_tel)
            tel["hw_cmd"] = "STIM_ON"
            return is_done, cmds, tel

        worker.paradigm.process_frame = _custom_process  # type: ignore

        with patch.dict(sys.modules, {"psychopy": mock_psychopy, "psychopy.core": mock_psychopy.core, "psychopy.event": fake_event}):
            with patch("src.workers.stimulus_worker.CoreRenderer", return_value=mock_renderer):
                with patch("src.workers.stimulus_worker.GroundTruthLogger", return_value=mock_logger):
                    with patch("src.workers.stimulus_worker.adaption_duration", 0.01):
                        with patch("src.workers.stimulus_worker.initial_baseline_dur", 0.01):
                            worker.run()

        actions = []
        while not tel_q.empty():
            actions.append(tel_q.get_nowait()["action"])

        assert "worker_done" in actions

        cmd_q.cancel_join_thread()
        tel_q.cancel_join_thread()


def test_worker_run_abort_during_wait_phases() -> None:
    """Verify GenericWorker.run abort during Auto, Manual, and Kinematic wait phases."""
    # 1. Abort in Auto wait
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = _make_config(tmpdir, **{"Execution Mode": "Auto"})
        cmd_q = mp.Queue()
        tel_q = mp.Queue()
        worker = GenericWorker(cfg, cmd_q, tel_q)

        fake_clock = FakeClock(step=0.2)
        fake_event = FakeEvent(default_key=ABORT_KEY)

        mock_psychopy = MagicMock()
        mock_psychopy.core.Clock.return_value = fake_clock
        mock_psychopy.event = fake_event

        with patch.dict(sys.modules, {"psychopy": mock_psychopy, "psychopy.core": mock_psychopy.core, "psychopy.event": fake_event}):
            with patch("src.workers.stimulus_worker.CoreRenderer", return_value=MagicMock()):
                with patch("src.workers.stimulus_worker.GroundTruthLogger", return_value=MagicMock()):
                    with patch("src.workers.stimulus_worker.adaption_duration", 0.0):
                        worker.run()

        actions = []
        while not tel_q.empty():
            actions.append(tel_q.get_nowait()["action"])
        assert "worker_abort" in actions
        cmd_q.cancel_join_thread()
        tel_q.cancel_join_thread()

    # 2. Abort in Manual wait
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = _make_config(tmpdir, **{"Execution Mode": "Manual"})
        cmd_q = mp.Queue()
        tel_q = mp.Queue()
        worker = GenericWorker(cfg, cmd_q, tel_q)

        fake_clock = FakeClock(step=0.2)
        fake_event = FakeEvent(default_key=ABORT_KEY)

        mock_psychopy = MagicMock()
        mock_psychopy.core.Clock.return_value = fake_clock
        mock_psychopy.event = fake_event

        with patch.dict(sys.modules, {"psychopy": mock_psychopy, "psychopy.core": mock_psychopy.core, "psychopy.event": fake_event}):
            with patch("src.workers.stimulus_worker.CoreRenderer", return_value=MagicMock()):
                with patch("src.workers.stimulus_worker.GroundTruthLogger", return_value=MagicMock()):
                    with patch("src.workers.stimulus_worker.adaption_duration", 0.0):
                        with patch("src.workers.stimulus_worker.initial_baseline_dur", 0.0):
                            worker.run()

        actions = []
        while not tel_q.empty():
            actions.append(tel_q.get_nowait()["action"])
        assert "worker_abort" in actions
        cmd_q.cancel_join_thread()
        tel_q.cancel_join_thread()



def test_worker_run_kinematic_mode_and_trigger() -> None:
    """Verify GenericWorker.run execution in Kinematic mode with kinematic trigger."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = _make_config(
            tmpdir,
            **{
                "Execution Mode": "Kinematic",
                "Trigger Dist Enabled": True,
                "Trigger Dist (mm)": 5.0,
            }
        )
        cmd_q = mp.Queue()
        tel_q = mp.Queue()
        worker = GenericWorker(cfg, cmd_q, tel_q)

        fake_clock = FakeClock(step=0.2)
        fake_event = FakeEvent(auto_space=True)

        mock_psychopy = MagicMock()
        mock_psychopy.core.Clock.return_value = fake_clock
        mock_psychopy.event = fake_event

        mock_renderer = MagicMock()
        mock_logger = MagicMock()
        mock_logger.is_open.return_value = True

        with patch.dict(sys.modules, {"psychopy": mock_psychopy, "psychopy.core": mock_psychopy.core, "psychopy.event": fake_event}):
            with patch("src.workers.stimulus_worker.CoreRenderer", return_value=mock_renderer):
                with patch("src.workers.stimulus_worker.GroundTruthLogger", return_value=mock_logger):
                    with patch("src.workers.stimulus_worker.adaption_duration", 0.01):
                        with patch("src.workers.stimulus_worker.initial_baseline_dur", 0.01):
                            with patch.object(KinematicEngine, "evaluate_trigger", return_value=True):
                                worker.run()

        actions = []
        while not tel_q.empty():
            actions.append(tel_q.get_nowait()["action"])

        assert "worker_done" in actions
        cmd_q.cancel_join_thread()
        tel_q.cancel_join_thread()


def test_worker_run_abort_during_kinematic_wait() -> None:
    """Verify GenericWorker.run abort during Kinematic wait phase."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = _make_config(
            tmpdir,
            **{
                "Execution Mode": "Kinematic",
                "Trigger Dist Enabled": True,
                "Trigger Dist (mm)": 5.0,
            }
        )
        cmd_q = mp.Queue()
        tel_q = mp.Queue()
        worker = GenericWorker(cfg, cmd_q, tel_q)

        fake_clock = FakeClock(step=0.2)
        fake_event = FakeEvent(auto_space=True)

        mock_psychopy = MagicMock()
        mock_psychopy.core.Clock.return_value = fake_clock
        mock_psychopy.event = fake_event

        # Inject ABORT_KEY when in kinematic wait loop
        call_count = 0

        def _custom_get_keys() -> List[str]:
            nonlocal call_count
            call_count += 1
            if call_count > 2:
                return [ABORT_KEY]
            return ["space"]

        fake_event.getKeys = _custom_get_keys  # type: ignore

        with patch.dict(sys.modules, {"psychopy": mock_psychopy, "psychopy.core": mock_psychopy.core, "psychopy.event": fake_event}):
            with patch("src.workers.stimulus_worker.CoreRenderer", return_value=MagicMock()):
                with patch("src.workers.stimulus_worker.GroundTruthLogger", return_value=MagicMock()):
                    with patch("src.workers.stimulus_worker.adaption_duration", 0.0):
                        with patch("src.workers.stimulus_worker.initial_baseline_dur", 0.0):
                            with patch.object(KinematicEngine, "evaluate_trigger", return_value=False):
                                worker.run()

        actions = []
        while not tel_q.empty():
            actions.append(tel_q.get_nowait()["action"])

        assert "worker_abort" in actions
        cmd_q.cancel_join_thread()
        tel_q.cancel_join_thread()


def test_worker_entry_function() -> None:


    """Verify worker_entry entrypoint sets signals and executes GenericWorker.run."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = _make_config(tmpdir)
        cmd_q = mp.Queue()
        tel_q = mp.Queue()

        mock_worker_instance = MagicMock()
        with patch("src.workers.stimulus_worker.GenericWorker", return_value=mock_worker_instance):
            with pytest.raises(SystemExit) as exc_info:
                worker_entry(cfg, cmd_q, tel_q)

            assert exc_info.value.code == 0
            assert mock_worker_instance.run.called

        cmd_q.cancel_join_thread()
        tel_q.cancel_join_thread()
