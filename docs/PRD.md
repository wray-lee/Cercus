# Product Requirement Document (PRD) — Cercus System

**Status**: Draft / Active Spec  
**Author**: `wray-lee <i@wray7.top>`  
**Date**: 2026-09-01
**Target Architecture**: Cercus v2.0 NiceGUI + PsychoPy multi-process behavior and telemetry engine

---

## 1. Context & Problem Statement

In insect neurobehavioral research (specifically crickets), analyzing spatiotemporal multisensory integration (e.g. visual looming stimuli combined with precise wind puffs at specific angles and TTC offsets) requires deterministic real-time synchronization between:
1. High-framerate visual stimulus rendering.
2. Microsecond-level solenoid valve control for pneumatic stimulus delivery.
3. High-frequency 2D kinematic tracking using optical flow mouse sensors.
4. Live execution monitoring and web-based telemetry mirroring without blocking experiment hot paths.

Legacy systems often suffer from GUI thread starvation, GC pause jitters, and cross-paradigm state leakage. Cercus solves this via strict process isolation, zero-allocation hot paths, stateless rendering, and non-blocking background serial daemons.

---

## 2. Goals & Non-Goals

### Goals
- **Real-Time Determinism**: Maintain stable 60+ FPS rendering while polling hardware kinematics at high frequency without UI/GC stutter.
- **Multisensory Synchronization**: Trigger wind solenoid valves with precise TTC (Time-To-Collision) offsets (e.g., -373ms to +200ms) relative to visual looming expansion ($l/v = 120$).
- **Architectural Isolation**: Separate UI controller, execution workers, and web telemetry into isolated processes connected exclusively via `multiprocessing.Queue`.
- **Paradigm Extensibility**: Provide a pluggable paradigm architecture (`BaseParadigm`) for Looming, OpticFlow, MovementTrace, etc., without modifying core infrastructure.
- **Unified UI & Web Monitoring**: Provide a NiceGUI native control window alongside a read-only LAN monitor route.

### Non-Goals
- **In-process Direct Execution**: Running hardware drivers or experiment loops inside the NiceGUI UI thread.
- **Uncontrolled Dependency Growth**: Adding unapproved third-party dependencies outside the locked requirements.
- **Shared Memory Synchronization**: Using `mp.shared_memory` or shared global objects across worker process boundaries.

---

## 3. Domain Model & Key Concepts

| Concept | Description |
| :--- | :--- |
| **BaseParadigm** | Abstract state machine defining parameter schema, trial generation, frame processing (`process_frame`), and idle state frames (`get_idle_frame`). |
| **KinematicEngine** | Hot-path engine receiving raw optical mouse readings ($dX, dY$), calculating directional velocity/displacement vectors, and evaluating trigger threshold conditions. |
| **SerialDaemon** | Non-blocking thread-driven hardware interface managing Arduino Mega 2560 communication for solenoid valve activation and sensor input. |
| **CoreRenderer** | Pure geometry visual rendering engine mapping paradigm draw commands onto PsychoPy objects. |
| **StimulusWorker** | Isolated process hosting the execution loop (KinematicEngine + Paradigm + SerialDaemon + Renderer). |
| **AppState** | Shared in-process reactive state updated by the global telemetry poller for dashboard and monitor pages. |

---

## 4. Technical Architecture & Component Design

### 4.1 System Topology

```
+-------------------------------------------------------------------------------+
| Main UI Process (src/ui/app.py)                                               |
|   ├── NiceGUI native dashboard (form controls & status)                       |
|   └── NiceGUI /monitor route (read-only LAN observation)                      |
+------------------------------------+------------------------------------------+
                                     |
                       cmd_queue     | telemetry_queue
                                     v
+-------------------------------------------------------------------------------+
| Worker Process (workers/stimulus_worker.py)                                   |
|   ├── KinematicEngine (src/core/kinematics.py) [Zero-Allocation]               |
|   ├── SerialDaemon (src/core/hardware.py)      [Background I/O Threads]       |
|   ├── CoreRenderer (src/core/render.py)        [Pure Stateless]               |
|   └── Paradigm (src/models/paradigm.py)        [Protocol State Machine]       |
+-------------------------------------------------------------------------------+
```

### 4.2 Data & Telemetry Flow
1. User configures trial parameters in `dashboard.py`.
2. UI serializes config into dictionary and puts `START` payload into `cmd_queue`.
3. `stimulus_worker.py` pops command, initializes selected `BaseParadigm`, and enters high-frequency loop.
4. Each frame: `SerialDaemon` delivers kinematics -> `KinematicEngine` updates -> `BaseParadigm` returns draw commands & hardware triggers -> `SerialDaemon` fires solenoids -> `CoreRenderer` draws PsychoPy objects.
5. Telemetry frames and terminal events are posted to `telemetry_queue`; the global UI poller updates `AppState` for both routes.

---

## 5. Invariants & System Boundaries

1. **Git & Commit Verification**: `user.email` MUST be `i@wray7.top` (`wray-lee`).
2. **Process Boundary**: No shared memory (`mp.Value`, `mp.Array`, `global`). Queue only.
3. **Hot-Path Zero Allocation**: `KinematicEngine.update` & `evaluate_trigger` MUST NOT instantiate new objects during active trials.
4. **Non-Blocking Hot Paths**: Hot paths MUST NOT call `time.sleep()` or blocking I/O calls.
5. **Paradigm Extension Safety**: Adding or extending paradigms MUST NOT touch `render.py`, `hardware.py`, or `kinematics.py`.

---

## 6. Verification & Test Plan

- **Kinematic Engine Verification**: Unit test zero-allocation velocity calculations and trigger evaluation against simulated optical mouse telemetry stream.
- **Paradigm Protocol Verification**: Verify trial generation logic, parameter schema validation, and ITI/ISI timer correctness for `LoomingParadigm` ($l/v = 120$, 9 patterns, 18 trials/session).
- **Process Communication Isolation**: Verify clean startup, pause, abort, and teardown sequences across `cmd_queue` and `telemetry_queue`.
