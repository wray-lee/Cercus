"""Per-animal QC gate for a raw recording folder.

Usage: python qc_session.py <folder with one animal's two sessions>

Checks per session: event completeness, trial composition, wind delivery and
timing, Arduino telemetry, all three kinematics channels, and duration.
Exit 0 = animal PASS, 1 = FAIL, 2 = usage error.
"""

from __future__ import annotations

import glob
import os
import re
import sys

import numpy as np
import pandas as pd

EXPECTED_TRIALS = 18
ONSET_TOL_MS = 60.0
PULSE_MIN_MS, PULSE_MAX_MS = 100.0, 400.0

if os.name == "nt":
    os.system("")  # enable ANSI VT processing on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_COLOR = sys.stdout.isatty()
GREEN, RED, YELLOW, BOLD, DIM = "32", "31", "33", "1", "2"
SEP = "─" * 72


def paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


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
    if len(verdicts) == 0:
        warns.append("no trial_verdict events (pre-verdict acquisition format)")
    elif len(verdicts) != n:
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
    if (len(resp) and types.eq("looming_wind").any()
            and resp.isin(["escape", "startle"]).sum() == 0):
        warns.append("no escape/startle responses in a looming_wind session")

    # collision + wind per trial
    coll = {}
    for _, r in trans.iterrows():
        if '"to_phase": "Collision_TTC0"' in str(r.details):
            coll[int(r.global_trial_id)] = float(r.timestamp)
    stim = kin.stim_state.to_numpy()
    vals = sorted(int(v) for v in np.unique(stim))
    wind_session = types.isin(["looming_wind", "baseline_wind"]).any()
    if wind_session and vals != [0, 1]:
        warns.append(f"stim_state glitch values {vals} (expected [0, 1])")
    if not wind_session and vals != [0]:
        warns.append(f"visual-only session has stim_state values {vals}")
    onsets, durs, durs_detail, missing = [], [], [], 0
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
        d = (sys_t[idx[-1]] - sys_t[idx[0]]) * 1000.0
        durs.append(d)
        durs_detail.append((tid, d))
    info["wind_pulses"] = len(onsets)
    if missing:
        fails.append(f"{missing} looming trials without a wind pulse")
    if onsets:
        nominal = float(ttc.dropna().iloc[0]) if ttc.notna().any() else None
        med = float(np.median(onsets))
        info["onset_med_ms"] = med
        info["nominal_ms"] = nominal
        if nominal is not None and abs(med - nominal) > ONSET_TOL_MS:
            fails.append(f"wind onset median {med:.0f} ms vs nominal {nominal:.0f}")
        odd = [(t, d) for t, d in durs_detail
               if d < PULSE_MIN_MS or d > PULSE_MAX_MS]
        if odd:
            detail = ", ".join(f"trial {t}: {d:.0f} ms" for t, d in odd[:3])
            warns.append(f"odd wind pulse duration ({detail})")

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

    # telemetry continuity: sys_time is the recorded clock.  ard_time jumps
    # with continuous sys_time are Arduino clock re-syncs, not data loss.
    ard = kin.ard_time.to_numpy(float)
    info["rows"] = len(kin)
    info["ard_zero"] = int((ard == 0).sum())
    if (ard == 0).mean() > 1e-3:
        fails.append(f"ard_time zero rows {int((ard == 0).sum())} ({100*(ard==0).mean():.2f}%)")
    ds = np.diff(sys_t)
    if not bool((ds >= 0).all()):
        fails.append("sys_time not monotonic")
    info["host_read_stalls"] = 0
    for i in np.flatnonzero(ds > 0.1):
        # sys_time is stamped per serial read, so a host-side read stall shows
        # as a sys gap while ard_time stays continuous (backlog stamped at
        # once).  Only a matching ard_time gap means samples were lost.
        d_ard = ard[i + 1] - ard[i]
        if ard[i] > 0 and 0 <= d_ard <= 20:
            info["host_read_stalls"] += 1
            continue
        t0 = float(sys_t[i])
        msg = f"telemetry gap {ds[i]:.1f} s at {t0:.1f} s"
        warns.append(msg + (" (inside trial)" if any(a <= t0 <= b for a, b in windows) else " (ITI)"))
    nz = ard[ard > 0]
    if len(nz) > 2:
        med_dt = float(np.median(np.diff(nz)))
        info["ard_med_dt_ms"] = med_dt
        if not 3.0 <= med_dt <= 8.0:
            fails.append(f"ard_time median dt {med_dt:.1f} ms")

    # kinematics channels.  The dead-x signature is EXACT: raw dx == 0, so
    # the recorded dx is bit-for-bit the calibration cross-talk of dy/dz.
    # Test the exactness of the linear relation, not R2 (outlier spikes can
    # fake a high R2 in a healthy session).
    dx, dy, dz = (kin[c].to_numpy(float) for c in ("dx", "dy", "dz"))
    x = np.column_stack([dy, dz, np.ones(len(dy))])
    coef, *_ = np.linalg.lstsq(x, dx, rcond=None)
    res = dx - x @ coef
    scale = max(float(np.abs(dx).max()), 1.0)
    exact = float(np.abs(res).max()) <= 1e-9 * scale
    info.update(dx_std=float(dx.std()), crosstalk_exact=bool(exact),
                dy_std=float(dy.std()), dz_std=float(dz.std()))
    x_dead = exact and (dy.std() > 0.003 or dz.std() > 0.003)
    info["x_dead"] = bool(x_dead)
    if x_dead:
        fails.append("x channel dead (raw dx == 0; recorded dx is only "
                     "calibration cross-talk)")
    if dy.std() <= 0.003:
        fails.append(f"y channel dead (dy_std={dy.std():.5f})")
    if dz.std() <= 0.003:
        fails.append(f"rotation channel dead (dz_std={dz.std():.5f})")

    # duration
    span = float(ev[ev.event_name == "trial_stop"].timestamp.max() - ev.timestamp.min())
    info["duration_min"] = span / 60.0
    if span / 60.0 < 15.0:
        fails.append(f"session duration {span/60:.1f} min (too short, aborted?)")
    elif span / 60.0 > 45.0:
        warns.append(f"long session {span/60:.1f} min (pause?)")

    return fails, warns, info


