import math
from typing import Callable, Optional


class KinematicEngine:
    """Real-time kinematics processor for cricket motion tracking.

    Computes turning angle (cumulative dz), turning speed (dz/dt),
    instantaneous movement speed (sqrt(dx^2+dy^2)/dt), and ready-phase
    cumulative displacement. Designed for 144Hz+ frame loops with zero
    heap allocation in update() and evaluate_trigger().
    """

    # Default quiet-speed threshold (units/sec) for stationary trigger detection.
    # Paradigms may override via evaluate_trigger's quiet_threshold parameter.
    QUIET_SPEED_THRESHOLD: float = 10.0

    # Pre-allocated slot names (documented for clarity; all are plain floats)
    __slots__ = (
        "_error_cb",
        "_last_t",
        "_cum_dz",
        "_cum_disp",
        "_turn_speed",
        "_move_speed",
        "_peak_move_speed",
        "_ready",
        # 2-D position tracking
        "_pos_x",
        "_pos_y",
        # sustained-speed trigger state
        "_speed_above_since",
        "_speed_threshold_active",
        # scratch for evaluate_trigger (avoids local vars)
        "_trig_dist_sq",
        "_trig_angle_abs",
        # frame-rate buffering for dt folding protection
        "_buf_dt",
        "_buf_dx",
        "_buf_dy",
        "_buf_dz",
        "_radius_mm",
    )

    def __init__(self, error_callback: Optional[Callable[[str, str, object], None]] = None):
        self._error_cb = error_callback
        self._last_t = -1.0
        self._cum_dz = 0.0
        self._cum_disp = 0.0
        self._turn_speed = 0.0
        self._move_speed = 0.0
        self._peak_move_speed = 0.0
        self._pos_x = 0.0
        self._pos_y = 0.0
        self._ready = False
        self._speed_above_since = -1.0
        self._speed_threshold_active = -1.0
        self._trig_dist_sq = 0.0
        self._trig_angle_abs = 0.0
        self._buf_dt = 0.0
        self._buf_dx = 0.0
        self._buf_dy = 0.0
        self._buf_dz = 0.0
        self._radius_mm = 30.0

    # ------------------------------------------------------------------
    # Public read-only properties (no allocation — just attribute access)
    # ------------------------------------------------------------------

    @property
    def cum_dz(self) -> float:
        """Cumulative turning angle (degrees, algebraic sum of dz)."""
        return self._cum_dz

    @property
    def turn_speed(self) -> float:
        """Turning speed (degrees/sec)."""
        return self._turn_speed

    @property
    def move_speed(self) -> float:
        """Instantaneous movement speed (units/sec)."""
        return self._move_speed

    @property
    def peak_move_speed(self) -> float:
        """Peak movement speed reached during trial (units/sec)."""
        return self._peak_move_speed

    @property
    def effective_speed(self) -> float:
        """Best available speed metric: peak if recorded, else instantaneous."""
        return self._peak_move_speed if self._peak_move_speed > 0.0 else self._move_speed

    @property
    def cum_disp(self) -> float:
        """Cumulative displacement during ready phase (same units as dx/dy)."""
        return self._cum_disp

    @property
    def pos_x(self) -> float:
        """Cumulative X position (same units as dx)."""
        return self._pos_x

    @property
    def pos_y(self) -> float:
        """Cumulative Y position (same units as dy)."""
        return self._pos_y

    # ------------------------------------------------------------------
    # Reset — call at each trial boundary
    # ------------------------------------------------------------------

    def reset(self):
        """Reset all accumulators for a new trial."""
        self._last_t = -1.0
        self._cum_dz = 0.0
        self._cum_disp = 0.0
        self._turn_speed = 0.0
        self._move_speed = 0.0
        self._peak_move_speed = 0.0
        self._pos_x = 0.0
        self._pos_y = 0.0
        self._ready = True
        self._speed_above_since = -1.0
        self._speed_threshold_active = -1.0
        self._buf_dt = 0.0
        self._buf_dx = 0.0
        self._buf_dy = 0.0
        self._buf_dz = 0.0
        self._radius_mm = 30.0

    # ------------------------------------------------------------------
    # Update — called every frame with raw hardware telemetry
    # ------------------------------------------------------------------

    def update(self, t: float, dx: float, dy: float, dz: float):
        """Ingest one telemetry sample. All arithmetic is in-place on
        pre-allocated float slots — no objects are created.

        Args:
            t: system timestamp (seconds).
            dx: incremental x displacement.
            dy: incremental y displacement.
            dz: incremental z displacement (turning axis).
        """
        # --- dirty-data guard (rejects entire sample) ---
        if not self._finite(t) or not self._finite(dx) or not self._finite(dy) or not self._finite(dz):
            if self._error_cb:
                self._error_cb("data_anomaly", "non-finite telemetry value", (t, dx, dy, dz))
            return

        # --- per-frame spike guard (rejects single-frame outliers) ---
        # Serial glitches occasionally deliver dz/dx/dy magnitudes far beyond
        # physically possible per-frame motion. One such sample must not
        # corrupt the accumulated heading/position — previously a dz of ~500mm
        # added ~1900° to cum_dz in a single frame and shifted every later pos.
        d_theta = math.degrees(dz / self._radius_mm)
        if abs(d_theta) > 30.0 or abs(dx) > 20.0 or abs(dy) > 20.0:
            if self._error_cb:
                self._error_cb("data_anomaly", "out-of-range telemetry sample", (t, dx, dy, dz))
            return

        # --- spatial accumulation (unconditional — timing cannot block this) ---
        # dz is arc length (mm) on 30mm radius sphere → convert to degrees.
        # Rotate this frame's displacement by the *previous* heading first,
        # then advance the heading. Using the freshly-updated angle would
        # rotate the displacement by the very turn applied this same frame.
        rad = math.radians(self._cum_dz)
        # 将体坐标系增量投影至全局坐标系
        dx_body = -dx
        dy_body = -dy
        dx_glob = dx_body * math.cos(rad) - dy_body * math.sin(rad)
        dy_glob = dx_body * math.sin(rad) + dy_body * math.cos(rad)
        self._pos_x += dx_glob
        self._pos_y += dy_glob
        self._cum_dz += d_theta
        step_dist = math.sqrt(dx * dx + dy * dy)
        if self._ready:
            self._cum_disp += step_dist

        # --- first frame: record baseline time, skip speed calculation ---
        if self._last_t < 0.0:
            self._last_t = t
            return

        dt = t - self._last_t

        # --- timing guard: only blocks speed buffering, not spatial data ---
        if dt <= 0.0 or dt > 1.0:
            if self._error_cb:
                self._error_cb("timing_error", f"dt={dt:.6f} out of range", (self._last_t, t))
            self._last_t = t
            return

        self._last_t = t

        # --- frame-rate buffering: accumulate raw deltas, skip speed update
        #     until >= 5ms of wall time has elapsed (dt folding protection) ---
        self._buf_dt += dt
        self._buf_dx += dx
        self._buf_dy += dy
        self._buf_dz += dz

        if self._buf_dt < 0.005:
            return

        # use buffered values for speed calculation
        bdt = self._buf_dt
        self._buf_dt = 0.0

        # turning speed: convert buffered arc length (mm) to degrees, then divide by dt
        self._turn_speed = math.degrees(self._buf_dz / self._radius_mm) / bdt
        self._buf_dz = 0.0

        # instantaneous movement speed: sqrt(dx^2 + dy^2) / dt
        step_dist = math.sqrt(self._buf_dx * self._buf_dx + self._buf_dy * self._buf_dy)
        self._move_speed = step_dist / bdt
        if self._move_speed > self._peak_move_speed:
            self._peak_move_speed = self._move_speed
        self._buf_dx = 0.0
        self._buf_dy = 0.0

        # sustained-speed tracking: update crossing timestamp
        if self._speed_threshold_active >= 0.0:
            if self._speed_threshold_active == 0.0:
                # stationary trigger: any movement resets the timer
                if self._move_speed > self.QUIET_SPEED_THRESHOLD:
                    self._speed_above_since = -1.0
                elif self._speed_above_since < 0.0:
                    self._speed_above_since = t
            else:
                # motion trigger: speed dropping below threshold resets the timer
                if self._move_speed < self._speed_threshold_active:
                    self._speed_above_since = -1.0
                elif self._speed_above_since < 0.0:
                    self._speed_above_since = t


    # ------------------------------------------------------------------
    # Trigger evaluation — zero-allocation boolean check
    # ------------------------------------------------------------------

    def evaluate_trigger(
        self,
        threshold_dist: float,
        threshold_angle: float,
        threshold_speed: float = -1.0,
        speed_duration_ms: float = 0.0,
    ) -> bool:
        """Check whether motion exceeds any configured threshold.

        Args:
            threshold_dist: displacement threshold (mm). 0 = disabled.
            threshold_angle: turning angle threshold (degrees). 0 = disabled.
            threshold_speed: movement speed threshold (units/sec). 0 = disabled.
            speed_duration_ms: speed must remain >= threshold_speed for this
                many continuous milliseconds before triggering. Resets if
                speed drops below threshold.

        Returns:
            True if any threshold is met/exceeded.
        """
        if threshold_dist > 0.0:
            if self._cum_disp >= threshold_dist:
                return True

        if threshold_angle > 0.0:
            if abs(self._cum_dz) >= threshold_angle:
                return True

        # sustained-speed trigger (or instantaneous when speed_duration_ms == 0)
        if threshold_speed >= 0.0:
            self._speed_threshold_active = threshold_speed
            if speed_duration_ms > 0.0:
                # Duration-gated: speed must stay above threshold for N ms
                if self._speed_above_since >= 0.0 and self._last_t >= 0.0:
                    elapsed_ms = (self._last_t - self._speed_above_since) * 1000.0
                    if elapsed_ms >= speed_duration_ms:
                        return True
            else:
                # Instantaneous speed check (speed_duration_ms == 0)
                if threshold_speed == 0.0:
                    # Stationary trigger: speed must be below quiet threshold
                    if self._move_speed <= self.QUIET_SPEED_THRESHOLD:
                        return True
                else:
                    # Motion trigger: current speed meets threshold
                    if self._move_speed >= threshold_speed:
                        return True
        else:
            self._speed_threshold_active = -1.0

        return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _finite(v: float) -> bool:
        """Check that v is a finite number (not None, NaN, or Inf)."""
        if v is None:
            return False
        try:
            return math.isfinite(v)
        except (TypeError, ValueError):
            return False
