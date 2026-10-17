"""Per-animal QC gate for a raw recording folder.

Usage: python qc_session.py <folder with one animal's two sessions>

Checks per session: event completeness, trial composition, wind delivery and
timing, Arduino telemetry, all three kinematics channels, and duration.
Exit 0 = animal PASS, 1 = FAIL, 2 = usage error.
"""

from __future__ import annotations

import glob
import json
import os
import sys

import numpy as np
import pandas as pd

EXPECTED_TRIALS = 18
ONSET_TOL_MS = 60.0
PULSE_MIN_MS, PULSE_MAX_MS = 100.0, 400.0


def _details(s: pd.Series) -> pd.Series:
    return s.fillna("{}")


def check_session(ev_path: str, kin_path: str) -> tuple[list[str], list[str], dict]:
    fails: list[str] = []
    warns: list[str] = []
    info: dict = {}

    ev = pd.read_csv(ev_path, encoding="utf-8-sig")
    ev.columns = [c.strip() for c in ev.columns]
    kin = pd.read_csv(kin_path, encoding="utf-8-sig")
    kin.columns = [c.strip() for c in kin.columns]

    starts = ev[ev.event_name == "trial_start"]
    stops = ev[ev.event_name == "trial_stop"]
    verdicts = ev[ev.event_name == "trial_verdict"]
    n = len(starts)
    info["trials"] = n
    if n != EXPECTED_TRIALS:
        fails.append(f"trial_start={n} (expected {EXPECTED_TRIALS})")
    if len(stops) != n:
        fails.append(f"trial_stop={len(stops)} vs {n} trials")
    if len(verdicts) != n:
        fails.append(f"trial_verdict={len(verdicts)} vs {n} trials")
    types = starts.details.fillna("").str.extract(r'"type": "([a-z_]+)"')[0]
    ttc = starts.details.fillna("").str.extract(r'"target_ttc_ms": ([-0-9]+)')[0]
    info["types"] = types.value_counts().to_dict()
    info["ttc"] = ttc.value_counts().to_dict()
    if types.nunique() != 1:
        warns.append(f"mixed trial types: {info['types']}")

    # phase completeness per trial
    trans = ev[ev.event_name == "phase_transition"]
    for tid in starts.global_trial_id:
        d = trans[trans.global_trial_id == tid].details.fillna("")
        tos = set(d.str.extract(r'"to_phase": "([A-Za-z_0-9]+)"')[0].dropna())
        expected = {"Looming", "Collision_TTC0", "PostStimulus", "PostStimulus_End"}
        if types[starts.global_trial_id == tid].iloc[0] == "looming_wind":
            missing = expected - tos
            if missing:
                warns.append(f"trial {tid} missing phases {sorted(missing)}")

    # verdicts
    resp = verdicts.details.fillna("").str.extract(r'"response": "([a-z_]+)"')[0]
    info["responses"] = resp.value_counts().to_dict()
    if len(resp) and resp.isin(["escape", "startle"]).sum() == 0:
        fails.append("no escape/startle responses in the whole session")

    # collision + wind per trial
    coll = {}
    for _, r in trans.iterrows():
        if '"to_phase": "Collision_TTC0"' in str(r.details):
            coll[int(r.global_trial_id)] = float(r.timestamp)
    stim = kin.stim_state.to_numpy()
    vals = sorted(int(v) for v in np.unique(stim))
    if vals != [0, 1]:
        fails.append(f"stim_state values {vals} (expected [0, 1])")
    onsets, durs, missing = [], [], 0
    gid = kin.global_trial_id.to_numpy()
    sys_t = kin.sys_time.to_numpy(float)
    for _, r in starts.iterrows():
        tid = int(r.global_trial_id)
        if types[starts.global_trial_id == tid].iloc[0] != "looming_wind":
            continue
        if tid not in coll:
            warns.append(f"trial {tid} has no Collision_TTC0 event")
            continue
        mask = (gid == tid) & (stim != 0)
        if not mask.any():
            missing += 1
            continue
        idx = np.flatnonzero(mask)
        onsets.append((sys_t[idx[0]] - coll[tid]) * 1000.0)
        durs.append((sys_t[idx[-1]] - sys_t[idx[0]]) * 1000.0)
    info["wind_pulses"] = len(onsets)
    if missing:
        fails.append(f"{missing} looming trials without a wind pulse")
    if onsets:
        nominal = float(ttc.dropna().iloc[0]) if ttc.notna().any() else None
        med = float(np.median(onsets))
        info["onset_med_ms"] = med
        if nominal is not None and abs(med - nominal) > ONSET_TOL_MS:
            fails.append(f"wind onset median {med:.0f} ms vs nominal {nominal:.0f}")
        if min(durs) < PULSE_MIN_MS or max(durs) > PULSE_MAX_MS:
            fails.append(f"wind pulse duration {min(durs):.0f}-{max(durs):.0f} ms")

    # stray wind outside [trial_start, trial_stop]
    windows = []
    for _, r in starts.iterrows():
        s = ev[(ev.global_trial_id == r.global_trial_id) & (ev.event_name == "trial_stop")]
        if len(s):
            windows.append((float(r.timestamp), float(s.timestamp.iloc[0])))
    if windows:
        inside = np.zeros(len(kin), dtype=bool)
        for a, b in windows:
            inside |= (sys_t >= a) & (sys_t <= b)
        stray = int(((stim != 0) & ~inside).sum())
        info["stray_wind_rows"] = stray
        if stray > 5:
            fails.append(f"{stray} stim_state rows outside trial windows")

    # arduino telemetry
    ard = kin.ard_time.to_numpy(float)
    dt = np.diff(ard)
    info["rows"] = len(kin)
    info["ard_zero"] = int((ard == 0).sum())
    if (ard == 0).mean() > 1e-3:
        fails.append(f"ard_time zero rows {int((ard == 0).sum())} ({100*(ard==0).mean():.2f}%)")
    if not bool((np.diff(sys_t) >= 0).all()):
        fails.append("sys_time not monotonic")
    nz = ard[ard > 0]
    if len(nz) > 2:
        gap = np.diff(nz)
        if (gap > 2000).any():
            fails.append(f"{int((gap > 2000).sum())} ard_time gaps > 2 s")
        med_dt = float(np.median(gap))
        info["ard_med_dt_ms"] = med_dt
        if not 3.0 <= med_dt <= 8.0:
            fails.append(f"ard_time median dt {med_dt:.1f} ms")

    # kinematics channels
    dx, dy, dz = (kin[c].to_numpy(float) for c in ("dx", "dy", "dz"))
    x = np.column_stack([dy, dz, np.ones(len(dy))])
    coef, *_ = np.linalg.lstsq(x, dx, rcond=None)
    res = dx - x @ coef
    r2 = 1.0 - res.var() / dx.var() if dx.var() > 0 else 0.0
    info.update(dx_std=float(dx.std()), crosstalk_r2=float(r2),
                dy_std=float(dy.std()), dz_std=float(dz.std()))
    if dx.std() <= 0.005 or r2 >= 0.9:
        fails.append(f"x channel dead (dx_std={dx.std():.5f}, crosstalk R2={r2:.3f})")
    if dy.std() <= 0.003:
        fails.append(f"y channel dead (dy_std={dy.std():.5f})")
    if dz.std() <= 0.003:
        fails.append(f"rotation channel dead (dz_std={dz.std():.5f})")

    # duration
    span = float(ev[ev.event_name == "trial_stop"].timestamp.max() - ev.timestamp.min())
    info["duration_min"] = span / 60.0
    if not 15.0 <= span / 60.0 <= 45.0:
        fails.append(f"session duration {span/60:.1f} min (expected 15-45)")

    return fails, warns, info


