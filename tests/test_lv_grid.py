"""42-trial l/v grid (3 sessions per animal, 18/12/12): plan, delays, metadata, QC.

Seam: LoomingParadigm public API (generate_trials / prepare_trial / session_metadata),
GenericWorker session_config event, qc_session.check_session.
Run: python -m pytest tests/test_lv_grid.py
"""
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List

import pandas as pd
import pytest

import qc_session
from src.models.paradigm import LV_GRID_PATTERN, LV_GRID_SOAS_MS, LoomingParadigm
from tests.test_lv_supplement import _write_session
from tests.test_wind_delay_guard import _run

ANIMALS = [f"cricket_{i:03d}" for i in range(1, 13)]
LEAD_MS = {60: 3437, 120: 6875, 180: 10312}
# Delays from the NSMoR spec (round(lv / tan 1 deg) + SOA).
SPEC_DELAYS = {
    60: [3129, 3176, 3212, 3257, 3293, 3318],
    120: [6502, 6567, 6614, 6650, 6756],
    180: [9712, 9792, 9832, 9882, 10025],
}


def _animal(subject: str, **cfg: object) -> List[List[dict]]:
    para = LoomingParadigm(config={"Subject ID": subject, "Session Number": 1,
                                   "Total Sessions": 3, **cfg})
    return [para.generate_trials(LV_GRID_PATTERN) for _ in range(3)]


def _max_run(xs: List[object]) -> int:
    return LoomingParadigm._max_consecutive(list(xs))


def _delay(cmd: str) -> int:
    return int(re.fullmatch(r"<[LR],(\d+)>", cmd).group(1))


def test_one_animal_has_42_trials_with_the_specified_composition() -> None:
    for subject in ANIMALS:
        s1, s2, s3 = _animal(subject)
        assert [len(s1), len(s2), len(s3)] == [18, 12, 12]
        assert Counter(t["type"] for t in s1) == {"baseline_wind": 6, "looming_wind": 12}
        for s in (s2, s3):
            assert Counter(t["type"] for t in s) == {"baseline_visual": 2, "looming_wind": 10}

        allt = s1 + s2 + s3
        cells = Counter((t["condition"], t["screen_side"]) for t in allt if t["type"] == "looming_wind")
        assert len(cells) == 32 and set(cells.values()) == {1}  # 16 cells x (left, right)
        where: Dict[str, set] = {}
        for k, s in enumerate((s1, s2, s3)):
            for t in s:
                if t["type"] == "looming_wind":
                    where.setdefault(t["condition"], []).append(k)
        assert all(len(v) == 2 and v[0] != v[1] for v in where.values()), where

        wind = Counter((t["condition"], t["screen_side"]) for t in s1 if t["type"] == "baseline_wind")
        assert wind == {(f"W{lv}", side): 1 for lv in (60, 120, 180) for side in ("left", "right")}
        vis = Counter(t["condition"] for t in s2 + s3 if t["type"] == "baseline_visual")
        assert vis == {"V120": 2, "V60": 1, "V180": 1}
        v120 = [(k, t["screen_side"]) for k, s in ((1, s2), (2, s3)) for t in s if t["condition"] == "V120"]
        assert {side for _, side in v120} == {"left", "right"} and v120[0][0] != v120[1][0]


def test_order_and_side_balance_constraints() -> None:
    for subject in ANIMALS:
        for k, s in enumerate(_animal(subject)):
            assert _max_run([t["screen_side"] for t in s]) <= 2, (subject, k)
            assert _max_run([t["lv_ratio_ms"] for t in s]) <= 2, (subject, k)
            lr = Counter(t["screen_side"] for t in s)
            assert lr["left"] == lr["right"], (subject, k, lr)


def test_visual_60_180_sides_rotate_across_animals() -> None:
    sides = Counter()
    for subject in ANIMALS:
        for s in _animal(subject):
            for t in s:
                if t["condition"] in ("V60", "V180"):
                    sides[(t["condition"], t["screen_side"])] += 1
    assert sides == {(c, side): 6 for c in ("V60", "V180") for side in ("left", "right")}


def test_delays_match_spec() -> None:
    para = LoomingParadigm(config={"Subject ID": "cricket_001", "Total Sessions": 3})
    seen = {lv: [] for lv in SPEC_DELAYS}
    for s in _animal("cricket_001"):
        for t in s:
            cmd = para.prepare_trial(t)
            lv = t["lv_ratio_ms"]
            if t["type"] == "looming_wind":
                assert t["target_ttc_ms"] in LV_GRID_SOAS_MS[lv]
                seen[lv].append(_delay(cmd))
                assert cmd.startswith("<L," if t["wind_dir"] == "left" else "<R,")
            elif t["type"] == "baseline_wind":
                assert _delay(cmd) == LEAD_MS[lv]
            else:
                assert cmd == "" and t["wind_dir"] == "none"
    assert {lv: sorted(set(v)) for lv, v in seen.items()} == SPEC_DELAYS
    assert all(len(v) == 2 * len(SPEC_DELAYS[lv]) for lv, v in seen.items())


