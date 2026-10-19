"""Looming pattern labels, wind trigger delays and baseline alignment (l/v = 120 ms).

Seam: LoomingParadigm public API — get_available_patterns / generate_trials /
prepare_trial.
"""
import math
import re

from src.models.paradigm import LoomingParadigm, SingleLoomingParadigm

LV_MS = 120
T_COL_MS = round(LV_MS / math.tan(math.radians(1.0)))  # init 2° → half-angle 1°


def _delay(cmd: str) -> int:
    return int(re.fullmatch(r"<[LR],(\d+)>", cmd).group(1))


def test_label_angle_matches_lv_and_ttc() -> None:
    for key, p in LoomingParadigm.EXPERIMENT_PATTERNS.items():
        if p["type"] != "looming_wind" or p["target_ttc_ms"] >= 0:
            continue
        m = re.search(r"/ ([\d.]+)°", key)
        assert m, key
        expected = math.degrees(2 * math.atan(p["lv_ratio_ms"] / abs(p["target_ttc_ms"])))
        assert abs(float(m.group(1)) - expected) <= 0.1, key


def test_ttc_gradient_order_and_25deg_pattern() -> None:
    ttcs = [p["target_ttc_ms"] for p in LoomingParadigm.EXPERIMENT_PATTERNS.values()
            if p["type"] == "looming_wind"]
    assert ttcs == [-541, -373, -308, -261, -225, -119, 0, 200]
    assert "Looming + Wind (TTC -541ms / 25°)" in LoomingParadigm.get_available_patterns()


def test_25deg_trials_and_delay() -> None:
    para = LoomingParadigm(config={"Number of Repetitions": 3, "Random Seed": "1"})
    trials = para.generate_trials("Looming + Wind (TTC -541ms / 25°)")
    assert sorted(t["wind_dir"] for t in trials) == ["left"] * 3 + ["right"] * 3
    for t in trials:
        assert abs(_delay(para.prepare_trial(t)) - (T_COL_MS - 541)) <= 1


def test_existing_delays_unchanged() -> None:
    para = LoomingParadigm()
    for key, p in LoomingParadigm.EXPERIMENT_PATTERNS.items():
        if p["type"] != "looming_wind":
            continue
        t = para.generate_trials(key)[0]
        assert _delay(para.prepare_trial(t)) == max(0, T_COL_MS + p["target_ttc_ms"])


def test_baseline_wind_aligned_to_looming_lead_time() -> None:
    para = LoomingParadigm()
    t = para.generate_trials("Baseline Wind")[0]
    assert _delay(para.prepare_trial(t)) == T_COL_MS


def test_single_looming_untouched() -> None:
    assert "Looming + Wind (TTC -373ms / 30°)" in SingleLoomingParadigm.EXPERIMENT_PATTERNS
    assert all(p["lv_ratio_ms"] in (100, None)
               for p in SingleLoomingParadigm.EXPERIMENT_PATTERNS.values())


def test_baseline_wind_onset_equals_ttc0_trigger_in_both_paradigms() -> None:
    for cls in (LoomingParadigm, SingleLoomingParadigm):
        para = cls()
        ttc0 = next(k for k, p in cls.EXPERIMENT_PATTERNS.items()
                    if p["type"] == "looming_wind" and p["target_ttc_ms"] == 0)
        bw = para.prepare_trial(para.generate_trials("Baseline Wind")[0])
        col = para.prepare_trial(para.generate_trials(ttc0)[0])
        assert _delay(bw) == _delay(col), cls.__name__
