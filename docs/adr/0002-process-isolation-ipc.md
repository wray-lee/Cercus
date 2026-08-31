# ADR 0002: Physical Process Isolation and Multiprocessing Queue IPC

## Status
Accepted

## Date
2025-02-28

## Context
Cricket behavioral experiments demand microsecond-precision timing synchronization between visual stimulus rendering (60–144 Hz) and tactile wind puff delivery. UI event loops, garbage collection pauses, or web rendering latencies in the main process must never interfere with the deterministic real-time experiment execution loop.

## Decision
Enforce strict physical process isolation between the UI process and experiment execution workers:
- Experiment execution runs in an isolated worker process (`GenericWorker` in `src/workers/stimulus_worker.py` or `CalibrationWorker` in `src/workers/calibration_worker.py`).
- All cross-process communication is strictly restricted to bounded `multiprocessing.Queue` instances:
  - `cmd_queue` (main UI -> worker): for commands, serialized experiment configuration, and abort signals.
  - `telemetry_queue` (worker -> main UI): for state snapshots, downsampled telemetry, and terminal signals.
- Forbidden primitives across process boundaries:
  - No shared memory (`multiprocessing.shared_memory`, `multiprocessing.Value`, `multiprocessing.Array`, `multiprocessing.Manager`, `multiprocessing.Pipe`).
  - No shared mutable global variables.
  - No passing non-serializable objects (Locks, Threads, Processes, Lambdas) through IPC queues.
  - UI layer must never import or instantiate core hardware drivers or worker internal classes directly.

## Consequences
### Positive
- Total immunity of visual stimulus and hardware timing against UI freezes, rendering lag, or GC pauses.
- Clean process lifecycle: worker can be cleanly spawned, monitored, and terminated.

### Negative / Trade-offs
- All inter-process messages must be serializable.
- Telemetry data must be downsampled / debounced before pushing into `telemetry_queue` to prevent queue saturation.
