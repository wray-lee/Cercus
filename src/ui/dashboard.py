import os
import sys
import json
import math
import queue
import time
import threading
import multiprocessing as mp
from typing import Dict, Any, Optional, List
import customtkinter as ctk
from datetime import datetime

time_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

try:
    import serial
    import serial.tools.list_ports

    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

from src.models.paradigm import PARADIGM_REGISTRY
from src.workers.stimulus_worker import worker_entry, create_ipc_queues
from src.workers.calibration_worker import calibration_worker_entry
from src.ui.web_bridge import WebBridge

# Kinematic trigger params: (key, default, label). Rendered / serialized only
# when Execution Mode is Kinematic.
_KINEMATIC_PARAMS = [
    ("Trigger Duration (ms)", 2000.0, "Trigger Duration (ms):"),
    ("Trigger Dist (mm)", 5.0, "Trigger Dist (mm):"),
    ("Trigger Angle (°)", 10.0, "Trigger Angle (°):"),
    ("Trigger Speed (units/s)", 0.0, "Trigger Speed (units/s):"),
]


# ---- Pure-Python 3x3 matrix helpers (no numpy dependency) ----

def _det3(m):
    return (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )


def _inv3(m, det=None):
    if det is None:
        det = _det3(m)
    inv_det = 1.0 / det
    return [
        [
            (m[1][1] * m[2][2] - m[1][2] * m[2][1]) * inv_det,
            (m[0][2] * m[2][1] - m[0][1] * m[2][2]) * inv_det,
            (m[0][1] * m[1][2] - m[0][2] * m[1][1]) * inv_det,
        ],
        [
            (m[1][2] * m[2][0] - m[1][0] * m[2][2]) * inv_det,
            (m[0][0] * m[2][2] - m[0][2] * m[2][0]) * inv_det,
            (m[0][2] * m[1][0] - m[0][0] * m[1][2]) * inv_det,
        ],
        [
            (m[1][0] * m[2][1] - m[1][1] * m[2][0]) * inv_det,
            (m[0][1] * m[2][0] - m[0][0] * m[2][1]) * inv_det,
            (m[0][0] * m[1][1] - m[0][1] * m[1][0]) * inv_det,
        ],
    ]


def _matmul3(a, b):
    return [
        [a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j] for j in range(3)]
        for i in range(3)
    ]


def _transpose3(m):
    return [[m[j][i] for j in range(3)] for i in range(3)]


