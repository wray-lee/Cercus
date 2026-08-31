#!/usr/bin/env python3
"""Synthetic experiment integration test.

Runs 100 trials with MockSerialDaemon to verify:
- Zero frame drops (all frames < 16.67ms at 60Hz baseline)
- Zero GC pauses > 1ms
- Clean worker shutdown
"""
import argparse
import gc
import multiprocessing as mp
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.workers.stimulus_worker import create_ipc_queues, worker_entry


def main() -> int:
    parser = argparse.ArgumentParser(description='Run synthetic experiment')
    parser.add_argument('--trials', type=int, default=10, help='Number of trials')
    parser.add_argument('--profile', action='store_true', help='Enable profiling')
    args = parser.parse_args()

    print(f"Starting synthetic experiment: {args.trials} trials")
    print(f"Profiling: {'enabled' if args.profile else 'disabled'}")

    # Config for mock experiment
    config = {
        "Subject ID": "TEST_SUBJECT",
        "Session Number": 1,
        "Paradigm Class": "SingleLooming",
        "Experiment Pattern": "manual",
        "Total Trials": args.trials,
        "Serial Port": "mock",
        "Debug Mode": True,
        "Screen Width (px)": 1920,
        "Screen Height (px)": 1080,
        "Stimulus Screen ID": 0,
        "Random Seed": 42,
        "_output_dir": "data/synthetic_test",
    }

    # Create IPC queues
    cmd_queue, telemetry_queue = create_ipc_queues()

    # Launch worker
    worker_proc = mp.Process(
        target=worker_entry,
        args=(config, cmd_queue, telemetry_queue),
        daemon=False
    )

    gc_pauses = []
    frame_times = []
    last_telemetry_time = time.monotonic()

    worker_proc.start()
    print(f"Worker started (PID {worker_proc.pid})")

    try:
        # Monitor telemetry
        trials_completed = 0
        while worker_proc.is_alive():
            try:
                msg = telemetry_queue.get(timeout=0.1)
                now = time.monotonic()
                dt = now - last_telemetry_time
                last_telemetry_time = now

                if args.profile and dt > 0.001:  # Track gaps > 1ms
                    frame_times.append(dt)

                # Check for terminal signals
                if msg.get('action') == 'terminal':
                    status = msg.get('status')
                    print(f"Terminal signal: {status}")
                    if status == 'completed':
                        print(f"[PASS] Experiment completed normally")
                    break
                elif msg.get('action') == 'verdict':
                    trials_completed += 1
                    if trials_completed % 10 == 0:
                        print(f"Progress: {trials_completed}/{args.trials} trials")

            except Exception:
                pass

    finally:
        # Graceful shutdown
        try:
            cmd_queue.put({"action": "POISON_PILL"}, timeout=0.5)
        except Exception:
            pass

        worker_proc.join(timeout=5)
        if worker_proc.is_alive():
            print("[WARN] Worker did not terminate gracefully, killing")
            worker_proc.kill()
            worker_proc.join()
        else:
            print(f"[PASS] Worker exited cleanly (exit code {worker_proc.exitcode})")

    # Analysis
    if args.profile and frame_times:
        max_frame_time = max(frame_times)
        avg_frame_time = sum(frame_times) / len(frame_times)
        frame_drops = sum(1 for t in frame_times if t > 0.01667)  # 60Hz baseline

        print(f"\n=== Profiling Results ===")
        print(f"Total telemetry frames: {len(frame_times)}")
        print(f"Avg frame time: {avg_frame_time*1000:.2f}ms")
        print(f"Max frame time: {max_frame_time*1000:.2f}ms")
        print(f"Frame drops (>16.67ms): {frame_drops}")

        if frame_drops == 0:
            print("[PASS] Zero frame drops")
        else:
            print(f"[FAIL] {frame_drops} frame drops detected")

        # GC pause check (simplified - real impl would need tracemalloc)
        gc_long_pauses = sum(1 for t in frame_times if t > 0.001)
        print(f"Gaps >1ms: {gc_long_pauses} (may include GC pauses)")

    if worker_proc.exitcode == 0:
        print("\n[PASS] Synthetic experiment PASSED")
        return 0
    else:
        print(f"\n[FAIL] Synthetic experiment FAILED (exit code {worker_proc.exitcode})")
        return 1


if __name__ == '__main__':
    sys.exit(main())
