# BOUNDARY.md — Paradigm Extension Boundary

## Interface Mandatory Inheritance

- ALL new experiment paradigms MUST inherit `BaseParadigm` abstract class.
- ALL new paradigms MUST implement:
  - `get_available_patterns() -> List[str]`
  - `get_parameter_schema() -> Dict[str, Dict[str, Any]]`
  - `generate_trials(pattern_key: str) -> List[Dict[str, Any]]`
  - `prepare_trial(trial_context: dict) -> str`
  - `process_frame(elapsed_time: float, trial_context: dict, hw_telemetry: dict) -> Tuple[bool, List[dict], dict]`
  - `get_idle_frame(hw_telemetry: dict) -> Tuple[List[dict], dict]`
- Registration: new paradigms MUST be added to `PARADIGM_REGISTRY` in `paradigm.py`.

## Reverse Modification Prohibition

- To satisfy a specific experiment's needs (e.g., Looming, OpticFlow, MovementTrace), it is PROHIBITED to:
  - Modify `src/core/render.py` rendering logic.
  - Modify `src/core/hardware.py` serial parsing logic.
  - Modify `src/core/kinematics.py` kinematic engine logic.
- The core infrastructure MUST remain paradigm-agnostic.
- If a paradigm needs different rendering or hardware behavior, it MUST be handled within the paradigm's own `process_frame` or `prepare_trial` methods via command dictionaries.