class CalibrationPanel:
    """Per-axis physical calibration panel with matrix decoupling."""

    def __init__(self, parent: ctk.CTkFrame):
        self._calib_active = False
        self._current_axis = None  # "X", "Y", "Z" while calibrating

        # Callbacks set by MasterDashboard
        self._cb_start_axis = None  # called with (axis, radius, rotations)
        self._cb_stop_axis = None  # called when user stops current axis
        self._cb_enter = None  # called when user clicks "Enter Calibration"
        self._cb_exit = None  # called when user clicks "Exit Calibration"
        self._cb_apply_matrix = None  # called with (matrix: list[list[float]])

        # Per-axis results: {"X": {"target_mm": float, "raw_vector": [int,int,int]}, ...}
        self.axis_results: Dict[str, dict] = {}

        self.frame = ctk.CTkScrollableFrame(parent, fg_color="transparent", width=400)
        self.frame.pack(fill="both", expand=True, padx=6, pady=(2, 0))

        header = ctk.CTkFrame(self.frame, fg_color="transparent")
        header.pack(fill="x", padx=6, pady=(2, 2))
        ctk.CTkLabel(
            header, text="Physical Calibration", font=("Segoe UI", 13, "bold")
        ).pack(side="left")

        # --- Geometry inputs ---
        geo_frame = ctk.CTkFrame(self.frame, fg_color="transparent")
        geo_frame.pack(fill="x", padx=6, pady=(0, 2))
        ctk.CTkLabel(geo_frame, text="Radius (mm):").pack(side="left")
        self.radius_var = ctk.StringVar(value="30.0")
        ctk.CTkEntry(geo_frame, textvariable=self.radius_var, width=70).pack(
            side="left", padx=(4, 0)
        )
        ctk.CTkLabel(geo_frame, text="Rotations:").pack(side="left", padx=(10, 0))
        self.rotations_var = ctk.StringVar(value="10.0")
        ctk.CTkEntry(geo_frame, textvariable=self.rotations_var, width=50).pack(
            side="left", padx=(4, 0)
        )

        # --- Polarity instruction ---
        ctk.CTkLabel(
            self.frame,
            text="Roll sphere strictly in the\nPOSITIVE direction for each axis.",
            text_color="orange",
            font=("Segoe UI", 10),
            justify="left",
        ).pack(fill="x", padx=6, pady=(0, 2))

        # --- Enter / Exit calibration ---
        self.toggle_btn = ctk.CTkButton(
            self.frame,
            text="Enter Calibration",
            fg_color="#1f6aa5",
            hover_color="#144870",
            command=self._on_toggle,
        )
        self.toggle_btn.pack(fill="x", padx=6, pady=(0, 2))

        # --- Axis buttons ---
        axis_row = ctk.CTkFrame(self.frame, fg_color="transparent")
        axis_row.pack(fill="x", padx=6, pady=(0, 2))
        axis_row.grid_columnconfigure((0, 1, 2), weight=1)
        self.btn_cal_x = ctk.CTkButton(
            axis_row,
            text="Calibrate X",
            fg_color="#1f6aa5",
            hover_color="#144870",
            command=lambda: self._on_start_axis("X"),
            state="disabled",
        )
        self.btn_cal_x.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.btn_cal_y = ctk.CTkButton(
            axis_row,
            text="Calibrate Y",
            fg_color="#1f6aa5",
            hover_color="#144870",
            command=lambda: self._on_start_axis("Y"),
            state="disabled",
        )
        self.btn_cal_y.grid(row=0, column=1, sticky="ew", padx=(0, 4))
        self.btn_cal_z = ctk.CTkButton(
            axis_row,
            text="Calibrate Z",
            fg_color="#1f6aa5",
            hover_color="#144870",
            command=lambda: self._on_start_axis("Z"),
            state="disabled",
        )
        self.btn_cal_z.grid(row=0, column=2, sticky="ew", padx=(0, 0))

        # --- Stop axis button ---
        self.stop_axis_btn = ctk.CTkButton(
            self.frame,
            text="Stop Axis",
            fg_color="red",
            hover_color="darkred",
            command=self._on_stop_axis,
            state="disabled",
        )
        self.stop_axis_btn.pack(fill="x", padx=6, pady=(0, 2))

        # --- Raw vector + Axis result labels (3x2 grid) ---
        self.results_frame = ctk.CTkFrame(self.frame, fg_color="transparent")
        self.results_frame.pack(fill="x", padx=6, pady=(0, 2))

        self.lbl_dx = ctk.CTkLabel(
            self.results_frame, text="Raw DX: 0", font=("Segoe UI", 12)
        )
        self.lbl_dx.grid(row=0, column=0, sticky="w", padx=(0, 20))
        self.lbl_dy = ctk.CTkLabel(
            self.results_frame, text="Raw DY: 0", font=("Segoe UI", 12)
        )
        self.lbl_dy.grid(row=1, column=0, sticky="w", padx=(0, 20))
        self.lbl_dz = ctk.CTkLabel(
            self.results_frame, text="Raw DZ: 0", font=("Segoe UI", 12)
        )
        self.lbl_dz.grid(row=2, column=0, sticky="w", padx=(0, 20))

        self.lbl_result_x = ctk.CTkLabel(
            self.results_frame, text="X: --", font=("Segoe UI", 11)
        )
        self.lbl_result_x.grid(row=0, column=1, sticky="w")
        self.lbl_result_y = ctk.CTkLabel(
            self.results_frame, text="Y: --", font=("Segoe UI", 11)
        )
        self.lbl_result_y.grid(row=1, column=1, sticky="w")
        self.lbl_result_z = ctk.CTkLabel(
            self.results_frame, text="Z: --", font=("Segoe UI", 11)
        )
        self.lbl_result_z.grid(row=2, column=1, sticky="w")

        # --- Apply Matrix ---
        self.apply_btn = ctk.CTkButton(
            self.frame,
            text="Apply Matrix",
            fg_color="green",
            hover_color="darkgreen",
            command=self._on_apply,
            state="disabled",
        )
        self.apply_btn.pack(fill="x", padx=6, pady=(2, 2))

        # --- Manual 3x3 Matrix Grid ---
        ctk.CTkLabel(
            self.frame,
            text="Manual Calibration Matrix",
            font=("Segoe UI", 11, "bold"),
        ).pack(fill="x", padx=6, pady=(2, 2))

        grid_frame = ctk.CTkFrame(self.frame, fg_color="transparent")
        grid_frame.pack(padx=6, pady=(0, 2))

        self._matrix_vars: List[List[ctk.StringVar]] = []
        for r in range(3):
            row_vars: List[ctk.StringVar] = []
            for c in range(3):
                var = ctk.StringVar(value="0.0000" if r != c else "1.0000")
                entry = ctk.CTkEntry(
                    grid_frame,
                    textvariable=var,
                    width=80,
                    font=("Segoe UI", 11),
                )
                entry.grid(row=r, column=c, padx=2, pady=2)
                row_vars.append(var)
            self._matrix_vars.append(row_vars)

        self.manual_save_btn = ctk.CTkButton(
            self.frame,
            text="Save/Update Manual Parameters",
            fg_color="#6b5b95",
            hover_color="#4a3f6b",
            command=self._on_manual_save,
        )
        self.manual_save_btn.pack(fill="x", padx=6, pady=(0, 2))

        self.status_lbl = ctk.CTkLabel(
            self.frame, text="Idle", text_color="gray", font=("Segoe UI", 11)
        )
        self.status_lbl.pack(padx=6, pady=(0, 2))

    # ---- public API for MasterDashboard ----

    def set_callbacks(
        self, enter=None, exit_=None, start_axis=None, stop_axis=None, apply_matrix=None
    ):
        self._cb_enter = enter
        self._cb_exit = exit_
        self._cb_start_axis = start_axis
        self._cb_stop_axis = stop_axis
        self._cb_apply_matrix = apply_matrix

    def set_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.toggle_btn.configure(state=state)
        self._update_axis_button_states()

    def handle_telemetry(self, data: dict):
        self.lbl_dx.configure(text=f"Raw DX: {data.get('raw_dx', 0)}")
        self.lbl_dy.configure(text=f"Raw DY: {data.get('raw_dy', 0)}")
        self.lbl_dz.configure(text=f"Raw DZ: {data.get('raw_dz', 0)}")

    def handle_axis_done(self, data: dict):
        """Process an axis_calib_done result from the worker."""
        axis = data.get("axis")
        if axis and axis in ("X", "Y", "Z"):
            self.axis_results[axis] = {
                "target_mm": data.get("target_mm", 0.0),
                "raw_vector": data.get("raw_vector", [0, 0, 0]),
            }
            rv = data["raw_vector"]
            lbl = getattr(self, f"lbl_result_{axis.lower()}")
            lbl.configure(
                text=f"{axis}: target={data['target_mm']:.1f}mm  "
                f"raw=[{rv[0]}, {rv[1]}, {rv[2]}]",
                text_color="lime",
            )
            self._current_axis = None
            self._update_axis_button_states()
            n = len(self.axis_results)
            self.status_lbl.configure(
                text=f"Axis {axis} done ({n}/3).", text_color="cyan"
            )
            if n == 3:
                self.apply_btn.configure(state="normal")
                self.status_lbl.configure(
                    text="All axes done. Review & Apply Matrix.", text_color="lime"
                )

    def on_calib_stopped(self, preserve_status: bool = False):
        """Called by dashboard when calibration process exits."""
        self._calib_active = False
        self._current_axis = None
        self.toggle_btn.configure(
            text="Enter Calibration", fg_color="#1f6aa5", hover_color="#144870"
        )
        self._update_axis_button_states()
        self.stop_axis_btn.configure(state="disabled")
        if not preserve_status:
            self.status_lbl.configure(
                text="Stopped. Apply or re-enter.", text_color="orange"
            )

    def reset(self):
        self._calib_active = False
        self._current_axis = None
        self.axis_results.clear()
        self.toggle_btn.configure(
            text="Enter Calibration",
            fg_color="#1f6aa5",
            hover_color="#144870",
            state="normal",
        )
        for axis in ("x", "y", "z"):
            getattr(self, f"btn_cal_{axis}").configure(state="disabled")
            getattr(self, f"lbl_result_{axis}").configure(
                text=f"{axis.upper()}: --", text_color="white"
            )
        self.stop_axis_btn.configure(state="disabled")
        self.apply_btn.configure(state="disabled")
        self.lbl_dx.configure(text="Raw DX: 0")
        self.lbl_dy.configure(text="Raw DY: 0")
        self.lbl_dz.configure(text="Raw DZ: 0")
        self.status_lbl.configure(text="Idle", text_color="gray")

    # ---- internal ----

    def _update_axis_button_states(self):
        base = (
            "normal"
            if self._calib_active and self._current_axis is None
            else "disabled"
        )
        for axis in ("x", "y", "z"):
            btn = getattr(self, f"btn_cal_{axis}")
            if self._calib_active and self._current_axis is None:
                btn.configure(state="normal")
            else:
                btn.configure(state="disabled")

    def _on_toggle(self):
        if not self._calib_active:
            self._calib_active = True
            self.axis_results.clear()
            self._current_axis = None
            self.toggle_btn.configure(
                text="Exit Calibration", fg_color="red", hover_color="darkred"
            )
            for axis in ("x", "y", "z"):
                getattr(self, f"lbl_result_{axis}").configure(
                    text=f"{axis.upper()}: --", text_color="white"
                )
            self.apply_btn.configure(state="disabled")
            self.lbl_dx.configure(text="Raw DX: 0")
            self.lbl_dy.configure(text="Raw DY: 0")
            self.lbl_dz.configure(text="Raw DZ: 0")
            self.status_lbl.configure(
                text="Calibration active. Pick an axis.", text_color="cyan"
            )
            self._update_axis_button_states()
            if self._cb_enter:
                self._cb_enter()
        else:
            self.status_lbl.configure(text="Exiting...", text_color="gray")
            if self._cb_exit:
                self._cb_exit()

    def _on_start_axis(self, axis: str):
        try:
            radius = float(self.radius_var.get())
            rotations = float(self.rotations_var.get())
        except ValueError:
            self.status_lbl.configure(text="Invalid radius/rotations", text_color="red")
            return
        self._current_axis = axis
        self.stop_axis_btn.configure(state="normal")
        self._update_axis_button_states()
        self.lbl_dx.configure(text="Raw DX: 0")
        self.lbl_dy.configure(text="Raw DY: 0")
        self.lbl_dz.configure(text="Raw DZ: 0")
        self.status_lbl.configure(text=f"Calibrating {axis} axis...", text_color="cyan")
        if self._cb_start_axis:
            self._cb_start_axis(axis, radius, rotations)

    def _on_stop_axis(self):
        if self._current_axis is None:
            return
        self.stop_axis_btn.configure(state="disabled")
        self.status_lbl.configure(
            text=f"Stopping {self._current_axis} axis...", text_color="gray"
        )
        if self._cb_stop_axis:
            self._cb_stop_axis()

    def update_matrix_display(self, matrix: List[List[float]]):
        """Populate the 3x3 entry grid with values from a matrix."""
        for r in range(3):
            for c in range(3):
                self._matrix_vars[r][c].set(f"{matrix[r][c]:.4f}")

    def _on_manual_save(self):
        """Read the 3x3 grid, validate, and fire the apply_matrix callback."""
        matrix: List[List[float]] = []
        try:
            for r in range(3):
                row: List[float] = []
                for c in range(3):
                    row.append(float(self._matrix_vars[r][c].get()))
                matrix.append(row)
        except ValueError:
            self.status_lbl.configure(
                text="Invalid matrix value — must be numeric", text_color="red"
            )
            return
        if self._cb_apply_matrix:
            self._cb_apply_matrix(matrix)
        self.status_lbl.configure(text="Manual matrix saved", text_color="lime")

    def _on_apply(self):
        if len(self.axis_results) < 3:
            self.status_lbl.configure(text="Need all 3 axes first", text_color="red")
            return
        matrix = self._compute_transformation_matrix()
        if matrix is None:
            self.status_lbl.configure(
                text="Singular Matrix: No valid pulses detected. Check sensors.",
                text_color="red",
            )
            return
        self.status_lbl.configure(text="Matrix applied.", text_color="lime")
        if self._cb_apply_matrix:
            self._cb_apply_matrix(matrix)

    def _compute_transformation_matrix(self):
        """Build the 3x3 decoupling matrix from per-axis calibration data.

        raw_matrix rows = raw vectors from each axis calibration.
        target_matrix = diag(target_mm per axis).
        transformation = inverse(raw_matrix) * target_matrix.
        """
        try:
            raw_rows = []
            targets = []
            for axis in ("X", "Y", "Z"):
                r = self.axis_results[axis]
                raw_rows.append([float(v) for v in r["raw_vector"]])
                targets.append(float(r["target_mm"]))

            det = _det3(raw_rows)
            if abs(det) < 1e-12:
                return None
            inv = _inv3(raw_rows, det)
            target_diag = [
                [targets[0], 0.0, 0.0],
                [0.0, targets[1], 0.0],
                [0.0, 0.0, targets[2]],
            ]
            return _transpose3(_matmul3(inv, target_diag))
        except Exception:
            return None


