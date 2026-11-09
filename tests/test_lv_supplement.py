"""LV supplement mixed patterns: variable l/v, frozen loom, contralateral wind.

Seam: LoomingParadigm public API — generate_trials / prepare_trial / process_frame.
"""
import json
import math
import re
from collections import Counter
from pathlib import Path

import pandas as pd

import qc_session
from src.models.paradigm import LoomingParadigm

CORE = "LV Supplement: Core (16 cond x L/R, 2 sessions)"
FULL = "LV Supplement: Full (21 cond x L/R, 2 sessions)"
COHORT = "LV Supplement: Freeze + Contra Cohort (12 trials)"


def _t_col_ms(lv: int) -> int:
    return round(lv / math.tan(math.radians(1.0)))


def _delay(cmd: str) -> int:
    return int(re.fullmatch(r"<[LR],(\d+)>", cmd).group(1))


def _max_run(xs) -> int:
    return LoomingParadigm._max_consecutive(list(xs))


def _block(pattern: str, subject: str = "cricket_07"):
    para = LoomingParadigm(config={"Subject ID": subject, "Session Number": 1})
    return para, [para.generate_trials(pattern) for _ in range(2)]


def test_two_session_blocks_cover_each_condition_both_sides() -> None:
    for pattern, n in ((CORE, 16), (FULL, 21)):
        _, (s1, s2) = _block(pattern)
        for s in (s1, s2):
            assert len(s) == n and len({t["condition"] for t in s}) == n
            assert _max_run(t["screen_side"] for t in s) <= 2
            assert _max_run(t["lv_ratio_ms"] for t in s) <= 2
            sides = Counter(t["screen_side"] for t in s)
            assert abs(sides["left"] - sides["right"]) <= 1
        pairs = Counter((t["condition"], t["screen_side"]) for t in s1 + s2)
        assert len(pairs) == 2 * n and set(pairs.values()) == {1}


def test_session_two_in_later_launch_gets_complement() -> None:
    _, (s1, s2) = _block(CORE)
    # Different launch, re-rolled seed: the plan must not depend on it.
    later = LoomingParadigm(config={"Subject ID": "cricket_07", "Random Seed": "Auto",
                                    "Session Number": 2})
    assert later.generate_trials(CORE) == s2
    assert _block(CORE, "cricket_08")[1][0] != s1
    # Sessions 3/4 are a fresh block, not a replay of 1/2.
    para, _ = _block(CORE)
    assert para.generate_trials(CORE) != s1


def test_cohort_single_session_both_sides() -> None:
    para = LoomingParadigm(config={"Random Seed": "3"})
    s = para.generate_trials(COHORT)
    assert len(s) == 12
    assert Counter(t["condition"] for t in s) == {c: 2 for c in ("F1", "F2", "FV", "C1", "C2", "W120")}


def test_wind_commands_and_directions() -> None:
    para, (s1, s2) = _block(FULL)
    by = {(t["condition"], t["screen_side"]): t for t in s1 + s2}
    assert _delay(para.prepare_trial(by["B3", "left"])) == _t_col_ms(240) - 373
    assert _delay(para.prepare_trial(by["A6", "left"])) == _t_col_ms(120) - 119
    assert _delay(para.prepare_trial(by["W240", "left"])) == _t_col_ms(240)
    assert _delay(para.prepare_trial(by["W120", "left"])) == _t_col_ms(120)
    assert _delay(para.prepare_trial(by["F1", "left"])) == _t_col_ms(120) - 228
    assert para.prepare_trial(by["V240", "left"]) == ""
    assert para.prepare_trial(by["FV", "left"]) == ""
    assert para.prepare_trial(by["C1", "left"]).startswith("<R,")
    assert para.prepare_trial(by["C2", "right"]).startswith("<L,")
    assert para.prepare_trial(by["A1", "right"]).startswith("<R,")


def test_frozen_loom_holds_angle_until_end() -> None:
    para, (s1, s2) = _block(FULL)
    t = next(t for t in s1 + s2 if t["condition"] == "F2")
    para.prepare_trial(t)
    t_col = _t_col_ms(120) / 1000.0
    _, _, tel = para.process_frame(t_col - 0.400, t, {})
    assert tel["phase"] == "Looming" and tel["ui_metrics"]["theta"] < 42.0
    for dt, phase in ((-0.300, "Frozen"), (-0.118, "Frozen"),
                      (0.0, "Collision_TTC0"), (0.900, "Collision_TTC0")):
        _, _, tel = para.process_frame(t_col + dt, t, {})
        assert tel["phase"] == phase and tel["ui_metrics"]["theta"] == 42.6, dt
    _, _, tel = para.process_frame(t_col + 1.05, t, {})
    assert tel["phase"] == "PostStimulus"


def _write_session(tmp_path: Path, trials: list) -> tuple:
    """Synthetic clean recording: each trial's wind lands exactly on its SOA."""
    ev, kin, t = [], [], 0.0
    for gid, tr in enumerate(trials, 1):
        coll = t + 7.0
        ev.append(("trial_start", t, gid, json.dumps(tr)))
        ev.append(("phase_transition", coll, gid, json.dumps({"to_phase": "Collision_TTC0"})))
        ev.append(("trial_stop", t + 10.0, gid, ""))
        ev.append(("trial_verdict", t + 10.0, gid, json.dumps({"response": "escape"})))
        on = coll + (tr["target_ttc_ms"] or 0) / 1000.0
        for i in range(int(10.0 / 0.005)):
            ts = t + i * 0.005
            wind = tr["wind_dir"] != "none" and on <= ts < on + 0.2
            kin.append((ts, ts * 1000 + 1, gid, int(wind), 0.0, 0.0, 0.0))
        t += 80.0
    ev_p, kin_p = tmp_path / "ev.csv", tmp_path / "kin.csv"
    pd.DataFrame(ev, columns=["event_name", "timestamp", "global_trial_id", "details"]).to_csv(ev_p, index=False)
    pd.DataFrame(kin, columns=["sys_time", "ard_time", "global_trial_id", "stim_state",
                               "dx", "dy", "dz"]).to_csv(kin_p, index=False)
    return str(ev_p), str(kin_p)


def test_qc_accepts_mixed_session_and_catches_bad_onset(tmp_path: Path) -> None:
    _, (s1, _) = _block(CORE)
    fails, _, info = qc_session.check_session(*_write_session(tmp_path, s1))
    assert info["pattern"] == CORE and info["expected_trials"] == 16
    assert not [f for f in fails if f.startswith(("trial_start", "wind onset", "unknown"))], fails

    late = [dict(t, target_ttc_ms=t["target_ttc_ms"] - 100) if t["type"] == "looming_wind" else t
            for t in s1]
    ev_p, kin_p = _write_session(tmp_path, late)
    # Log the true SOAs but deliver every wind 100 ms early → onset check must fail.
    ev = pd.read_csv(ev_p)
    ev.loc[ev.event_name == "trial_start", "details"] = [json.dumps(t) for t in s1]
    ev.to_csv(ev_p, index=False)
    fails, _, _ = qc_session.check_session(ev_p, kin_p)
    assert any(f.startswith("wind onset") for f in fails), fails
