"""AppState — reactive state object consumed by UI pages.

Updated by the polling loop via apply(poll_result). No UI framework dependency.
"""
import math
from typing import Any, Dict, List, Optional, Tuple


class AppState:
    """Centralized reactive state for dashboard and monitor pages."""

    TRAIL_JUMP_MM = 50.0
    TRAIL_MAX_POINTS = 1000

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Reset all state to idle defaults."""
        # Live telemetry
        self.phase: str = "IDLE"
        self.ui_color: str = "gray"
        self.session_num: Any = "—"
        self.trial_idx: Any = "—"
        self.total_trials: Any = "—"
        self.hardware_metrics: dict = {}
        self.status_text: str = "Ready"
        self.status_color: str = "white"
        self.worker_status: str = "idle"
        self.worker_error: str = ""
        self.worker_died: bool = False
        self._aborting: bool = False

        # Trajectory
        self.trail_points: List[Tuple[float, float]] = []
        self._trail_last_phase: str = ""
        self._trail_min_x: Optional[float] = None
        self._trail_max_x: Optional[float] = None
        self._trail_min_y: Optional[float] = None
        self._trail_max_y: Optional[float] = None
        self.trail_angle: float = 0.0
        self.kinematic: dict = {}

        # Twin preview
        self.ui_twin: Optional[dict] = None

        # Verdicts
        self.verdict_history: List[dict] = []
        self.verdict_counts: dict = {"escape": 0, "startle": 0, "no_response": 0}
        self._verdict_last_session: Any = None

        # Config snapshot (for monitor display)
        self.config_snapshot: dict = {}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def trail_bbox(self) -> Optional[Tuple[float, float, float, float]]:
        """(min_x, max_x, min_y, max_y) or None if no points."""
        if self._trail_min_x is None:
            return None
        return (self._trail_min_x, self._trail_max_x,
                self._trail_min_y, self._trail_max_y)

    @property
    def is_aborting(self) -> bool:
        """True between STOP being pressed and the worker actually dying."""
        return self._aborting

    # ------------------------------------------------------------------
    # Event application
    # ------------------------------------------------------------------

    def set_aborting(self) -> None:
        """Mark the experiment as aborting — suppresses telemetry overwrites."""
        self._aborting = True
        self.phase = 'ABORTING'
        self.ui_color = 'orange'
        self.status_text = 'Stopping experiment...'
        self.worker_status = 'worker_abort'

    def apply(self, poll_result: dict) -> None:
        """Apply a poll_telemetry result dict to update state."""
        tel = poll_result.get("telemetry")
        # Suppress telemetry overwrites while aborting — the worker may
        # still be sending frames until it processes the POISON_PILL.
        if tel and not self._aborting:
            self._apply_telemetry(tel)

        for vd in poll_result.get("verdicts", []):
            self._append_verdict(vd)

        terminal = poll_result.get("terminal")
        if terminal:
            action = terminal.get("action", "")
            self.worker_status = action
            self.worker_error = terminal.get("error", "")

        self.worker_died = poll_result.get("worker_died", False)
        if self.worker_died:
            self._aborting = False  # terminal — clear abort suppression

    def _apply_telemetry(self, data: dict):
        self.phase = str(data.get("phase", "—"))
        self.ui_color = data.get("ui_color", "gray")
        self.session_num = data.get("session_num", "—")
        self.trial_idx = data.get("trial_idx", "—")
        self.total_trials = data.get("total_trials", "—")
        self.ui_twin = data.get("ui_twin")

        ui_metrics = data.get("ui_metrics") or {}
        self.hardware_metrics = ui_metrics

        # Session change clears verdicts
        sess = data.get("session_num")
        if sess is not None and sess != self._verdict_last_session:
            self._verdict_last_session = sess
            self.verdict_history.clear()
            self.verdict_counts = {"escape": 0, "startle": 0, "no_response": 0}

        # Trajectory
        self._update_trajectory(data.get("phase", ""), ui_metrics)

    def _update_trajectory(self, raw_phase: str, ui_metrics: dict):
        # Keep one trail for all phases within a trial; reset only at a
        # waiting/interval boundary or when the session/trial changes.
        raw_phase = str(raw_phase or '')
        if raw_phase.startswith("ITI"):
            trail_epoch = "ITI"
        elif raw_phase.startswith("ISI"):
            trail_epoch = "ISI"
        elif raw_phase.startswith("Kinematic"):
            trail_epoch = "Kinematic"
        elif raw_phase.startswith(("Wait", "WAIT")):
            trail_epoch = "WAIT"
        elif raw_phase in ("Adaptation", "Initial Baseline", "IDLE", "ABORTING", ""):
            trail_epoch = raw_phase
        else:
            session = self.session_num if self.session_num not in ("—", None) else 0
            trial = self.trial_idx if self.trial_idx not in ("—", None) else 0
            trail_epoch = f"TRIAL_{session}_{trial}"

        if trail_epoch != self._trail_last_phase:
            self._reset_trail()
            self._trail_last_phase = trail_epoch

        # Angle — always update (before draw, not lagged)
        try:
            self.trail_angle = float(ui_metrics.get("k_angle", 0.0))
        except (ValueError, TypeError):
            self.trail_angle = 0.0

        # Kinematic readouts
        for k in ("k_angle", "k_turn_speed", "k_disp"):
            if k in ui_metrics:
                self.kinematic[k] = ui_metrics[k]

        px = ui_metrics.get("pos_x")
        py = ui_metrics.get("pos_y")
        if px is None or py is None:
            return

        try:
            fpx, fpy = float(px), float(py)
        except (ValueError, TypeError):
            return
        if not (math.isfinite(fpx) and math.isfinite(fpy)):
            return

        # Jump gate
        if self.trail_points:
            lx, ly = self.trail_points[-1]
            if math.hypot(fpx - lx, fpy - ly) > self.TRAIL_JUMP_MM:
                self._reset_trail()
                return

        self.trail_points.append((fpx, fpy))
        self.trail_points = self.trail_points[-self.TRAIL_MAX_POINTS:]

        # Monotonic bbox
        if self._trail_min_x is None:
            self._trail_min_x = self._trail_max_x = fpx
            self._trail_min_y = self._trail_max_y = fpy
        else:
            self._trail_min_x = min(self._trail_min_x, fpx)
            self._trail_max_x = max(self._trail_max_x, fpx)
            self._trail_min_y = min(self._trail_min_y, fpy)
            self._trail_max_y = max(self._trail_max_y, fpy)

    def _reset_trail(self):
        self.trail_points = []
        self._trail_last_phase = ""
        self._trail_min_x = None
        self._trail_max_x = None
        self._trail_min_y = None
        self._trail_max_y = None
        self.trail_angle = 0.0

    def _append_verdict(self, vd: dict):
        self.verdict_history.append(vd)
        resp = vd.get("response", "no_response")
        if resp in self.verdict_counts:
            self.verdict_counts[resp] += 1
