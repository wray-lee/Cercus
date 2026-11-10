"""Firmware delay guard: preflight refusal and per-trial wind command log.

Seam: GenericWorker.run / _preflight_wind_delays (public behaviour: worker_error
telemetry, logger events).
"""
import multiprocessing as mp
import random
import re
import sys
import tempfile
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from src.workers.stimulus_worker import FIRMWARE_MAX_DELAY_MS, GenericWorker
from tests.test_stimulus_worker import FakeClock, FakeEvent, _make_config

FULL = "LV Supplement: Full (21 cond x L/R, 2 sessions)"
WIND = "Looming + Wind (TTC -373ms / 35.7°)"


def _run(pattern: str, limit: int = FIRMWARE_MAX_DELAY_MS) -> tuple:
    """Run a full mock session; return (mock_logger, telemetry actions/errors)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = _make_config(tmpdir, **{"Execution Mode": "Auto", "Experiment Pattern": pattern})
        cmd_q, tel_q = mp.Queue(), mp.Queue()
        worker = GenericWorker(cfg, cmd_q, tel_q)
        psy = MagicMock()
        psy.core.Clock.return_value = FakeClock(step=0.2)
        psy.event = FakeEvent(auto_space=True)
        logger = MagicMock()
        mods = {"psychopy": psy, "psychopy.core": psy.core, "psychopy.event": psy.event}
        with patch.dict(sys.modules, mods), \
                patch("src.workers.stimulus_worker.CoreRenderer", return_value=MagicMock()), \
                patch("src.workers.stimulus_worker.GroundTruthLogger", return_value=logger), \
                patch("src.workers.stimulus_worker.FIRMWARE_MAX_DELAY_MS", limit), \
                patch("src.workers.stimulus_worker.adaption_duration", 0.02), \
                patch("src.workers.stimulus_worker.initial_baseline_dur", 0.02):
            worker.run()
        items: List[Dict[str, Any]] = []
        while not tel_q.empty():
            items.append(tel_q.get_nowait())
        cmd_q.cancel_join_thread()
        tel_q.cancel_join_thread()
    return logger, items


def test_over_limit_session_is_refused_before_opening() -> None:
    logger, items = _run(FULL, limit=10000)  # the old firmware limit
    errors = [i["error"] for i in items if i.get("action") == "worker_error"]
    assert len(errors) == 1
    assert "Preflight failed" in errors[0] and "MAX_DELAY_MS=10000" in errors[0]
    assert re.search(r"\(B\d\): 13\d{3} ms", errors[0])  # 240 arm, over the old limit
    logger.open_session.assert_not_called()
    assert not [i for i in items if i.get("action") == "worker_done"]


def test_preflight_leaves_rng_state_untouched() -> None:
    from src.models.paradigm import LoomingParadigm

    worker = GenericWorker(_make_config("."), mp.Queue(), mp.Queue())
    worker.paradigm = LoomingParadigm(config={"Random Seed": "5", "Subject ID": "s"})
    trials = worker.paradigm.generate_trials(FULL)
    random.seed(9)
    before = random.getstate()
    worker._preflight_wind_delays(trials)
    assert random.getstate() == before
    with patch("src.workers.stimulus_worker.FIRMWARE_MAX_DELAY_MS", 13000):
        with pytest.raises(ValueError, match="MAX_DELAY_MS=13000"):
            worker._preflight_wind_delays(trials)
    assert random.getstate() == before


def test_each_wind_command_is_logged_with_its_delay() -> None:
    logger, items = _run(WIND)
    assert not [i for i in items if i.get("action") == "worker_error"], items
    sent = [c for c in logger.log_event.call_args_list if c.args[0] == "wind_cmd_queued"]
    assert len(sent) == 2  # 1 repetition x (left, right)
    for c in sent:
        kw = c.kwargs
        assert kw["dir"] in ("L", "R") and kw["cmd"] == f"<{kw['dir']},{kw['delay_ms']}>"
        assert abs(kw["delay_ms"] - (6875 - 373)) <= 1
        assert isinstance(c.args[1], float)