def main(folder: str) -> int:
    evs = sorted(glob.glob(os.path.join(folder, "*_events.csv")))
    if not evs:
        print(f"no events files in {folder}")
        return 2
    if len(evs) != 2:
        print(f"warn: {len(evs)} session(s) in folder (an animal needs 2)")
    all_fails = 0
    for ev_path in evs:
        kin_path = ev_path.replace("_events.csv", "_kinematics.csv")
        name = os.path.basename(ev_path)
        if not os.path.exists(kin_path):
            print(f"{name}: FAIL missing kinematics")
            all_fails += 1
            continue
        if os.path.getsize(ev_path) == 0:
            print(f"{name}: FAIL events file is empty (session not closed normally)")
            all_fails += 1
            continue
        fails, warns, info = check_session(ev_path, kin_path)
        status = "PASS" if not fails else "FAIL"
        if fails:
            all_fails += 1
        print(f"{name}: {status}")
        print(f"  trials={info.get('trials')} wind={info.get('wind_pulses')} "
              f"onset={info.get('onset_med_ms', float('nan')):.1f} ms "
              f"dur={info.get('duration_min', 0):.1f} min "
              f"dx={info.get('dx_std', 0):.5f} R2={info.get('crosstalk_r2', 0):.3f} "
              f"responses={info.get('responses')}")
        for f in fails:
            print(f"  FAIL: {f}")
        for w in warns:
            print(f"  warn: {w}")
    print("ANIMAL:", "PASS" if all_fails == 0 else f"FAIL ({all_fails} session(s))")
    return 0 if all_fails == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
