# ADR 0003: Zero-Allocation Hot Paths for Kinematic Tracking

## Status
Accepted

## Date
2025-02-28

## Context
At 144 Hz+ rendering rates and high-frequency optical mouse sensor polling, dynamic memory allocations in the inner loop cause frequent Python Garbage Collection (GC) sweeps. GC pauses introduce frame jitter and timing glitches that compromise behavioural experiments.

## Decision
Design the kinematic calculation engine (`KinematicEngine` in `src/core/kinematics.py`) and hot telemetry processing loops to operate with zero heap allocations during active frames:
- Pre-allocate all engine internal state in `__slots__` with primitive C-level floats.
- Perform all vector projections, turning angle calculations, and distance accumulations in-place.
- Forbid `list()`, `dict()`, `set()`, `str()` instantiations, list/dict comprehensions, and dynamic tuple creation inside `KinematicEngine.update()` and `KinematicEngine.evaluate_trigger()`.
- Pre-allocate scratch arrays and buffers in vectorized paradigms (`OpticFlowParadigm`, `MovementTraceParadigm`) during `prepare_trial()` rather than allocating per frame.
- Enforce zero-allocation compliance via AST static analysis in `scripts/audit_boundaries.py`.

## Consequences
### Positive
- Predictable, sub-millisecond execution time per frame.
- Elimination of GC pauses and frame stutter during critical stimulus windows.

### Negative / Trade-offs
- Code in hot paths must be written carefully using pre-allocated slots and in-place math rather than high-level Python dynamic data structures.
