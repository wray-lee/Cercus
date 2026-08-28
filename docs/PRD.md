# Product Requirement Document (PRD) — Cercus System

**Status**: Draft / Active Spec  
**Author**: `wray-lee <i@wray7.top>`  
**Date**: 2025-02-28  
**Target Architecture**: Cercus v0.1.0+ Multi-Process Behavior & Telemetry Engine  

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
- **Dual UI & Web Mirroring**: Provide desktop CustomTkinter controls alongside a low-latency web canvas mirror for remote observation.

### Non-Goals
- **In-process Direct Execution**: Running hardware drivers or experiment loops inside the CustomTkinter UI thread.
- **Dynamic Dependency Injection**: Adding heavy third-party web or gaming engines outside python stdlib/pygame/customtkinter/websockets.
- **Shared Memory Synchronization**: Using `mp.shared_memory` or shared global objects across worker process boundaries.

---

## 3. Domain Model & Key Concepts

| Concept | Description |
| :--- | :--- |
| **BaseParadigm** | Abstract state machine defining parameter schema, trial generation, frame processing (`process_frame`), and idle state frames (`get_idle_frame`). |
| **KinematicEngine** | Hot-path engine receiving raw optical mouse readings ($dX, dY$), calculating directional velocity/displacement vectors, and evaluating trigger threshold conditions. |
| **SerialDaemon** | Non-blocking thread-driven hardware interface managing Arduino Mega 2560 communication for solenoid valve activation and sensor input. |
| **CoreRenderer** | Pure geometry visual rendering engine mapping paradigm draw commands onto Pygame surfaces. |
| **StimulusWorker** | Isolated process hosting the execution loop (KinematicEngine + Paradigm + SerialDaemon + Renderer). |
| **WebTelemetry** | Async server broadcasting encoded canvas frames and telemetry JSON to web consumers. |

---

## 4. Technical Architecture & Component Design

### 4.1 System Topology

```
+-------------------------------------------------------------------------------+
| Main Controller Process (ui/dashboard.py)                                     |
|   ├── CustomTkinter GUI (Form controls & status bar)                          |
|   └── Web Server & Telemetry Bridge (ui/web_bridge.py -> ui/static/index.html)|
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
4. Each frame: `SerialDaemon` delivers kinematics -> `KinematicEngine` updates -> `BaseParadigm` returns draw commands & hardware triggers -> `SerialDaemon` fires solenoids -> `CoreRenderer` draws surface.
5. Telemetry frame is posted to `telemetry_queue` -> `dashboard.py` / `web_bridge.py` forwards to UI and Web Sockets.

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