def test_plan_is_fixed_per_animal_and_independent_of_launch_seed() -> None:
    first = _animal("cricket_007", **{"Random Seed": 1})
    again = _animal("cricket_007", **{"Random Seed": "Auto"})
    assert first == again
    later = LoomingParadigm(config={"Subject ID": "cricket_007", "Session Number": 3,
                                    "Total Sessions": 1})
    assert later.generate_trials(LV_GRID_PATTERN) == first[2]
    assert _animal("cricket_008") != first


def test_session_metadata_has_plan_seed_and_session() -> None:
    para = LoomingParadigm(config={"Subject ID": "cricket_005", "Session Number": 2,
                                   "Total Sessions": 2})
    para.generate_trials(LV_GRID_PATTERN)
    meta = para.session_metadata()
    assert meta["grid_session"] == 2 and meta["animal_index"] == 5
    assert isinstance(meta["plan_seed"], int) and meta["pattern"] == LV_GRID_PATTERN


@pytest.mark.parametrize("cfg", [
    {"Subject ID": "cricket"},                                  # no animal number
    {"Subject ID": "cricket_20261110_100000"},                  # timestamp, not an animal number
    {"Subject ID": "cricket_001", "Total Sessions": 4},         # 4 sessions
    {"Subject ID": "cricket_001", "Total Sessions": -1},        # manual / unbounded
    {"Subject ID": "cricket_001", "Session Number": 2, "Total Sessions": 3},
])
def test_unsatisfiable_session_ranges_raise(cfg: dict) -> None:
    with pytest.raises(ValueError):
        LoomingParadigm(config=cfg).generate_trials(LV_GRID_PATTERN)


def test_missing_lv_is_an_error_not_120() -> None:
    para = LoomingParadigm(config={"Subject ID": "cricket_001", "Total Sessions": 3})
    for t in _animal("cricket_001")[0]:
        bad = {k: v for k, v in t.items() if k != "lv_ratio_ms"}
        with pytest.raises(ValueError, match="lv_ratio_ms"):
            para.prepare_trial(bad)
        if t["type"] != "baseline_wind":  # pure wind is timed by prepare_trial
            with pytest.raises(ValueError, match="lv_ratio_ms"):
                para.process_frame(0.1, bad, {})


def test_trial_start_fields_and_session_config_event() -> None:
    logger, items = _run(LV_GRID_PATTERN, **{"Subject ID": "cricket_003", "Total Sessions": 3})
    assert not [i for i in items if i.get("action") == "worker_error"], items
    events = {}
    for c in logger.log_event.call_args_list:
        events.setdefault(c.args[0], []).append(c.kwargs)
    cfgs = events["session_config"]
    assert len(cfgs) == 3
    assert [c["grid_session"] for c in cfgs] == [1, 2, 3]
    assert all(c["firmware"] == "hardware@3920573" and isinstance(c["plan_seed"], int) for c in cfgs)
    assert len(events["trial_start"]) == 42
    need = {"lv_ratio_ms", "target_ttc_ms", "condition", "screen_side", "wind_dir"}
    assert all(need <= set(t) for t in events["trial_start"])
    queued = events["wind_cmd_queued"]
    assert len(queued) == 38  # 32 looming + 6 pure wind; the 4 visual trials send nothing
    assert {e["dir"] for e in queued} == {"L", "R"}


def test_qc_expected_size_follows_grid_session_number(tmp_path: Path) -> None:
    s1, s2, _ = _animal("cricket_001")
    for sess, trials, ok in ((1, s1, True), (2, s2, True), (2, s1, False), (4, s2, False)):
        ev_p, kin_p = _write_session(tmp_path, trials)
        ev = pd.read_csv(ev_p)
        ev["session_num"] = sess
        ev.to_csv(ev_p, index=False)
        fails, _, info = qc_session.check_session(ev_p, kin_p)
        bad = [f for f in fails if f.startswith(("trial_start", "grid session", "wind onset", "unknown"))]
        assert info["pattern"] == LV_GRID_PATTERN
        assert (not bad) == ok, (sess, len(trials), fails)


def test_qc_animal_level_needs_all_three_sessions_and_each_cell_once(tmp_path: Path) -> None:
    s1, s2, s3 = _animal("cricket_007")

    def info(sess: int, trials: List[dict]) -> dict:
        ev_p, kin_p = _write_session(tmp_path, trials)
        ev = pd.read_csv(ev_p)
        ev["session_num"] = sess
        ev.to_csv(ev_p, index=False)
        return qc_session.check_session(ev_p, kin_p)[2]

    i1, i2, i3 = info(1, s1), info(2, s2), info(3, s3)
    assert not qc_session._check_grid_animal([i1, i2, i3])
    assert qc_session._check_grid_animal([i1, i2])          # session 3 missing
    assert qc_session._check_grid_animal([i1, i2, i2])      # session 2 twice, cells repeat


def test_qc_parse_name_keeps_stable_subject_id() -> None:
    a = qc_session._parse_name("cricket_007_session_1_events.csv")
    b = qc_session._parse_name("cricket_008_session_1_events.csv")
    assert a[0] == "cricket_007" and a[0] != b[0] and a[3] == "1"