TTC_LABEL = {
    -373: "30° (-373 ms)", -308: "36° (-308 ms)",
    -261: "42° (-261 ms)", -225: "48° (-225 ms)",
    -119: "80° (-119 ms)", 0: "180° (0 ms)", 200: "+200 ms",
}


def _parse_name(name: str) -> tuple[str, str, str, str]:
    m = re.match(r"(.*?)cricket(?:_001)?_(\d{8})_(\d{6})_session_(\d)", name)
    if not m:
        return "?", "?", "?", "?"
    d = m.group(2)
    return (m.group(1) or "?", f"{d[:4]}-{d[4:6]}-{d[6:]}",
            m.group(3), m.group(4))


def _paradigm(info: dict) -> str:
    types = info.get("types") or {}
    if "baseline_visual" in types:
        return "visual only (bv)"
    if "baseline_wind" in types:
        return "wind only (bw)"
    for k in (info.get("ttc") or {}):
        try:
            n = int(k)
        except (TypeError, ValueError):
            continue
        return TTC_LABEL.get(n, f"ttc {n} ms")
    return "?"


def _responses(info: dict) -> str:
    r = info.get("responses") or {}
    return ", ".join(f"{k} {v}" for k, v in sorted(r.items())) if r else "no verdicts"


def _session_line(sess: str, fails: list[str], info: dict) -> str:
    ok = not fails
    dead = bool(info.get("x_dead"))
    onset, nom = info.get("onset_med_ms"), info.get("nominal_ms")
    if onset is not None and nom is not None:
        onset_s = f"onset {onset:+.0f} ms (nom {nom:+.0f})"
    elif onset is not None:
        onset_s = f"onset {onset:+.0f} ms"
    else:
        onset_s = "onset n/a"
    n = int(info.get("trials", 0))
    wind = int(info.get("wind_pulses", 0))
    dur = float(info.get("duration_min", 0.0))
    status = "✅" if ok else "❌"
    dx = "dx DEAD" if dead else "dx OK"
    line = (f"  {status}  session {sess}   {n:2d}/18 trials   "
            f"{wind:2d}/{n} wind   {onset_s:24s} {dur:5.1f} min   "
            f"{dx:8s} {_responses(info)}")
    line = line.replace(status, paint(status, GREEN if ok else RED), 1)
    if dead:
        line = line.replace(dx, paint(dx, RED), 1)
    return line


def main(folder: str) -> int:
    evs = sorted(glob.glob(os.path.join(folder, "*_events.csv")))
    if not evs:
        print(f"no events files in {folder}")
        return 2

    groups: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
    for ev_path in evs:
        name = os.path.basename(ev_path)
        animal, date, time, sess = _parse_name(name)
        groups.setdefault((animal, date, time), []).append((sess, ev_path))

    n_pass = 0
    for (animal, date, _time), items in sorted(groups.items()):
        results = []
        for sess, ev_path in sorted(items):
            kin_path = ev_path.replace("_events.csv", "_kinematics.csv")
            if not os.path.exists(kin_path):
                results.append((sess, ["missing kinematics file"], [], {}))
            elif os.path.getsize(ev_path) == 0:
                results.append((sess, ["events file is empty (session not "
                                       "closed normally)"], [], {}))
            else:
                results.append((sess, *check_session(ev_path, kin_path)))
        paradigm = _paradigm(results[0][3]) if results else "?"
        print()
        print(paint(f"🦗  {animal}   ·   {paradigm}   ·   {date}", BOLD))
        print(paint(SEP, DIM))
        animal_fail = False
        if len(results) != 2:
            print("      " + paint(
                f"⚠️   {len(results)} session(s) found (an animal needs 2)",
                YELLOW))
        for sess, fails, warns, info in results:
            if fails:
                animal_fail = True
            print(_session_line(sess, fails, info))
            for f in fails:
                print("      " + paint(f"❌   {f}", RED))
            for w in warns:
                print("      " + paint(f"⚠️   {w}", YELLOW))
        print(paint(SEP, DIM))
        if animal_fail:
            print("  " + paint("🏁  RESULT  FAIL", "1;31"))
        else:
            n_pass += 1
            print("  " + paint("🏁  RESULT  PASS", "1;32"))
    print()
    total = len(groups)
    print(paint(f"📊  SUMMARY   {n_pass}/{total} animals PASS",
                "1;32" if n_pass == total else "1;31"))
    return 0 if n_pass == total else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
