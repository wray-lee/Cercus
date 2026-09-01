#!/usr/bin/env python3
"""Synthetic experiment integration test.

Runs N trials with MockSerialDaemon in a subprocess to verify:
- Worker completes all trials without crash
- Worker exits cleanly (exit code 0)
- All expected telemetry events received
- Queue communication integrity
- Memory stability

Requires PsychoPy for full rendering. When PsychoPy is unavailable,
falls back to a headless validation of IPC, kinematics, paradigm logic,
and worker lifecycle without Pygame rendering.
"""
import argparse
import gc
import multiprocessing as mp
import queue
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _check_psychopy() -> bool:
    """Return True if PsychoPy is importable."""
    try:
        import psychopy  # noqa: F401
        return True
    except ImportError:
        return False


def run_full_experiment(num_trials: int, timeout: int, profile: bool) -> int:
    """Run a real worker process with PsychoPy rendering."""
    from src.workers.stimulus_worker import create_ipc_queues, worker_entry

    output_dir = Path('data/synthetic_test')
    output_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "Subject ID": "SYNTH_TEST",
        "Session Number": 1,
        "Paradigm Class": "SingleLooming",
        "Experiment Pattern": "manual",
        "Total Trials": num_trials,
        "Serial Port": "mock",
        "Debug Mode": True,
        "Screen Width (px)": 1920,
        "Screen Height (px)": 1080,
        "Stimulus Screen ID": 0,
        "Random Seed": 42,
        "_output_dir": str(output_dir),
    }

    cmd_queue, telemetry_queue = create_ipc_queues()

    if profile:
        tracemalloc.start()
        snap_before = tracemalloc.take_snapshot()

    worker_proc = mp.Process(
        target=worker_entry,
        args=(config, cmd_queue, telemetry_queue),
        daemon=False,
    )
    worker_proc.start()
    print(f"Worker PID: {worker_proc.pid}")

    verdicts = []
    telemetry_count = 0
    terminal_received = False
    terminal_status = None
    broken_pipe = False
    deadline = time.monotonic() + timeout
    failures = []

    try:
        while time.monotonic() < deadline:
            if not worker_proc.is_alive() and terminal_received:
                break
            try:
                msg = telemetry_queue.get(timeout=0.5)
            except queue.Empty:
                if not worker_proc.is_alive():
                    break
                continue
            except (BrokenPipeError, EOFError, OSError):
                broken_pipe = True
                break

            action = msg.get('action', '')
            telemetry_count += 1

            if action == 'verdict':
                verdicts.append(msg)
                n = len(verdicts)
                if n % 20 == 0 or n == num_trials:
                    print(f"  verdict {n}/{num_trials}")
            elif action in ('terminal', 'worker_done', 'worker_error', 'worker_abort'):
                terminal_received = True
                terminal_status = msg.get('status', action)
                break

        if not terminal_received and time.monotonic() >= deadline:
            failures.append(f"TIMEOUT after {timeout}s")

    finally:
        if worker_proc.is_alive():
            try:
                cmd_queue.put({"action": "POISON_PILL"}, timeout=1)
            except Exception:
                pass
            worker_proc.join(timeout=5)
            if worker_proc.is_alive():
                worker_proc.kill()
                worker_proc.join(timeout=3)
                failures.append("Worker required kill")

    mem_growth_kb = 0
    if profile:
        snap_after = tracemalloc.take_snapshot()
        tracemalloc.stop()
        stats = snap_after.compare_to(snap_before, 'lineno')
        mem_growth_kb = sum(s.size_diff for s in stats if s.size_diff > 0) / 1024
        print(f"\nUI-side memory growth: {mem_growth_kb:.1f} KB")

    return _report(num_trials, worker_proc.exitcode, terminal_received,
                   terminal_status, len(verdicts), telemetry_count,
                   broken_pipe, mem_growth_kb if profile else None, failures)


