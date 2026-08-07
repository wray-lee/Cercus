#!/usr/bin/env python3
"""Calibrate the stimulus-angle offset of a ring-airflow cricket escape apparatus.

Per group (default: one date-folder = one cricket) it estimates a constant
angular offset delta between the nominal stimulus angle and its true direction,
then writes corrected copies of every events/kinematics pair under --output,
mirroring the input folder structure. Also writes calibration_report.json/.png.

The per-group regression (response ~ nominal) is a diagnostic only: its implied
delta (intercept+1)/slope equals delta_est only when the data follows the
regression prior (slope ~ 0.9, intercept ~ -1). It is not a pass/fail gate.
"""
import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile

import numpy as np
import pandas as pd

# ══════════════════════════════════════════════════════════════════════════
# angle helpers
# ══════════════════════════════════════════════════════════════════════════

def wrap180(a):
    return ((np.asarray(a, dtype=float) + 180.0) % 360.0) - 180.0


def circ_mean(deg):
    d = np.asarray(deg, dtype=float)
    d = d[np.isfinite(d)]
    if d.size == 0:
        return float("nan")
    return float(np.degrees(np.angle(np.mean(np.exp(1j * np.radians(d))))))


def delta_from_trials(trials, expected_error):
    if len(trials) < 2:
        return float("nan")
    err = wrap180([t["response"] - (t["nominal"] + 180.0) for t in trials])
    return circ_mean(err) + expected_error


def _gid(v):
    """global_trial_id key: collapse integral floats (1.0 -> '1') but never
    rewrite literal strings, so a string id '1.0' stays distinct from '1'."""
    if isinstance(v, float) and not math.isnan(v) and v.is_integer():
        return str(int(v))
    return str(v)

# ══════════════════════════════════════════════════════════════════════════
# scanning & nominal-angle resolution
# ══════════════════════════════════════════════════════════════════════════

SESSION_RE = re.compile(r"(.+?)_session_(\d+)_(events|kinematics)\.csv$")
ANGLE_KEYS = ("stim_angle", "wind_angle", "wind_direction",
              "stim_azimuth", "wind_azimuth", "angle")


def _side_of(det):
    for k in ("wind_dir", "screen_side"):
        v = det.get(k)
        if v is not None and str(v).strip().lower() in ("left", "right"):
            return str(v).strip().lower()
    return None


def nominal_angle(det, left_angle, right_angle):
    """(nominal_deg|nan, side|None). Prefer an explicit numeric angle key."""
    for k in ANGLE_KEYS:
        if k in det:
            v = str(det[k]).strip()
            if v.lower() in ("left", "right"):
                return (left_angle, "left") if v.lower() == "left" else (right_angle, "right")
            try:
                return float(v), None
            except ValueError:
                pass
    side = _side_of(det)
    if side is None:
        return float("nan"), None
    return (left_angle, "left") if side == "left" else (right_angle, "right")


def _sesskey(ev_path):
    m = SESSION_RE.match(os.path.basename(ev_path))
    return (m.group(1), int(m.group(2)))


def _pair_sessions(fdir):
    evs = {}
    for f in os.listdir(fdir):
        m = SESSION_RE.match(f)
        if m and m.group(3) == "events":
            evs[(m.group(1), int(m.group(2)))] = os.path.join(fdir, f)
    pairs = []
    for f in os.listdir(fdir):
        m = SESSION_RE.match(f)
        if m and m.group(3) == "kinematics":
            k = (m.group(1), int(m.group(2)))
            if k in evs:
                pairs.append((evs[k], os.path.join(fdir, f)))
    pairs.sort(key=lambda p: _sesskey(p[0]))
    return pairs


