# CONTEXT.md — Cercus System & Domain Harness Architecture

This document defines the domain model, system topology, and agent execution harness for **Cercus** — a real-time multisensory behavioral experiment system (visual stimulus rendering, kinematic optical tracking, and precision wind puff hardware control).

---

## 1. Elevator Pitch

Cercus is a high-precision Python framework for insect (cricket) behavioral paradigms. It coordinates real-time visual stimulus generation, hardware-level wind trigger synchronization, optical flow/mouse kinematic tracking, and dual UI/web telemetry mirroring without sacrificing real-time deterministic loop performance.

---

## 2. Ubiquitous Language & Core Concepts

| Term | Definition |
| :--- | :--- |
| **Paradigm** | High-level experimental protocol (`BaseParadigm`) defining stimulus sequence, timing, trial generation, and per-frame state logic (e.g., `LoomingParadigm`, `OpticFlowParadigm`, `MovementTraceParadigm`). |
| **Trial / Session** | **Trial**: A single stimulus execution unit with target parameters (e.g., TTC, wind angle). **Session**: A collection of randomized trials separated by ITI (Inter-Trial Interval, 60–90s) and ISI (Inter-Session Interval, 5–10min). |
| **Kinematics / KinematicEngine** | High-frequency engine in `kinematics.py` evaluating movement triggers and tracking insect velocity with zero GC allocations in hot paths. |
| **Hardware / SerialDaemon** | Arduino Mega 2560 interface (`hardware.py`) controlling solenoid valves and reading optical mouse sensor frames non-blockingly via background daemon threads. |
| **CoreRenderer** | Pure stateless visual drawing engine (`render.py`) mapping geometry objects to Pygame surfaces. |
| **Worker Process** | Multi-processing worker node (`stimulus_worker.py`, `calibration_worker.py`) executing trial logic in an isolated process away from the main UI thread. |
| **WebBridge & Telemetry Mirror** | Asynchronous HTTP/WebSocket server (`web_telemetry.py`, `web_bridge.py`) broadcasting live canvas frames and status telemetry to browser clients (`ui/static/index.html`). |

---

## 3. Architectural Topology & Boundary Rules

```
+-----------------------------------------------------------------------+
| Main UI Process (dashboard.py)                                        |
|   ├── CustomTkinter Dashboard (Non-blocking callbacks)                |
|   └── Web Bridge / Server (Static HTML + WebSocket mirror)            |
+-----------------------------------+-----------------------------------+
                                    | mp.Queue (cmd_queue / telemetry_queue)
                                    v
+-----------------------------------------------------------------------+
| Worker Process (stimulus_worker.py / calibration_worker.py)            |
|   ├── SerialDaemon (Background I/O threads to Arduino)                |
|   ├── KinematicEngine (Zero-allocation hot loop)                      |
|   ├── BaseParadigm Subclass (State & Trial logic)                     |
|   └── CoreRenderer (Stateless Pygame drawing)                         |
+-----------------------------------------------------------------------+
```

### Boundary Constraints (Hard Rules)

1. **Process Isolation (`BOUNDARY.md`)**:
   - `dashboard.py` and workers (`stimulus_worker.py`) MUST NOT share global state or memory.
   - Cross-process communication MUST ONLY use `multiprocessing.Queue` (`cmd_queue`, `telemetry_queue`).

2. **Renderer Absolute Statelessness (`src/core/BOUNDARY.md`)**:
   - `render.py` (`CoreRenderer`) is strictly a pure drawing engine. No state machines, time calculations, or business logic.

3. **Non-Blocking Hardware I/O & Zero-Allocation (`src/core/BOUNDARY.md`)**:
   - Hardware I/O operates via background threads. `time.sleep()` is forbidden in hot paths.
   - `KinematicEngine.update` and `evaluate_trigger` MUST NOT allocate memory (no `list()`, `dict()`, `str()` instantiations in frame loops).

4. **Paradigm Extension Boundary (`src/models/BOUNDARY.md`)**:
   - All paradigms MUST inherit `BaseParadigm` and register in `PARADIGM_REGISTRY`.
   - Never modify core infrastructure (`render.py`, `hardware.py`, `kinematics.py`) for individual paradigm features.

5. **UI Boundary (`src/ui/BOUNDARY.md`)**:
   - CustomTkinter callbacks MUST be non-blocking. UI collects parameters into config dicts and hands them off via queues.

---

## 4. Agent & Developer Execution Directives

- **Git Identity Verification**: Always verify `git config user.email` returns `i@wray7.top` (Author: `wray-lee`) before committing.
- **Dependency Lock**: `requirements.txt` is locked. Do not add external packages without explicit approval.
- **Codebase Navigation**: Consult subsystem `BOUNDARY.md` files before modifying `src/core`, `src/models`, `src/ui`, or `src/workers`.
- **Review & Test Protocol**: Changes to hot paths or paradigm logic require non-blocking unit tests (`tests/`) and zero-allocation compliance checks.