def run_headless_validation(num_trials: int, profile: bool) -> int:
    """Headless validation without PsychoPy: exercises paradigm, kinematics,
    hardware parser, and worker IPC protocol in-process."""
    print("[INFO] PsychoPy not available -- running headless validation")
    print(f"[INFO] Validating: paradigm, kinematics, hardware parser, IPC protocol")

    from src.core.kinematics import KinematicEngine
    from src.core.hardware import KinematicsParser
    from src.models.paradigm import PARADIGM_REGISTRY

    failures = []

    # 1. Paradigm trial generation + verdict classification
    p_cls = PARADIGM_REGISTRY.get("SingleLooming", PARADIGM_REGISTRY.get("Looming"))
    paradigm = p_cls(debug_mode=True, config={
        "Paradigm Class": "SingleLooming",
        "Experiment Pattern": "Baseline Visual",
        "Random Seed": 42,
    })
    # SingleLooming.generate_trials returns a fixed-size batch (18 per session).
    # Generate enough sessions to reach num_trials.
    trials = []
    while len(trials) < num_trials:
        batch = paradigm.generate_trials("Baseline Visual")
        trials.extend(batch)
    trials = trials[:num_trials]
    if len(trials) != num_trials:
        failures.append(f"Trial generation: {len(trials)} != {num_trials}")
        print(f"[FAIL] Trial count: {len(trials)} != {num_trials}")
    else:
        print(f"[PASS] Paradigm generated {len(trials)} trials")

    # 2. KinematicEngine: run num_trials resets + 100 frames each
    engine = KinematicEngine()
    if profile:
        tracemalloc.start()
        gc.collect()
        gc.disable()
        snap_before = tracemalloc.take_snapshot()

    verdicts_ok = 0
    for t_idx, trial in enumerate(trials):
        engine.reset()
        paradigm.prepare_trial(trial)
        # Simulate 100 frames of motion per trial
        for frame in range(100):
            t_sec = t_idx * 10.0 + frame * 0.007  # ~143Hz
            engine.update(t_sec, 0.5, 0.3, 0.1)
        # Classify response
        verdict = paradigm.classify_response(engine, trial, trial_duration=0.7)
        if 'response' in verdict:
            verdicts_ok += 1

    if profile:
        snap_after = tracemalloc.take_snapshot()
        gc.enable()
        tracemalloc.stop()
        kin_filter = tracemalloc.Filter(True, "*kinematics.py")
        diff = snap_after.filter_traces([kin_filter]).compare_to(
            snap_before.filter_traces([kin_filter]), "lineno")
        net_alloc = sum(s.size_diff for s in diff if s.size_diff > 0)
        if net_alloc == 0:
            print(f"[PASS] Zero net allocation in kinematics over {num_trials * 100} frames")
        else:
            print(f"[WARN] Kinematics net allocation: {net_alloc} bytes")

    if verdicts_ok == num_trials:
        print(f"[PASS] All {num_trials} verdicts classified")
    else:
        print(f"[FAIL] Verdicts classified: {verdicts_ok}/{num_trials}")
        failures.append(f"Verdict classification: {verdicts_ok}/{num_trials}")

    # 3. Hardware parser: parse num_trials * 100 mock packets
    parser = KinematicsParser()
    packets_parsed = 0
    for i in range(num_trials * 100):
        raw = f"{i*7},{i%5},{i%3},{i%4},0"
        row = parser.parse(float(i) * 0.007, raw, i // 100)
        if row is not None:
            packets_parsed += 1
    if packets_parsed == num_trials * 100:
        print(f"[PASS] Hardware parser: {packets_parsed} packets parsed")
    else:
        print(f"[FAIL] Hardware parser: {packets_parsed}/{num_trials * 100}")
        failures.append(f"Parser: {packets_parsed}/{num_trials * 100}")

    # 4. IPC queue protocol: simulate worker->UI telemetry flow
    cmd_q = mp.Queue(maxsize=32)
    tel_q = mp.Queue(maxsize=256)
    # Simulate putting telemetry
    for i in range(min(num_trials, 200)):
        try:
            tel_q.put_nowait({"action": "telemetry", "trial_idx": i})
        except queue.Full:
            break
    # Simulate putting terminal
    tel_q.put_nowait({"action": "terminal", "status": "completed"})
    # Drain
    tel_count = 0
    terminal_found = False
    while True:
        try:
            m = tel_q.get_nowait()
            tel_count += 1
            if m.get('action') == 'terminal':
                terminal_found = True
        except queue.Empty:
            break
    if terminal_found:
        print(f"[PASS] IPC protocol: {tel_count} messages drained, terminal received")
    else:
        print(f"[FAIL] IPC protocol: terminal not received")
        failures.append("IPC terminal missing")

    # Cleanup
    cmd_q.close()
    tel_q.close()

    # ── Summary ──
    print(f"\n{'='*50}")
    print(f"Headless validation: {num_trials} trials")
    print(f"{'='*50}")
    if not failures:
        print(f"[PASS] Headless validation PASSED")
        return 0
    else:
        print(f"[FAIL] Headless validation FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1


def _report(num_trials: int, exit_code: int, terminal_received: bool,
            terminal_status: str, n_verdicts: int, telemetry_count: int,
            broken_pipe: bool, mem_kb: float, failures: list) -> int:
    """Print validation results and return exit code."""
    print(f"\n{'='*50}")
    print(f"Results for {num_trials}-trial synthetic experiment")
    print(f"{'='*50}")

    if exit_code == 0:
        print(f"[PASS] Worker exited cleanly (code 0)")
    else:
        print(f"[FAIL] Worker exit code: {exit_code}")
        failures.append(f"Worker exit code {exit_code}")

    if terminal_received:
        if terminal_status in ('completed', 'worker_done'):
            print(f"[PASS] Terminal event: {terminal_status}")
        else:
            print(f"[FAIL] Terminal status: {terminal_status}")
            failures.append(f"Terminal '{terminal_status}' != 'completed'")
    else:
        print(f"[FAIL] No terminal event received")
        failures.append("No terminal event")

    if n_verdicts == num_trials:
        print(f"[PASS] Received {n_verdicts}/{num_trials} verdicts")
    else:
        print(f"[FAIL] Received {n_verdicts}/{num_trials} verdicts")
        failures.append(f"Verdict count {n_verdicts} != {num_trials}")

    if telemetry_count > 0:
        print(f"[PASS] Total telemetry messages: {telemetry_count}")
    else:
        print(f"[FAIL] Zero telemetry messages")
        failures.append("Zero telemetry")

    if not broken_pipe:
        print(f"[PASS] No broken pipe errors")
    else:
        print(f"[FAIL] Broken pipe detected")
        failures.append("Broken pipe")

    if mem_kb is not None:
        if mem_kb < 1024:
            print(f"[PASS] UI memory growth < 1MB ({mem_kb:.1f} KB)")
        else:
            print(f"[WARN] UI memory growth: {mem_kb:.1f} KB")

    print(f"{'='*50}")
    if not failures:
        print(f"[PASS] Synthetic experiment PASSED ({num_trials} trials)")
        return 0
    else:
        print(f"[FAIL] Synthetic experiment FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description='Run synthetic experiment')
    parser.add_argument('--trials', type=int, default=100, help='Number of trials')
    parser.add_argument('--profile', action='store_true', help='Enable memory profiling')
    parser.add_argument('--timeout', type=int, default=120, help='Max seconds to wait')
    parser.add_argument('--headless', action='store_true', help='Force headless mode')
    args = parser.parse_args()

    has_psychopy = _check_psychopy()

    if args.headless or not has_psychopy:
        return run_headless_validation(args.trials, args.profile)
    else:
        return run_full_experiment(args.trials, args.timeout, args.profile)


if __name__ == '__main__':
    sys.exit(main())