def scan(input_dir, group_by):
    """-> {group_key: [(events,kin)]}, {folder: group_key}, {folder: [(events,kin)]}"""
    groups, folder_groups, folder_sessions = {}, {}, {}
    for folder in sorted(os.listdir(input_dir)):
        fdir = os.path.join(input_dir, folder)
        if not os.path.isdir(fdir):
            continue
        pairs = _pair_sessions(fdir)
        if not pairs:
            continue
        folder_sessions[folder] = pairs
        key = (SESSION_RE.match(os.path.basename(pairs[0][0])).group(1)
               if group_by == "subject" else folder)
        folder_groups[folder] = key
        groups.setdefault(key, []).extend(pairs)
    return groups, folder_groups, folder_sessions

# ══════════════════════════════════════════════════════════════════════════
# per-trial loading, estimation, stats
# ══════════════════════════════════════════════════════════════════════════

_NO_SIDE_WARNED = {"count": 0, "printed": False}


def _response_angle(det, row, has_angle_col):
    """Numeric response angle from details JSON key or a top-level events column."""
    v = det.get("response_angle")
    if v is not None:
        try:
            fv = float(v)
        except (TypeError, ValueError):
            pass
        else:
            return fv if not math.isnan(fv) else None
    if has_angle_col:
        v = getattr(row, "response_angle", None)
        if v is not None and not (isinstance(v, float) and math.isnan(v)):
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None


def load_trials(ev_path, kin_path, left_angle, right_angle, min_disp):
    """Valid trials: response angle over stim_state==1 frames, or the trial's
    pre-existing response_angle when present (details key or events column)."""
    ev = pd.read_csv(ev_path, encoding="utf-8-sig")
    kin = pd.read_csv(kin_path, encoding="utf-8-sig")
    kin = kin[kin["stim_state"] == 1]
    kin["gid"] = kin["global_trial_id"].map(_gid)
    has_angle_col = "response_angle" in ev.columns
    trials = []
    for row in ev.itertuples(index=False):
        if row.event_name != "trial_start":
            continue
        try:
            det = json.loads(row.details)
        except Exception:
            continue
        if not isinstance(det, dict):
            continue
        nominal, side = nominal_angle(det, left_angle, right_angle)
        if math.isnan(nominal):
            _NO_SIDE_WARNED["count"] += 1
            if not _NO_SIDE_WARNED["printed"]:
                _NO_SIDE_WARNED["printed"] = True
                print(f"warning: trial_start with no numeric angle key and "
                      f"unrecognized wind_dir/screen_side skipped (nominal NaN); "
                      f"first at {os.path.basename(ev_path)} "
                      f"gid={_gid(row.global_trial_id)}", file=sys.stderr)
            continue
        resp = _response_angle(det, row, has_angle_col)
        if resp is None:
            fr = kin[kin["gid"] == _gid(row.global_trial_id)]
            if fr.empty:
                continue
            dxs, dys = float(fr["dx"].sum()), float(fr["dy"].sum())
            if math.isnan(dxs) or math.isnan(dys):   # NaN sums -> meaningless angle
                continue
            if math.hypot(dxs, dys) < min_disp:      # near-zero vector -> meaningless angle
                continue
            resp = math.degrees(math.atan2(dys, dxs))
        if side is None:
            side = ("left" if abs(wrap180(nominal - left_angle)) <
                    abs(wrap180(nominal - right_angle)) else "right")
        trials.append({"nominal": nominal, "response": resp, "side": side})
    return trials


def group_stats(trials, expected_error):
    st = {"n_trials": len(trials)}
    if len(trials) >= 2:
        err = wrap180([t["response"] - (t["nominal"] + 180.0) for t in trials])
        st["circ_mean_error_deg"] = circ_mean(err)
        st["delta_est_deg"] = st["circ_mean_error_deg"] + expected_error
        x = np.array([t["nominal"] for t in trials])
        y = np.array([t["response"] for t in trials])
        if len(np.unique(x)) >= 2:
            slope, intercept = np.polyfit(x, y, 1)
            st["slope"], st["intercept"] = float(slope), float(intercept)
            st["r"] = float(np.corrcoef(x, y)[0, 1])
        else:
            st["slope"] = st["intercept"] = st["r"] = float("nan")
        if not math.isnan(st["slope"]) and st["slope"] != 0.0:
            st["regression_implied_delta_deg"] = (st["intercept"] + 1.0) / st["slope"]
        else:
            st["regression_implied_delta_deg"] = float("nan")
    else:
        for k in ("circ_mean_error_deg", "delta_est_deg", "slope",
                  "intercept", "r", "regression_implied_delta_deg"):
            st[k] = float("nan")
    return st


