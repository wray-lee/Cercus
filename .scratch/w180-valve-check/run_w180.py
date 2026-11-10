"""Valve check on the real board: two baseline_wind trials, W100 (control) then W180.

W100: delay round(100/tan 1°) = 5729 ms, accepted by old and new firmware.
W180: delay 10312 ms, silently dropped by firmware with MAX_DELAY_MS = 10000.
Fires the real valve (left) and flashes the real photodiode marker.

Usage (psychopy env, repo root):  python .scratch/w180-valve-check/run_w180.py COM3 tmp/w180-check
Raw output (event + kinematics CSV) goes to the given dir under tmp/; not committed.
"""
import glob
import multiprocessing as mp
import sys

import pandas as pd

PORT, OUT = sys.argv[1], sys.argv[2]


def main() -> None:
    import psychopy.event as pe
    from src.models.paradigm import PARADIGM_REGISTRY, LoomingParadigm
    from src.workers.stimulus_worker import GenericWorker

    class W180Check(LoomingParadigm):
        def generate_trials(self, pattern_key):
            return [{"type": "baseline_wind", "target_ttc_ms": None, "lv_ratio_ms": lv,
                     "condition": f"W{lv}", "wind_dir": "left", "screen_side": "left"}
                    for lv in (100, 180)]

    PARADIGM_REGISTRY["W180Check"] = W180Check
    pe.getKeys = lambda *a, **k: ["space"]  # skip the Auto-mode SPACE wait

    cfg = {
        "Paradigm Class": "W180Check", "Subject ID": "w180_check", "Session Number": 1,
        "Total Sessions": 1, "Experiment Pattern": "Baseline Wind", "Number of Repetitions": 1,
        "Execution Mode": "Auto", "Serial Port": PORT, "Debug Mode": False,
        "Screen Width (px)": 3840, "Screen Height (px)": 1080, "Stimulus Screen ID": 1,
        "ITI Range (sec)": "1-1", "ISI Range (sec)": "0-0", "Random Seed": 1, "_output_dir": OUT,
    }
    cmd_q, tel_q = mp.Queue(), mp.Queue()
    GenericWorker(cfg, cmd_q, tel_q).run()
    while not tel_q.empty():
        item = tel_q.get_nowait()
        if item.get("action") in ("worker_error", "worker_abort", "worker_done"):
            print("worker:", item.get("action"), item.get("error", ""))

    ev = pd.read_csv(glob.glob(f"{OUT}/*events*.csv")[0], encoding="utf-8-sig")
    kin = pd.read_csv(glob.glob(f"{OUT}/*kinematics*.csv")[0], encoding="utf-8-sig")
    kin.columns = [c.strip() for c in kin.columns]
    for _, s in ev[ev.event_name == "trial_start"].iterrows():
        g = s.global_trial_id
        q = ev[(ev.global_trial_id == g) & (ev.event_name == "wind_cmd_queued")]
        k = kin[(kin.global_trial_id == g) & (kin.stim_state != 0)]
        cmd = q.details.iloc[0] if len(q) else "none"
        if len(k):
            on = (k.sys_time.iloc[0] - float(q.timestamp.iloc[0])) * 1000
            print(f"trial {g}: queued {cmd} | valve ON {on:.0f} ms after queue, "
                  f"{len(k)} rows, {(k.sys_time.iloc[-1] - k.sys_time.iloc[0]) * 1000:.0f} ms")
        else:
            print(f"trial {g}: queued {cmd} | NO valve action")


if __name__ == "__main__":
    mp.freeze_support()
    main()