class MasterDashboard:
    # Max jump between consecutive trajectory points (mm) before the sample is
    # treated as an outlier and the trail is reset. Configurable.
    TRAIL_JUMP_MM = 50.0

    def __init__(self, root: ctk.CTk):
        self.root = root
        self.root.title("Cercus - Experiment Controller")
        self.root.geometry("1200x800")

        try:
            self.root.state("zoomed")
        except Exception:
            try:
                self.root.attributes("-zoomed", True)
            except Exception:
                pass

        try:
            self.root.tk.call("tk", "scaling", 1.0)
        except Exception:
            pass

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.worker_process: Optional[mp.Process] = None
        self.cmd_queue: Optional[mp.Queue] = None
        self.telemetry_queue: Optional[mp.Queue] = None

        self.calib_process: Optional[mp.Process] = None
        self.calib_cmd_queue: Optional[mp.Queue] = None
        self.calib_telemetry_queue: Optional[mp.Queue] = None

        # Web mirror process (pure-stdlib server, see src/core/web_telemetry.py)
        self.web_proc: Optional[mp.Process] = None
        self.web_state_q: Optional[mp.Queue] = None
        self._web_url: str = ""
        self._web_state_last_push: float = 0.0
        self._web_restart_at: float = 0.0
        self._status_text: str = ""
        self._closing: bool = False
        self._worker_terminal_status: Optional[str] = None
        self._worker_terminal_error: str = ""
        self._last_telemetry: Optional[Dict[str, Any]] = None
        self._last_ui_twin: Any = None
        self._calib_raw: Dict[str, Any] = {"dx": 0, "dy": 0, "dz": 0}

        self._param_vars: Dict[str, ctk.StringVar] = {}
        self._param_widgets: List[ctk.CTkBaseClass] = []
        self._trigger_interlocks: List[tuple] = []
        self._refreshing: bool = False
        self._exit_attempts: int = 0

        # Trajectory panel state
        self._trail_points: List[tuple] = []
        self._trail_last_phase: str = ""
        self._trail_min_x: float = 0.0
        self._trail_max_x: float = 0.0
        self._trail_min_y: float = 0.0
        self._trail_max_y: float = 0.0
        self._trail_last_angle: float = 0.0
        self._create_widgets()
        self._load_default_config()
        self.refresh_dynamic_parameters()
        self.root.after(16, self._poll_telemetry)
        self._start_web_server()

    # ------------------------------------------------------------------
    # Time Generator
    # ------------------------------------------------------------------
    def update_subject_with_current_time(self):
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")

        base_name = "cricket_001"
        new_subject = f"{base_name}_{current_time}"

        self.subject_var.set(new_subject)
    # ------------------------------------------------------------------
    # Serial port helper
    # ------------------------------------------------------------------
    def _get_serial_ports(self) -> List[str]:
        ports = []
        if HAS_SERIAL:
            ports = [p.device for p in serial.tools.list_ports.comports()]
        defaults = ["mock"]
        if sys.platform == "win32":
            defaults.append("COM3")
        else:
            defaults.append("/dev/ttyACM0")

        seen: set = set()
        result: List[str] = []
        for p in defaults + ports:
            if p not in seen:
                seen.add(p)
                result.append(p)
        return result

    # ------------------------------------------------------------------
    # Web mirror (real-time browser dashboard, see src/core/web_telemetry.py)
    # ------------------------------------------------------------------
    def _set_status(self, text: str, color: str = "white"):
        """Update the status label, keeping the web mirror URL visible."""
        self._status_text = text
        if self._web_url:
            text = f"{text}   |   Web: {self._web_url}"
        self.status_label.configure(text=text, text_color=color)

    def _start_web_server(self):
        try:
            from src.core.web_telemetry import (  # lazy: web deps are optional
                DEFAULT_PORT,
                find_free_port,
                local_web_url,
                web_telemetry_entry,
            )
        except ImportError:
            self._web_url = ""
            return  # fastapi/uvicorn not installed — mirror unavailable, controller unaffected
        if self.web_proc and self.web_proc.is_alive():
            return
        port = find_free_port(DEFAULT_PORT)
        if port == 0:
            self._set_status("Ready (web mirror unavailable: no free port)")
            return
        self._close_web_queue()
        self.web_state_q = mp.Queue(maxsize=8)
        self.web_proc = mp.Process(
            target=web_telemetry_entry,
            args=(self.web_state_q, port),
            daemon=True,
        )
        self.web_proc.start()
        self._web_url = local_web_url(port)
        # First start → "Ready"; mid-run restart → keep the active status text
        # and just refresh the (possibly changed) port on the label.
        color = (
            "white"
            if self._status_text in ("", "Ready")
            else self.status_label.cget("text_color")
        )
        self._set_status(self._status_text or "Ready", color)

    def _close_web_queue(self):
        q = self.web_state_q
        if q is not None:
            try:
                q.cancel_join_thread()
            except (OSError, ValueError):
                pass
            try:
                q.close()
            except (OSError, ValueError):
                pass
            self.web_state_q = None

    # NOTE: FullState serialization now lives in src/ui/web_bridge.py (WebBridge).
    # dashboard.py stays UI-only; _push_web_state calls WebBridge.build_full_state.

    def _put_web_state(self, state: dict):
        """Put a state frame, dropping the oldest on backpressure so the freshest
        always wins — never blocks, never raises."""
        q = self.web_state_q
        if q is None:
            return
        try:
            q.put_nowait(state)
        except queue.Full:
            try:
                q.get_nowait()  # drop one stale frame
            except queue.Empty:
                pass  # consumer drained it — a slot is free now
            except (ValueError, OSError):
                return
            try:
                q.put_nowait(state)
            except (queue.Full, ValueError, OSError):
                pass
        except (ValueError, OSError):
            pass

    def _push_web_state(self):
        """Push a FullState snapshot at up to 20 Hz."""
        if self._closing:
            return
        if not (self.web_proc and self.web_proc.is_alive()):
            # Mirror died mid-run — self-heal, throttled so a persistently
            # failing server can't spawn a process every poll tick.
            if self._web_url and time.monotonic() - self._web_restart_at > 2.0:
                self._web_restart_at = time.monotonic()
                self._start_web_server()
            return
        now = time.monotonic()
        if now - self._web_state_last_push < 0.05:
            return
        self._web_state_last_push = now
        self._put_web_state(
            WebBridge.build_full_state(self, self._last_telemetry)
        )

    # ------------------------------------------------------------------
    # Widget construction
    # ------------------------------------------------------------------
    def _create_widgets(self):
        main_frame = ctk.CTkFrame(self.root)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        main_frame.grid_rowconfigure(0, weight=1)  # top_row gets vertical stretch
        main_frame.grid_rowconfigure(1, weight=0)  # status_frame fixed height
        main_frame.grid_rowconfigure(2, weight=0)  # status_label fixed height
        main_frame.grid_rowconfigure(3, weight=0)  # ctrl_frame fixed height
        main_frame.grid_columnconfigure(0, weight=1)

        top_row = ctk.CTkFrame(main_frame, fg_color="transparent")
        top_row.grid(row=0, column=0, sticky="nsew", pady=(0, 5), padx=5)

        # --- Left: Config ---
        cfg_frame = ctk.CTkFrame(top_row)
        cfg_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))

        # Row 0: Paradigm + Pattern
        ctk.CTkLabel(cfg_frame, text="Paradigm:").grid(
            row=0, column=0, sticky="w", padx=10, pady=5
        )
        self.paradigm_var = ctk.StringVar(value=list(PARADIGM_REGISTRY.keys())[0])
        self.paradigm_var.trace_add("write", self.refresh_dynamic_parameters)
        ctk.CTkOptionMenu(
            cfg_frame,
            variable=self.paradigm_var,
            values=list(PARADIGM_REGISTRY.keys()),
            width=160,
        ).grid(row=0, column=1, sticky="w", padx=10, pady=5)

        ctk.CTkLabel(cfg_frame, text="Pattern:").grid(
            row=0, column=2, sticky="w", padx=10, pady=5
        )
        self.pattern_var = ctk.StringVar()
        self.pattern_menu = ctk.CTkOptionMenu(
            cfg_frame,
            variable=self.pattern_var,
            values=["—"],
            width=240,
        )
        self.pattern_menu.grid(row=0, column=3, sticky="w", padx=10, pady=5)

        # Row 1: Subject ID
        ctk.CTkLabel(cfg_frame, text="Subject ID:").grid(
            row=1, column=0, sticky="w", padx=10, pady=5
        )
        self.subject_var = ctk.StringVar(value=f"cricket_001_{time_stamp}")
        ctk.CTkEntry(cfg_frame, textvariable=self.subject_var).grid(
            row=1, column=1, sticky="w", padx=10, pady=5
        )
        # New Subject ID Button
        self.new_btn = ctk.CTkButton(cfg_frame, text="New Subject", command=self.update_subject_with_current_time)
        self.new_btn.grid(row=1, column=2, sticky="w", padx=10, pady=5)

        # Row 2: Session
        ctk.CTkLabel(cfg_frame, text="Start Session / Total:").grid(
            row=2, column=0, sticky="w", padx=10, pady=5
        )
        sess_frame = ctk.CTkFrame(cfg_frame, fg_color="transparent")
        sess_frame.grid(row=2, column=1, sticky="w", padx=10)
        self.session_start_var = ctk.StringVar(value="1")
        self.session_total_var = ctk.StringVar(value="2")
        ctk.CTkEntry(sess_frame, textvariable=self.session_start_var, width=60).pack(
            side="left"
        )
        self._session_sep_label = ctk.CTkLabel(sess_frame, text=" / ")
        self._session_sep_label.pack(side="left")
        self._session_total_entry = ctk.CTkEntry(
            sess_frame, textvariable=self.session_total_var, width=60
        )
        self._session_total_entry.pack(side="left")

        # Row 3: Viewing Distance / Screen Width
        ctk.CTkLabel(cfg_frame, text="Viewing Distance (cm):").grid(
            row=3, column=0, sticky="w", padx=10, pady=5
        )
        self.viewing_distance_var = ctk.StringVar(value="30.0")
        ctk.CTkEntry(cfg_frame, textvariable=self.viewing_distance_var).grid(
            row=3, column=1, sticky="w", padx=10, pady=5
        )
        ctk.CTkLabel(cfg_frame, text="Screen Width (cm):").grid(
            row=3, column=2, sticky="w", padx=10, pady=5
        )
        self.screen_width_cm_var = ctk.StringVar(value="53.0")
        ctk.CTkEntry(cfg_frame, textvariable=self.screen_width_cm_var).grid(
            row=3, column=3, sticky="w", padx=10, pady=5
        )

        # Row 4: Resolution
        ctk.CTkLabel(cfg_frame, text="Resolution (W,H):").grid(
            row=4, column=0, sticky="w", padx=10, pady=5
        )
        self.resolution_var = ctk.StringVar(value="3840,1080")
        ctk.CTkEntry(cfg_frame, textvariable=self.resolution_var).grid(
            row=4, column=1, sticky="w", padx=10, pady=5
        )

        # Row 5: ITI / ISI
        ctk.CTkLabel(cfg_frame, text="ITI Range (sec):").grid(
            row=5, column=0, sticky="w", padx=10, pady=5
        )
        self.iti_range_var = ctk.StringVar(value="60-90")
        ctk.CTkEntry(cfg_frame, textvariable=self.iti_range_var).grid(
            row=5, column=1, sticky="w", padx=10, pady=5
        )
        ctk.CTkLabel(cfg_frame, text="ISI Range (sec):").grid(
            row=5, column=2, sticky="w", padx=10, pady=5
        )
        self.isi_range_var = ctk.StringVar(value="300-300")
        ctk.CTkEntry(cfg_frame, textvariable=self.isi_range_var).grid(
            row=5, column=3, sticky="w", padx=10, pady=5
        )

        # Row 6: Serial / Screen
        ctk.CTkLabel(cfg_frame, text="Serial Port / Screen ID:").grid(
            row=6, column=0, sticky="w", padx=10, pady=5
        )
        hw_frame = ctk.CTkFrame(cfg_frame, fg_color="transparent")
        hw_frame.grid(row=6, column=1, columnspan=3, sticky="w", padx=10)
        serial_ports = self._get_serial_ports()
        self.serial_port_var = ctk.StringVar(
            value=serial_ports[0] if serial_ports else "mock"
        )
        self.screen_id_var = ctk.StringVar(value="1")
        ctk.CTkOptionMenu(
            hw_frame,
            variable=self.serial_port_var,
            values=serial_ports,
            width=110,
        ).pack(side="left", padx=(0, 5))
        ctk.CTkEntry(hw_frame, textvariable=self.screen_id_var, width=50).pack(
            side="left"
        )

        # Row 7: Debug Mode
        self.debug_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(cfg_frame, text="Debug Mode", variable=self.debug_var).grid(
            row=7, column=0, columnspan=2, sticky="w", padx=10, pady=10
        )

        # Row 8+: Dynamic paradigm parameters + kinematic trigger params
        self._param_frame = ctk.CTkScrollableFrame(cfg_frame)
        self._param_frame.grid(
            row=8, column=0, columnspan=4, sticky="nsew", padx=10, pady=(5, 10)
        )
        cfg_frame.grid_rowconfigure(8, weight=1)
        cfg_frame.grid_columnconfigure(4, weight=1)

        # --- Right: Calibration Panel ---
        right_panel = ctk.CTkFrame(top_row, width=400)
        right_panel.pack(side="right", fill="y", padx=(5, 0))

        # --- Calibration Panel ---
        self._calib_panel = CalibrationPanel(right_panel)
        self._calib_panel.set_callbacks(
            enter=self._start_calibration,
            exit_=self._stop_calibration,
            start_axis=self._start_axis_calibration,
            stop_axis=self._stop_axis_calibration,
            apply_matrix=self._apply_calibration_matrix,
        )

        # --- Status panel ---
        status_frame = ctk.CTkFrame(
            main_frame, fg_color=("gray90", "gray13"), corner_radius=10
        )
        status_frame.grid(row=1, column=0, sticky="ew", pady=10, padx=5)
        status_frame.grid_columnconfigure(0, weight=1)
        status_frame.grid_columnconfigure(1, weight=0)
        status_frame.grid_columnconfigure(2, weight=0)

        metrics_frame = ctk.CTkFrame(status_frame, fg_color="transparent")
        metrics_frame.grid(row=0, column=0, sticky="nsew", padx=20, pady=15)

        self.lbl_phase_val = self._add_metric_row(
            metrics_frame, "Phase:", 0, color="gray"
        )
        self.lbl_sess_val = self._add_metric_row(metrics_frame, "Session:", 1)
        self.lbl_trial_val = self._add_metric_row(metrics_frame, "Trial Progress:", 2)
        self.lbl_hw_val = self._add_metric_row(
            metrics_frame, "Hardware State:", 3, color="cyan"
        )
        self.lbl_hw_val.configure(justify="left")

        twin_frame = ctk.CTkFrame(status_frame, fg_color="transparent")
        twin_frame.grid(row=0, column=1, sticky="e", padx=20, pady=15)
        self.canvas = ctk.CTkCanvas(
            twin_frame,
            width=400,
            height=150,
            bg="black",
            highlightthickness=1,
            highlightbackground="#333333",
        )
        self.canvas.pack()

        # --- Trajectory panel (always visible) ---
        self._traj_frame = ctk.CTkFrame(status_frame, fg_color="transparent")
        self._traj_frame.grid(row=0, column=2, sticky="e", padx=(0, 20), pady=15)

        ctk.CTkLabel(
            self._traj_frame,
            text="Trajectory",
            font=("Segoe UI", 12, "bold"),
            text_color="gray70",
        ).pack(anchor="w")

        self._traj_canvas = ctk.CTkCanvas(
            self._traj_frame,
            width=150,
            height=150,
            bg="black",
            highlightthickness=1,
            highlightbackground="#333333",
        )
        self._traj_canvas.pack(pady=(2, 4))

        self._kin_row = ctk.CTkFrame(self._traj_frame, fg_color="transparent")
        self._kin_row.pack(fill="x")

        self._lbl_kin_angle = ctk.CTkLabel(
            self._kin_row,
            text="θ: —",
            font=("Consolas", 11),
            text_color="cyan",
            width=90,
        )
        self._lbl_kin_angle.pack(side="left")

        self._lbl_kin_turn = ctk.CTkLabel(
            self._kin_row,
            text="ω: —",
            font=("Consolas", 11),
            text_color="lime",
            width=90,
        )
        self._lbl_kin_turn.pack(side="left")

        self._lbl_kin_disp = ctk.CTkLabel(
            self._kin_row,
            text="D: —",
            font=("Consolas", 11),
            text_color="orange",
            width=90,
        )
        self._lbl_kin_disp.pack(side="left")

        # --- Status label ---
        self.status_label = ctk.CTkLabel(main_frame, text="Ready", fg_color="gray15")
        self.status_label.grid(row=2, column=0, sticky="ew", pady=(10, 0))

        # --- Control panel ---
        ctrl_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        ctrl_frame.grid(row=3, column=0, sticky="ew", pady=20)
        self.start_btn = ctk.CTkButton(
            ctrl_frame,
            text="Start Experiment",
            fg_color="green",
            hover_color="darkgreen",
            command=self.start_experiment,
            width=200,
            height=45,
            font=("Segoe UI", 16, "bold"),
        )
        self.start_btn.pack(side="left", expand=True, fill="x", padx=(0, 10))
        self.stop_btn = ctk.CTkButton(
            ctrl_frame,
            text="Stop Experiment",
            fg_color="red",
            hover_color="darkred",
            state="disabled",
            command=self.stop_experiment,
            width=200,
            height=45,
            font=("Segoe UI", 16, "bold"),
        )
        self.stop_btn.pack(side="right", expand=True, fill="x", padx=(10, 0))

    # ------------------------------------------------------------------
    # Metric row helper
    # ------------------------------------------------------------------
    def _add_metric_row(self, parent, label_text, row, color="white"):
        lbl = ctk.CTkLabel(
            parent,
            text=label_text,
            text_color=("gray35", "gray70"),
            font=("Segoe UI", 14),
        )
        lbl.grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
        val = ctk.CTkLabel(
            parent, text="—", text_color=color, font=("Segoe UI", 14, "bold")
        )
        val.grid(row=row, column=1, sticky="w", pady=4)
        return val

    # ------------------------------------------------------------------
    # Unified dynamic parameter refresh
    # ------------------------------------------------------------------
    def refresh_dynamic_parameters(self, *args):
        if self._refreshing:
            return
        self._refreshing = True
        try:
            self._do_refresh()
        finally:
            self._refreshing = False

    def _do_refresh(self):
        p_name = self.paradigm_var.get()
        p_cls = PARADIGM_REGISTRY.get(p_name)
        if p_cls is None:
            return

        patterns = p_cls.get_available_patterns()
        self.pattern_menu.configure(values=patterns)
        if patterns and self.pattern_var.get() not in patterns:
            self.pattern_var.set(patterns[0])

        # Preserve execution mode across refresh
        saved_exec_mode = None
        if "Execution Mode" in self._param_vars:
            saved_exec_mode = self._param_vars["Execution Mode"].get()

        # 1. Clear all existing dynamic widgets
        for w in self._param_widgets:
            w.destroy()
        self._param_widgets.clear()
        self._trigger_interlocks.clear()
        self._param_vars.clear()
        self._param_frame.grid_columnconfigure(2, weight=1)

        row = 0

        # 2. Render paradigm-specific parameters
        schema = p_cls.get_parameter_schema()
        if schema:
            for key, meta in schema.items():
                p_type = meta.get("type", "info")
                label_text = meta.get("label", key)

                if p_type == "info":
                    lbl = ctk.CTkLabel(
                        self._param_frame,
                        text=label_text,
                        text_color="gray60",
                        font=("Segoe UI", 11),
                    )
                    lbl.grid(
                        row=row, column=0, columnspan=2, sticky="w", padx=10, pady=4
                    )
                    self._param_widgets.append(lbl)
                    row += 1
                    continue

                lbl = ctk.CTkLabel(self._param_frame, text=f"{label_text}:")
                lbl.grid(row=row, column=0, sticky="w", padx=10, pady=4)
                self._param_widgets.append(lbl)

                default_val = str(meta.get("default", ""))
                var = ctk.StringVar(value=default_val)
                self._param_vars[key] = var

                if p_type == "choice":
                    w = ctk.CTkOptionMenu(
                        self._param_frame,
                        variable=var,
                        values=meta.get("choices", []),
                        width=160,
                    )
                elif p_type == "bool":
                    var = ctk.BooleanVar(value=bool(meta.get("default", False)))
                    self._param_vars[key] = var
                    w = ctk.CTkSwitch(self._param_frame, text="", variable=var)
                elif p_type == "filepath":
                    entry_frame = ctk.CTkFrame(
                        self._param_frame, fg_color="transparent"
                    )
                    entry_frame.grid(row=row, column=1, sticky="w", padx=10, pady=4)
                    w = ctk.CTkEntry(entry_frame, textvariable=var, width=120)
                    w.pack(side="left")
                    browse_btn = ctk.CTkButton(
                        entry_frame,
                        text="Browse",
                        width=60,
                        fg_color="gray30",
                        hover_color="gray40",
                        command=lambda v=var: self._browse_file(v),
                    )
                    browse_btn.pack(side="left", padx=(4, 0))
                    self._param_widgets.append(entry_frame)
                    row += 1
                    continue
                else:
                    w = ctk.CTkEntry(self._param_frame, textvariable=var, width=160)

                w.grid(row=row, column=1, sticky="w", padx=10, pady=4)
                self._param_widgets.append(w)
                row += 1

        # Restore execution mode selection
        if saved_exec_mode and "Execution Mode" in self._param_vars:
            self._param_vars["Execution Mode"].set(saved_exec_mode)

        # 3. Render kinematic trigger parameters (only when Execution Mode is Kinematic)
        exec_mode = self._param_vars.get("Execution Mode")
        if exec_mode and exec_mode.get() == "Kinematic":
            _CHECKBOX_KEYS = {
                "Trigger Dist (mm)",
                "Trigger Angle (°)",
                "Trigger Speed (units/s)",
            }

            for key, default, label_text in _KINEMATIC_PARAMS:
                lbl = ctk.CTkLabel(self._param_frame, text=label_text)
                lbl.grid(row=row, column=0, sticky="w", padx=10, pady=4)
                self._param_widgets.append(lbl)

                default_enabled = (key == "Trigger Speed (units/s)")

                var = ctk.StringVar(value=str(default))
                self._param_vars[key] = var
                entry = ctk.CTkEntry(
                    self._param_frame,
                    textvariable=var,
                    width=100,
                    state="normal" if (key not in _CHECKBOX_KEYS or default_enabled) else "disabled",
                )
                entry.grid(row=row, column=1, sticky="w", padx=10, pady=4)
                self._param_widgets.append(entry)

                if key in _CHECKBOX_KEYS:
                    en_key = f"{key} Enabled"
                    en_var = ctk.BooleanVar(value=default_enabled)
                    self._param_vars[en_key] = en_var
                    cb = ctk.CTkCheckBox(
                        self._param_frame,
                        text="",
                        variable=en_var,
                        width=20,
                        command=lambda v=en_var, inp=entry: self._on_trigger_toggle(
                            v, inp
                        ),
                    )
                    cb.grid(row=row, column=2, sticky="w", padx=(0, 10))
                    self._param_widgets.append(cb)
                    self._trigger_interlocks.append((en_var, entry))
                row += 1

        # 4. Bind execution mode trace (after all widgets are built)
        if "Execution Mode" in self._param_vars:
            self._param_vars["Execution Mode"].trace_add(
                "write", self._on_exec_mode_change
            )

    def _on_exec_mode_change(self, *args):
        if "Execution Mode" not in self._param_vars:
            self._session_sep_label.pack_forget()
            self._session_total_entry.pack_forget()
            return

        mode = self._param_vars["Execution Mode"].get()

        # Total Sessions visibility
        if mode == "Manual":
            self._session_sep_label.pack_forget()
            self._session_total_entry.pack_forget()
        else:
            if not self._session_sep_label.winfo_ismapped():
                self._session_sep_label.pack(side="left")
            if not self._session_total_entry.winfo_ismapped():
                self._session_total_entry.pack(side="left")

        # Full redraw — paradigm params preserved, kinematic params conditionally appended
        self.refresh_dynamic_parameters()

    def _on_trigger_toggle(self, cb_var: ctk.BooleanVar, entry: ctk.CTkEntry):
        entry.configure(state="normal" if cb_var.get() else "disabled")

    # ------------------------------------------------------------------
    # File browser helper
    # ------------------------------------------------------------------
    def _browse_file(self, var: ctk.StringVar):
        from tkinter import filedialog

        path = filedialog.askopenfilename()
        if path:
            var.set(path)

    # ------------------------------------------------------------------
    # Default config / helpers
    # ------------------------------------------------------------------
    def _load_default_config(self):
        self._calib_matrix = None
        try:
            root_dir = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            cfg_path = os.path.join(root_dir, "calibration_cfg.json")
            if os.path.isfile(cfg_path):
                with open(cfg_path, "r") as f:
                    data = json.load(f)
                # Support both old factor format and new matrix format
                if isinstance(data, list) and len(data) == 3:
                    self._calib_matrix = data
                    self._calib_panel.update_matrix_display(data)
                    self._calib_panel.status_lbl.configure(
                        text="Matrix loaded from file", text_color="lime"
                    )
                elif isinstance(data, dict):
                    # Legacy scalar factors — convert to diagonal matrix
                    self._calib_matrix = [
                        [data.get("dx", 1.0), 0.0, 0.0],
                        [0.0, data.get("dy", 1.0), 0.0],
                        [0.0, 0.0, data.get("dz", 1.0)],
                    ]
                    self._calib_panel.update_matrix_display(self._calib_matrix)
                    self._calib_panel.status_lbl.configure(
                        text="Legacy factors loaded (as diagonal matrix)",
                        text_color="lime",
                    )
        except Exception:
            pass

    def _safe_int(self, val_str: str, default: int) -> int:
        return int(val_str) if val_str.strip().isdigit() else default

    def _safe_float(self, val_str: str, default: float) -> float:
        try:
            return float(val_str)
        except ValueError:
            return default

    # ------------------------------------------------------------------
    # Config builder
    # ------------------------------------------------------------------
    def _build_config(self) -> Dict[str, Any]:
        root_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        out_dir = os.path.join(root_dir, "data")
        if not os.path.isdir(out_dir):
            os.makedirs(out_dir)

        p_name = self.paradigm_var.get()

        # Collect paradigm-specific parameters from dynamic form
        paradigm_params: Dict[str, Any] = {}
        p_cls = PARADIGM_REGISTRY.get(p_name)
        if p_cls:
            schema = p_cls.get_parameter_schema()
            for key, meta in schema.items():
                if key not in self._param_vars:
                    continue
                var = self._param_vars[key]
                p_type = meta.get("type", "info")
                if p_type == "int":
                    paradigm_params[key] = self._safe_int(
                        var.get(), meta.get("default", 0)
                    )
                elif p_type == "float":
                    paradigm_params[key] = self._safe_float(
                        var.get(), meta.get("default", 0.0)
                    )
                elif p_type == "bool":
                    paradigm_params[key] = var.get()
                elif p_type == "choice":
                    paradigm_params[key] = var.get()
                elif p_type == "string":
                    paradigm_params[key] = var.get()
                elif p_type == "range":
                    paradigm_params[key] = var.get()
                elif p_type == "filepath":
                    paradigm_params[key] = var.get()

        # Parse resolution string into width/height
        res_str = self.resolution_var.get().strip()
        res_parts = [p.strip() for p in res_str.split(",")]
        screen_w_px = (
            self._safe_int(res_parts[0], 3840) if len(res_parts) >= 1 else 3840
        )
        screen_h_px = (
            self._safe_int(res_parts[1], 1080) if len(res_parts) >= 2 else 1080
        )

        exec_mode = paradigm_params.get("Execution Mode", "Kinematic")
        total_sessions = (
            -1
            if exec_mode == "Manual"
            else self._safe_int(self.session_total_var.get(), 2)
        )

        cfg: Dict[str, Any] = {
            "Subject ID": self.subject_var.get().strip() or f"cricket_001_{time_stamp}",
            "Session Number": self._safe_int(self.session_start_var.get(), 1),
            "Total Sessions": total_sessions,
            "ITI Range (sec)": self.iti_range_var.get().strip() or "60-90",
            "ISI Range (sec)": self.isi_range_var.get().strip() or "300-300",
            "Experiment Pattern": self.pattern_var.get(),
            "Paradigm Class": p_name,
            "Serial Port": self.serial_port_var.get().strip() or "mock",
            "Stimulus Screen ID": self._safe_int(self.screen_id_var.get(), 1),
            "Debug Mode": self.debug_var.get(),
            "Viewing Distance (cm)": self._safe_float(
                self.viewing_distance_var.get(), 30.0
            ),
            "Screen Width (cm)": self._safe_float(self.screen_width_cm_var.get(), 53.0),
            "Screen Width (px)": screen_w_px,
            "Screen Height (px)": screen_h_px,
            "Sync Topology": [],
            "_output_dir": out_dir,
        }
        cfg.update(paradigm_params)

        # Kinematic trigger params (present only when Execution Mode is Kinematic)
        pv = self._param_vars
        if "Trigger Duration (ms)" in pv:
            cfg["Trigger Duration (ms)"] = self._safe_float(
                pv["Trigger Duration (ms)"].get(), 2000.0
            )
            cfg["Trigger Dist (mm)"] = self._safe_float(
                pv["Trigger Dist (mm)"].get(), 5.0
            )
            cfg["Trigger Dist Enabled"] = bool(pv["Trigger Dist (mm) Enabled"].get())
            cfg["Trigger Angle (°)"] = self._safe_float(
                pv["Trigger Angle (°)"].get(), 10.0
            )
            cfg["Trigger Angle Enabled"] = bool(pv["Trigger Angle (°) Enabled"].get())
            cfg["Trigger Speed (units/s)"] = self._safe_float(
                pv["Trigger Speed (units/s)"].get(), 0.0
            )
            cfg["Trigger Speed Enabled"] = bool(pv["Trigger Speed (units/s) Enabled"].get())

        return cfg

    # ------------------------------------------------------------------
    # Experiment lifecycle
    # ------------------------------------------------------------------
    def _close_queues(self):
        for q_name in ("cmd_queue", "telemetry_queue"):
            q = getattr(self, q_name, None)
            if q is not None:
                try:
                    q.cancel_join_thread()
                except (OSError, ValueError):
                    pass
                self._drain_queue_async(q)
                try:
                    q.close()
                except (OSError, ValueError):
                    pass
                setattr(self, q_name, None)

    def _close_calib_queues(self):
        for q_name in ("calib_cmd_queue", "calib_telemetry_queue"):
            q = getattr(self, q_name, None)
            if q is not None:
                try:
                    q.cancel_join_thread()
                except (OSError, ValueError):
                    pass
                self._drain_queue_async(q)
                try:
                    q.close()
                except (OSError, ValueError):
                    pass
                setattr(self, q_name, None)

    @staticmethod
    def _drain_queue_async(q: mp.Queue):
        """Drain a queue in a daemon thread to avoid blocking the GUI."""

        def _drain():
            empty_streak = 0
            while True:
                try:
                    q.get(timeout=0.05)
                    empty_streak = 0
                except queue.Empty:
                    empty_streak += 1
                    if empty_streak > 50:
                        break
                    time.sleep(0.01)
                except (ValueError, OSError, EOFError, BrokenPipeError):
                    break

        t = threading.Thread(target=_drain, daemon=True)
        t.start()

    def _kill_worker(self, proc: Optional[mp.Process], timeout: float = 4.0):
        if proc is None:
            return
        # Cancel join threads on all queues before terminating to prevent deadlock
        for q_attr in (
            "cmd_queue",
            "telemetry_queue",
            "calib_cmd_queue",
            "calib_telemetry_queue",
        ):
            q = getattr(self, q_attr, None)
            if q is not None:
                try:
                    q.cancel_join_thread()
                except Exception:
                    pass
        proc.join(timeout=timeout)
        if proc.is_alive():
            proc.terminate()

    # ---- Calibration lifecycle ----

    def _start_calibration(self):
        """Kill stimulus worker, then launch CalibrationWorker."""
        if self.calib_process and self.calib_process.is_alive():
            return
        self._worker_terminal_status = None
        self._worker_terminal_error = ""

        # Shut down stimulus worker if running; always clear stale reference
        # to prevent _poll_telemetry from detecting a dead worker and calling
        # _reset_ui() which would immediately exit calibration mode.
        if self.worker_process:
            if self.worker_process.is_alive():
                if self.cmd_queue:
                    try:
                        self.cmd_queue.put_nowait({"action": "POISON_PILL"})
                    except queue.Full:
                        pass
                self._close_queues()
                self._kill_worker(self.worker_process)
            self.worker_process = None

        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="disabled")
        self._calib_panel.set_enabled(True)
        self._set_status("Calibration mode", "cyan")

        self._close_calib_queues()
        self.calib_cmd_queue, self.calib_telemetry_queue = create_ipc_queues()

        cfg = {"Serial Port": self.serial_port_var.get().strip() or "mock"}
        self.calib_process = mp.Process(
            target=calibration_worker_entry,
            args=(cfg, self.calib_cmd_queue, self.calib_telemetry_queue),
        )
        self.calib_process.start()

    def _start_axis_calibration(self, axis: str, radius_mm: float, rotations: float):
        """Send START_CALIBRATION command for a specific axis."""
        if self.calib_cmd_queue:
            try:
                self.calib_cmd_queue.put_nowait(
                    {
                        "action": "START_CALIBRATION",
                        "axis": axis,
                        "radius_mm": radius_mm,
                        "rotations": rotations,
                    }
                )
            except queue.Full:
                pass

    def _stop_axis_calibration(self):
        """Send STOP_AXIS command to the calibration worker."""
        if self.calib_cmd_queue:
            try:
                self.calib_cmd_queue.put_nowait({"action": "STOP_AXIS"})
            except queue.Full:
                pass

    def _stop_calibration(self):
        """Send POISON_PILL to CalibrationWorker."""
        if self.calib_cmd_queue:
            try:
                self.calib_cmd_queue.put_nowait({"action": "POISON_PILL"})
            except queue.Full:
                pass

    def _apply_calibration_matrix(self, matrix: list):
        """Save the matrix, stop the calib worker, inject into hardware."""
        self._stop_calibration()

        self._calib_matrix = matrix
        try:
            root_dir = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            cfg_path = os.path.join(root_dir, "calibration_cfg.json")
            with open(cfg_path, "w") as f:
                json.dump(matrix, f, indent=2)
        except Exception:
            pass
        self._calib_panel.update_matrix_display(matrix)
        self._calib_just_applied = True
        self._set_status("Calibration matrix applied & saved", "lime")

    def _on_calib_process_exit(self):
        """Clean up after calibration worker exits."""
        self._close_calib_queues()
        self._kill_worker(self.calib_process)
        self.calib_process = None

        just_applied = getattr(self, "_calib_just_applied", False)

        self._calib_panel.on_calib_stopped(preserve_status=just_applied)
        self.start_btn.configure(state="normal")

        if not just_applied:
            self._set_status("Ready", "white")
        else:
            self._calib_just_applied = False

    # ---- Experiment lifecycle ----

    def start_experiment(self):
        if self.worker_process and self.worker_process.is_alive():
            return
        self._start_web_server()  # ensure the mirror is up for this run
        self._worker_terminal_status = None
        self._worker_terminal_error = ""

        self._calib_panel.set_enabled(False)
        self._close_queues()
        self.cmd_queue, self.telemetry_queue = create_ipc_queues()

        cfg = self._build_config()
        # Inject calibration matrix if available
        if hasattr(self, "_calib_matrix") and self._calib_matrix:
            cfg["calib_matrix"] = self._calib_matrix

        self.worker_process = mp.Process(
            target=worker_entry, args=(cfg, self.cmd_queue, self.telemetry_queue)
        )
        self.worker_process.start()

        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._set_status("Running...", "cyan")

    def stop_experiment(self):
        if self.cmd_queue:
            try:
                self.cmd_queue.put_nowait({"action": "POISON_PILL"})
                self.stop_btn.configure(state="disabled")
                self._set_status("Stopping...", "orange")
            except queue.Full:
                pass

    # ------------------------------------------------------------------
    # Telemetry polling
    # ------------------------------------------------------------------
    def _poll_telemetry(self):
        if self.telemetry_queue:
            # Drain queue in a single pass, keeping only the latest frame per category
            latest_telemetry = None
            terminal_event = None

            while not self.telemetry_queue.empty():
                try:
                    data = self.telemetry_queue.get_nowait()
                    action = data.get("action")

                    if action == "telemetry":
                        latest_telemetry = data
                    elif action in ["worker_done", "worker_abort", "worker_error"]:
                        terminal_event = data
                except (queue.Empty, ValueError, OSError, EOFError):
                    break

            if latest_telemetry:
                self._update_telemetry_ui(latest_telemetry)
                self._draw_twin(latest_telemetry)

            if terminal_event:
                action = terminal_event.get("action")
                self._worker_terminal_status = action
                self._worker_terminal_error = terminal_event.get("error", "")

                self.stop_btn.configure(state="disabled")
                if action == "worker_done":
                    self._set_status("Experiment completed. Cleaning up...", "white")
                elif action == "worker_abort":
                    self._set_status("Experiment aborted. Cleaning up...", "orange")
                elif action == "worker_error":
                    self._set_status(
                        f"Error: {self._worker_terminal_error}", "red"
                    )

        if self.worker_process and not self.worker_process.is_alive():
            # Skip dead-worker cleanup while calibration is active — the stale
            # reference must not trigger _reset_ui() which would exit calibration.
            if self._calib_panel._calib_active:
                self._close_queues()
                self._kill_worker(self.worker_process)
                self.worker_process = None
            else:
                # Salvage terminal signals that may be buried deep in the queue
                if self.telemetry_queue:
                    while not self.telemetry_queue.empty():
                        try:
                            frame = self.telemetry_queue.get_nowait()
                            if frame.get("action") in [
                                "worker_done",
                                "worker_abort",
                                "worker_error",
                            ]:
                                self._worker_terminal_status = frame.get("action")
                                if "error" in frame:
                                    self._worker_terminal_error = frame["error"]
                        except (queue.Empty, ValueError, OSError, EOFError):
                            break

                status = self._worker_terminal_status
                color, text = "white", "Ready"

                if status == "worker_done":
                    text, color = "Experiment completed", "lime"
                elif status == "worker_abort":
                    text, color = "Experiment aborted", "orange"
                elif status == "worker_error":
                    text, color = (
                        f"Error: {self._worker_terminal_error or 'Unknown'}",
                        "red",
                    )
                elif self.start_btn.cget("state") == "disabled" and not self.calib_process:
                    text, color = "Worker disconnected", "gray"
                else:
                    text, color = None, None

                if text:
                    self._reset_ui(text, color)
                # Keep _worker_terminal_status so the web mirror can show the
                # DONE/ABORT/ERROR badge; it resets when the next experiment starts.

        # --- Calibration telemetry ---
        if self.calib_telemetry_queue:
            for _ in range(50):
                try:
                    data = self.calib_telemetry_queue.get_nowait()
                    action = data.get("action")
                    if action == "calibration_telemetry":
                        self._calib_raw = {
                            "dx": data.get("raw_dx", 0),
                            "dy": data.get("raw_dy", 0),
                            "dz": data.get("raw_dz", 0),
                        }
                        self._calib_panel.handle_telemetry(data)
                    elif action == "axis_calib_done":
                        self._calib_panel.handle_axis_done(data)
                    elif action in ("calibration_done", "calibration_error"):
                        self._on_calib_process_exit()
                        break
                except (queue.Empty, ValueError, OSError, EOFError):
                    break

        if self.calib_process and not self.calib_process.is_alive():
            self._on_calib_process_exit()

        self._push_web_state()

        self.root.after(16, self._poll_telemetry)

    def _update_telemetry_ui(self, data: dict):
        self._last_telemetry = data
        self._last_ui_twin = data.get("ui_twin")
        phase = str(data.get("phase", "—"))
        sess = str(data.get("session_num", "—"))
        t_idx = str(data.get("trial_idx", "—"))
        tot = str(data.get("total_trials", "—"))

        ui_color = data.get("ui_color", "cyan")
        ui_metrics = data.get("ui_metrics", {})

        self.lbl_phase_val.configure(text=phase, text_color=ui_color)
        self.lbl_sess_val.configure(text=sess)
        self.lbl_trial_val.configure(text=f"{t_idx} / {tot}")

        hw_str = (
            "\n".join(f"{k}: {v}" for k, v in ui_metrics.items())
            if ui_metrics
            else "Active"
        )
        self.lbl_hw_val.configure(text=hw_str, text_color="cyan")

        # Trajectory panel — always active
        self._update_trajectory(data, ui_metrics)

    def _draw_twin(self, frame: Dict[str, Any]):
        self.canvas.delete("all")
        twin_cfg = frame.get("ui_twin")
        if not twin_cfg:
            return

        # New protocol: list of standard Canvas draw commands
        if isinstance(twin_cfg, list):
            for item in twin_cfg:
                cmd_name = item.get("cmd")
                if not cmd_name:
                    continue
                draw_fn = getattr(self.canvas, cmd_name, None)
                if draw_fn is None:
                    continue
                args = item.get("args", [])
                kwargs = item.get("kwargs", {})
                try:
                    draw_fn(*args, **kwargs)
                except Exception:
                    pass
            return

        # Legacy protocol: dict with "side" and "radius_ratio"
        side = twin_cfg.get("side", "left")
        radius_ratio = twin_cfg.get("radius_ratio", 0.0)
        radius_canvas = min(100, max(2, radius_ratio * 100))
        centre_y = 75

        if side in ["left", "both", "—"]:
            self.canvas.create_oval(
                100 - radius_canvas,
                centre_y - radius_canvas,
                100 + radius_canvas,
                centre_y + radius_canvas,
                outline="white",
                width=1,
            )
        if side in ["right", "both", "—"]:
            self.canvas.create_oval(
                300 - radius_canvas,
                centre_y - radius_canvas,
                300 + radius_canvas,
                centre_y + radius_canvas,
                outline="white",
                width=1,
            )
        self.canvas.create_line(200, 0, 200, 150, fill="#333333", dash=(4, 2))

    # ------------------------------------------------------------------
    # Trajectory panel
    # ------------------------------------------------------------------
    def _update_trajectory(self, data: dict, ui_metrics: dict):
        raw_phase = str(data.get("phase", ""))

        base_phase = raw_phase
        if raw_phase.startswith("ITI"):
            base_phase = "ITI"
        elif raw_phase.startswith("ISI"):
            base_phase = "ISI"
        elif raw_phase.startswith("Kinematic"):
            base_phase = "Kinematic"

        if base_phase != self._trail_last_phase:
            self._reset_trajectory()
            self._trail_last_phase = base_phase

        px = ui_metrics.get("pos_x")
        py = ui_metrics.get("pos_y")
        if px is not None and py is not None:
            new_pt = (float(px), float(py))
            # Distance gate — a single glitchy point far from the previous one
            # must not produce a line that shoots off-screen. Drop the sample
            # and restart the trail instead of connecting to the outlier.
            if self._trail_points:
                lx, ly = self._trail_points[-1]
                if math.hypot(new_pt[0] - lx, new_pt[1] - ly) > self.TRAIL_JUMP_MM:
                    self._reset_trajectory()
                    return  # discard the outlier point
            self._trail_points.append(new_pt)
            self._trail_points = self._trail_points[-1000:]
            # Recompute the bounding box from the (possibly truncated) trail —
            # incremental min/max goes stale once extreme points fall off the
            # window, which would leave the plot incorrectly zoomed out.
            self._trail_min_x = min(p[0] for p in self._trail_points)
            self._trail_max_x = max(p[0] for p in self._trail_points)
            self._trail_min_y = min(p[1] for p in self._trail_points)
            self._trail_max_y = max(p[1] for p in self._trail_points)
            self._draw_trajectory()

        try:
            self._trail_last_angle = float(ui_metrics.get('k_angle', 0.0))
        except (ValueError, TypeError):
            self._trail_last_angle = 0.0
        self._lbl_kin_angle.configure(text=f"θ: {ui_metrics.get('k_angle', '—')}")
        self._lbl_kin_turn.configure(text=f"ω: {ui_metrics.get('k_turn_speed', '—')}")
        self._lbl_kin_disp.configure(text=f"D: {ui_metrics.get('k_disp', '—')}")

    def _draw_trajectory(self):
        canvas = self._traj_canvas
        canvas.delete("all")

        W, H = 150, 150
        PAD = 10

        n = len(self._trail_points)
        if n < 2:
            return

        # Bounding box with 10% margin
        margin_x = max((self._trail_max_x - self._trail_min_x) * 0.1, 0.5)
        margin_y = max((self._trail_max_y - self._trail_min_y) * 0.1, 0.5)
        x0 = self._trail_min_x - margin_x
        x1 = self._trail_max_x + margin_x
        y0 = self._trail_min_y - margin_y
        y1 = self._trail_max_y + margin_y

        # Uniform scale — floor at 10.0 keeps single-point / zero-displacement
        # centered without division-by-zero or extreme zoom
        usable_w = W - 2 * PAD
        usable_h = H - 2 * PAD
        range_x = max(x1 - x0, 10.0)
        range_y = max(y1 - y0, 10.0)
        scale_x = usable_w / range_x
        scale_y = usable_h / range_y
        scale = scale_x if scale_x < scale_y else scale_y

        cx_phys = (x0 + x1) * 0.5
        cy_phys = (y0 + y1) * 0.5
        cx_canvas = W * 0.5
        cy_canvas = H * 0.5

        # Build flat coordinate list [x0,y0, x1,y1, ...] for a single
        # create_line call — O(1) Tk widget creation instead of O(n) loop
        # Trajectory draw
        flat = []
        for px, py in self._trail_points:
            flat.append(cx_canvas + (px - cx_phys) * scale)
            flat.append(cy_canvas - (py - cy_phys) * scale)
        canvas.create_line(*flat, fill="cyan", width=2)

        # Current position Arrow
        lx = flat[-2]
        ly = flat[-1]

        rad = math.radians(getattr(self, '_trail_last_angle', 0.0))

        # 物理坐标系下的向量 (Forward: dy=1, Right: dx=1)
        phys_dir_x = -math.sin(rad)
        phys_dir_y = math.cos(rad)
        phys_right_x = math.cos(rad)
        phys_right_y = math.sin(rad)

        # 映射到 Canvas UI 坐标系 (X轴反向，Y轴反向)
        canvas_dir_x = phys_dir_x
        canvas_dir_y = -phys_dir_y
        canvas_right_x = phys_right_x
        canvas_right_y = -phys_right_y
        # 箭头几何参数 (像素)
        L = 6  # 尖端长度
        B = 5  # 尾部向后长度
        W = 4  # 尾部侧向半宽
        N = 2  # 尾部凹槽向后长度

        tip_x = lx + canvas_dir_x * L
        tip_y = ly + canvas_dir_y * L

        br_x = lx - canvas_dir_x * B + canvas_right_x * W
        br_y = ly - canvas_dir_y * B + canvas_right_y * W

        notch_x = lx - canvas_dir_x * N
        notch_y = ly - canvas_dir_y * N

        bl_x = lx - canvas_dir_x * B - canvas_right_x * W
        bl_y = ly - canvas_dir_y * B - canvas_right_y * W

        canvas.create_polygon(
            tip_x, tip_y, br_x, br_y, notch_x, notch_y, bl_x, bl_y,
            fill="white", outline="cyan", width=1
        )

    def _reset_trajectory(self):
        self._trail_points = []
        self._trail_last_phase = ""
        self._trail_min_x = 0.0
        self._trail_max_x = 0.0
        self._trail_min_y = 0.0
        self._trail_max_y = 0.0
        self._trail_last_angle = 0.0
        self._traj_canvas.delete("all")
        self._lbl_kin_angle.configure(text="θ: —")
        self._lbl_kin_turn.configure(text="ω: —")
        self._lbl_kin_disp.configure(text="D: —")

    def _reset_ui(self, status: str, color: str):
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self._set_status(status, color)

        # Clear the last worker frame so the web mirror returns to IDLE instead
        # of showing the final phase/twin of the finished experiment forever.
        self._last_telemetry = None
        self._last_ui_twin = None

        self.lbl_phase_val.configure(text="IDLE", text_color="gray")
        self.lbl_hw_val.configure(text="Disconnected", text_color="gray")
        self.canvas.delete("all")
        self._reset_trajectory()
        self._calib_panel.reset()
        self._calib_panel.set_enabled(True)

        if self.worker_process:
            self._close_queues()
            self._kill_worker(self.worker_process)
            self.worker_process = None

    def on_closing(self):
        """Gracefully signal all workers and poll for exit."""
        self._exit_attempts = 0
        if self.calib_cmd_queue:
            try:
                self.calib_cmd_queue.put_nowait({"action": "POISON_PILL"})
            except (queue.Full, OSError):
                pass
        if self.cmd_queue:
            try:
                self.cmd_queue.put_nowait({"action": "POISON_PILL"})
            except (queue.Full, OSError):
                pass
        # Stop new state pushes so the shutdown sentinel can never be dropped.
        self._closing = True
        self._put_web_state({"__shutdown__": True})
        self.root.after(100, self._check_safe_exit)

    def _check_safe_exit(self):
        """Poll until both processes exit, then destroy; force after 2s."""
        self._exit_attempts += 1
        worker_alive = (
            self.worker_process is not None and self.worker_process.is_alive()
        )
        calib_alive = self.calib_process is not None and self.calib_process.is_alive()
        web_alive = self.web_proc is not None and self.web_proc.is_alive()

        if not worker_alive and not calib_alive and not web_alive:
            self._close_queues()
            self._close_calib_queues()
            self._close_web_queue()
            self.root.destroy()
        elif self._exit_attempts >= 20:
            if self.worker_process and self.worker_process.is_alive():
                self._kill_worker(self.worker_process)
            if self.calib_process and self.calib_process.is_alive():
                self._kill_worker(self.calib_process)
            if self.web_proc and self.web_proc.is_alive():
                self._kill_worker(self.web_proc)
            self._close_queues()
            self._close_calib_queues()
            self._close_web_queue()
            self.root.destroy()
        else:
            self.root.after(100, self._check_safe_exit)


def main():
    mp.set_start_method("spawn", force=True)
    root = ctk.CTk()
    app = MasterDashboard(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