def side_stats(trials, delta):
    out = {}
    for side in ("left", "right"):
        st = [t for t in trials if t["side"] == side]
        if not st:
            continue
        eb = wrap180([t["response"] - (t["nominal"] + 180.0) for t in st])
        mb = circ_mean(eb)
        ea = wrap180(eb - delta) if not math.isnan(delta) else eb
        ma = circ_mean(ea)
        out[side] = {"n": len(st),
                     "mean_error_before_deg": mb,
                     "mean_error_after_deg": ma,
                     "within_5deg_before": abs(mb + 18.0) <= 5.0,
                     "within_5deg_after": abs(ma + 18.0) <= 5.0}
    return out


def loo_delta_std(group_trials, expected_error):
    """Leave-one-cricket-out delta estimates -> std (the uncertainty)."""
    vals = []
    for i in range(len(group_trials)):
        # ponytail: O(g^2) pooling, fine for a handful of groups
        pooled = [t for j in range(len(group_trials))
                  if j != i for t in group_trials[j]]
        d = delta_from_trials(pooled, expected_error)
        if not math.isnan(d):
            vals.append(d)
    return float(np.std(vals)) if len(vals) >= 2 else float("nan")

# ══════════════════════════════════════════════════════════════════════════
# correction writer
# ══════════════════════════════════════════════════════════════════════════

def write_corrected(input_dir, output_dir, folder_sessions, folder_groups,
                    group_deltas, left_angle, right_angle):
    for folder, sess in folder_sessions.items():
        delta = group_deltas.get(folder_groups[folder], float("nan"))
        for ev_path, kin_path in sess:
            ev = pd.read_csv(ev_path, encoding="utf-8-sig")
            kin = pd.read_csv(kin_path, encoding="utf-8-sig")
            corr_by_gid = {}
            for idx, row in ev.iterrows():
                if row["event_name"] != "trial_start":
                    continue
                try:
                    det = json.loads(row["details"])
                except Exception:
                    continue
                nominal, _ = nominal_angle(det, left_angle, right_angle)
                corr = (nominal + delta
                        if not (math.isnan(nominal) or math.isnan(delta)) else float("nan"))
                corr_by_gid[_gid(row["global_trial_id"])] = corr
                det = dict(det)
                det["stim_angle"] = None if math.isnan(nominal) else nominal
                det["stim_angle_corrected"] = None if math.isnan(corr) else corr
                ev.at[idx, "details"] = json.dumps(det)
            out_dir = os.path.join(output_dir, folder)
            os.makedirs(out_dir, exist_ok=True)
            ev.to_csv(os.path.join(out_dir, os.path.basename(ev_path)),
                      index=False, encoding="utf-8-sig")
            kin["stim_angle_corrected"] = (kin["global_trial_id"].map(_gid)
                                           .map(corr_by_gid))
            kin.to_csv(os.path.join(out_dir, os.path.basename(kin_path)),
                       index=False, encoding="utf-8-sig")

# ══════════════════════════════════════════════════════════════════════════
# report & plot
# ══════════════════════════════════════════════════════════════════════════

def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    if isinstance(o, float) and not math.isfinite(o):
        return None
    return o


def _safe_savefig(fig, path):
    try:
        fig.savefig(path)
    except OSError:   # Windows OSError 22 dodge (unlink-then-save)
        if os.path.exists(path):
            os.unlink(path)
        fig.savefig(path)
    import matplotlib.pyplot as plt
    plt.close(fig)


def make_plot(all_valid, group_deltas, out_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    before, after = [], []
    for gkey, t in all_valid:
        e = float(wrap180(t["response"] - (t["nominal"] + 180.0)))
        before.append(e)
        d = group_deltas[gkey]
        after.append(float(wrap180(e - d)) if not math.isnan(d) else np.nan)
    before = np.asarray(before)
    after = np.asarray(after)
    before = before[np.isfinite(before)]
    after = after[np.isfinite(after)]

    fig = plt.figure(figsize=(11, 5))
    ax1 = fig.add_subplot(1, 2, 1, projection="polar")
    ax2 = fig.add_subplot(1, 2, 2)
    cb = np.zeros(0)
    ca = np.zeros(0)
    if before.size:
        cb = ax1.hist(np.mod(np.radians(before), 2 * np.pi), bins=36,
                      range=(0, 2 * np.pi), alpha=0.5,
                      color="tab:red", label="before")[0]
    if after.size:
        ca = ax1.hist(np.mod(np.radians(after), 2 * np.pi), bins=36,
                      range=(0, 2 * np.pi), alpha=0.5,
                      color="tab:blue", label="after")[0]
    rmax = max(1.0, float(cb.max()) if cb.size else 0.0,
               float(ca.max()) if ca.size else 0.0)
    ax1.set_rmax(rmax * 1.15)
    for th in (0.0, math.radians(-18.0) % (2 * np.pi)):
        ax1.plot([th, th], [0.0, rmax], "k--", lw=1)
    ax1.set_title("error rose (before vs after)")
    ax1.legend(fontsize=8, loc="upper right")

    ax2.hist(before, bins=36, range=(-180, 180), alpha=0.5,
             color="tab:red", label="before")
    ax2.hist(after, bins=36, range=(-180, 180), alpha=0.5,
             color="tab:blue", label="after")
    ax2.axvspan(-23.0, -13.0, color="gray", alpha=0.25)   # -18 ± 5 band
    ax2.axvline(-18.0, color="k", ls="--", lw=1)
    ax2.set_xlabel("error (deg)")
    ax2.set_ylabel("count")
    ax2.set_title("error histogram (-18±5 band)")
    ax2.legend(fontsize=8)
    fig.tight_layout()
    _safe_savefig(fig, out_path)

# ══════════════════════════════════════════════════════════════════════════
# synthetic self-test (the runnable correctness check, no test framework)
# ══════════════════════════════════════════════════════════════════════════

def _synth_session(fdir, sess, trials, delta, rng):
    os.makedirs(fdir, exist_ok=True)
    ev_rows, kin_rows = [], []
    for ti, (nominal, side) in enumerate(trials):
        # 162 = 180 - expected_error(18): cancels so delta_est recovers `delta`
        resp = wrap180(nominal + delta + 162.0 + rng.normal(0, 5.0))
        det = {"type": "baseline_wind", "wind_dir": side, "screen_side": side}
        if ti % 3 == 0:
            # plant a noiseless response_angle; load_trials must use it verbatim
            det["response_angle"] = float(wrap180(nominal + delta + 162.0))
        ev_rows.append({"event_name": "trial_start", "timestamp": ti * 10.0,
                        "session_num": 1, "trial_in_session": ti + 1,
                        "global_trial_id": str(ti), "details": json.dumps(det)})
        c, s = math.cos(math.radians(resp)), math.sin(math.radians(resp))
        for _ in range(5):
            kin_rows.append({"sys_time": 0.0, "ard_time": 0, "dx": 0.0, "dy": 0.0,
                             "dz": 0.0, "stim_state": 0, "global_trial_id": str(ti)})
        for _ in range(40):
            kin_rows.append({"sys_time": 0.0, "ard_time": 0,
                             "dx": c * (0.5 + rng.uniform(-0.05, 0.05)),
                             "dy": s * (0.5 + rng.uniform(-0.05, 0.05)),
                             "dz": 0.0, "stim_state": 1, "global_trial_id": str(ti)})
    ev_rows.append({"event_name": "phase_transition", "timestamp": 999.0,
                    "session_num": 1, "trial_in_session": np.nan,
                    "global_trial_id": np.nan, "details": "{}"})
    subj = "cricket_" + os.path.basename(fdir).replace(".", "")
    pd.DataFrame(ev_rows).to_csv(os.path.join(fdir, f"{subj}_session_{sess}_events.csv"),
                                 index=False, encoding="utf-8-sig")
    pd.DataFrame(kin_rows).to_csv(os.path.join(fdir, f"{subj}_session_{sess}_kinematics.csv"),
                                  index=False, encoding="utf-8-sig")


def _dir_hashes(root):
    return {os.path.relpath(os.path.join(r, f), root):
            hashlib.sha256(open(os.path.join(r, f), "rb").read()).hexdigest()
            for r, _, fs in os.walk(root) for f in fs}


def selftest():
    print("selftest: building synthetic dataset ...")
    planted = 7.0
    rng = np.random.default_rng(0)
    trials = [(90.0, "left"), (270.0, "right")] * 6
    n_planted = sum(ti % 3 == 0 for ti in range(len(trials))) * 2 * 3
    with tempfile.TemporaryDirectory() as tmp:
        in_dir, out_dir = os.path.join(tmp, "cali"), os.path.join(tmp, "out")
        for gname in ("d1", "d2", "d3"):
            for sess in (1, 2):
                _synth_session(os.path.join(in_dir, gname), sess, trials, planted, rng)
        input_hashes = _dir_hashes(in_dir)
        groups, folder_groups, folder_sessions = scan(in_dir, "folder")
        group_trials = {k: [] for k in groups}
        for k, sess in groups.items():
            for evp, kinp in sess:
                group_trials[k] += load_trials(evp, kinp, 90.0, 270.0, 1.0)
        deltas = {k: group_stats(tr, 18.0)["delta_est_deg"]
                  for k, tr in group_trials.items()}
        loo = loo_delta_std([group_trials[k] for k in sorted(groups)], 18.0)
        write_corrected(in_dir, out_dir, folder_sessions, folder_groups, deltas, 90.0, 270.0)

        ok_delta = all(abs(d - planted) <= 3.0 for d in deltas.values())
        ok_loo = math.isfinite(loo)
        ok_unchanged = _dir_hashes(in_dir) == input_hashes   # originals never modified
        kin_files = [os.path.join(r, f) for r, _, fs in os.walk(out_dir)
                     for f in fs if f.endswith("_kinematics.csv")]
        ev_files = [os.path.join(r, f) for r, _, fs in os.walk(out_dir)
                    for f in fs if f.endswith("_events.csv")]
        ok_mirror = (len(kin_files) == len(ev_files) == 6 and
                     {os.path.basename(os.path.dirname(p)) for p in kin_files} == set(groups))
        ok_ev_angle = any(
            "stim_angle" in det and "stim_angle_corrected" in det
            for evp in ev_files
            for det in (json.loads(d) for d in
                        pd.read_csv(evp, encoding="utf-8-sig")["details"]
                        if isinstance(d, str))
            if isinstance(det, dict))
        # every 3rd synthetic trial plants response_angle; assert those are used verbatim
        planted_resp = {90.0: float(wrap180(90.0 + planted + 162.0)),
                        270.0: float(wrap180(270.0 + planted + 162.0))}
        used = [t for tr in group_trials.values() for t in tr
                if abs(t["response"] - planted_resp[t["nominal"]]) < 1e-9]
        ok_resp_angle = len(used) == n_planted
        ok_corr = any("stim_angle_corrected" in
                      pd.read_csv(f, encoding="utf-8-sig").columns for f in kin_files)
        print(f"  planted delta={planted}; recovered={[round(v, 2) for v in deltas.values()]}")
        print(f"  loo_delta_std={loo:.3f}; originals_unchanged={ok_unchanged}; "
              f"mirror_ok={ok_mirror}; events_gained_angles={ok_ev_angle}; "
              f"response_angle_trials_used={ok_resp_angle} ({len(used)}/{n_planted})")
        ok = all([ok_delta, ok_loo, ok_corr, ok_unchanged, ok_mirror, ok_ev_angle, ok_resp_angle])
        print("PASS" if ok else "FAIL")
        return ok

# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════

def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Calibrate ring-airflow stimulus angle offset.")
    p.add_argument("--input", default="data")
    p.add_argument("--output", default="data_corrected")
    p.add_argument("--groups", type=int, default=None,
                   help="expected group count (warn on mismatch, don't crash)")
    p.add_argument("--group-by", choices=("folder", "subject"), default="folder")
    p.add_argument("--left-angle", type=float, default=90.0)
    p.add_argument("--right-angle", type=float, default=270.0)
    p.add_argument("--min-disp-mm", type=float, default=1.0)
    p.add_argument("--expected-error-deg", type=float, default=18.0)
    p.add_argument("--plot", dest="plot", action="store_true", default=True)
    p.add_argument("--no-plot", dest="plot", action="store_false")
    p.add_argument("--selftest", action="store_true",
                   help="run synthetic correctness check and exit")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.selftest:
        sys.exit(0 if selftest() else 1)
    if not os.path.isdir(args.input):
        print(f"error: input dir not found: {args.input}", file=sys.stderr)
        sys.exit(2)
    if os.path.abspath(args.output) == os.path.abspath(args.input):
        print("error: --output must differ from --input", file=sys.stderr)
        sys.exit(2)

    groups, folder_groups, folder_sessions = scan(args.input, args.group_by)
    if args.groups is not None and len(groups) != args.groups:
        print(f"warning: --groups {args.groups} but discovered {len(groups)} groups",
              file=sys.stderr)

    group_trials = {k: [] for k in groups}
    for k, sess in groups.items():
        for evp, kinp in sess:
            group_trials[k] += load_trials(evp, kinp, args.left_angle,
                                           args.right_angle, args.min_disp_mm)

    report_groups, group_deltas, all_valid = [], {}, []
    for k in sorted(groups):
        st = group_stats(group_trials[k], args.expected_error_deg)
        st["group"] = k
        st["sides"] = side_stats(group_trials[k], st["delta_est_deg"])
        group_deltas[k] = st["delta_est_deg"]
        all_valid += [(k, t) for t in group_trials[k]]
        report_groups.append(st)

    loo_std = loo_delta_std([group_trials[k] for k in sorted(groups)],
                            args.expected_error_deg)
    write_corrected(args.input, args.output, folder_sessions, folder_groups,
                    group_deltas, args.left_angle, args.right_angle)
    os.makedirs(args.output, exist_ok=True)

    report = {"n_groups": len(groups), "loo_delta_std_deg": loo_std,
              "nominal_mapping": {"left": args.left_angle, "right": args.right_angle},
              "cross_check_note": ("regression_implied_delta_deg (=(intercept+1)/slope) "
                                   "equals delta_est only when the data follows the "
                                   "regression prior (slope ~ 0.9, intercept ~ -1); "
                                   "diagnostic only, not a gate."),
              "parameters": vars(args), "groups": report_groups}
    with open(os.path.join(args.output, "calibration_report.json"), "w") as fh:
        json.dump(_clean(report), fh, indent=2)

    if args.plot:
        make_plot(all_valid, group_deltas,
                  os.path.join(args.output, "calibration_report.png"))

    print(f"groups: {len(groups)}")
    for st in report_groups:
        print(f"  {st['group']}: n={st['n_trials']} "
              f"delta_est={st['delta_est_deg']:.1f} circ_err={st['circ_mean_error_deg']:.1f} "
              f"slope={st['slope']:.2f} intercept={st['intercept']:.1f} r={st['r']:.2f}")
    print(f"loo_delta_std_deg: {loo_std:.2f}")
    print(f"report: {os.path.join(args.output, 'calibration_report.json')}")
    print(f"plot:   {os.path.join(args.output, 'calibration_report.png')}")


if __name__ == "__main__":
    main()
