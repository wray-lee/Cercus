"""Single source of truth for serializing the dashboard state to the web mirror.

Duck-types against ``MasterDashboard`` — no GUI-toolkit import and no import
of ``src.ui.dashboard`` — so this module can be imported standalone and unit-
tested. The returned ``build_full_state()`` dict is the cross-process contract
consumed by ``src/core/web_telemetry.py`` and broadcast over ``/ws/full_state``.
"""

from typing import Any, Dict

from src.models.paradigm import PARADIGM_REGISTRY


def _safe_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def _safe_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


class WebBridge:
    """Stateless collection of state-extraction helpers (mirror is read-only)."""

    @staticmethod
    def get_paradigm_schema(dash) -> Dict[str, Dict[str, Any]]:
        p_cls = PARADIGM_REGISTRY.get(dash.paradigm_var.get())
        return p_cls.get_parameter_schema() if p_cls else {}

    @staticmethod
    def get_paradigm_params_live(dash) -> Dict[str, Any]:
        """Live StringVar/BooleanVar values, including the kinematic trigger
        params and the info-note text (info params have no widget)."""
        live = {k: v.get() for k, v in dash._param_vars.items()}
        for key, meta in WebBridge.get_paradigm_schema(dash).items():
            if meta.get("type") == "info" and key not in live:
                live[key] = meta.get("label", key)
        return live

    @staticmethod
    def get_config_snapshot(dash) -> dict:
        return dash._build_config()

    @staticmethod
    def get_calibration_state(dash) -> dict:
        cal = dash._calib_panel
        matrix = []
        for r in range(3):
            row = []
            for c in range(3):
                try:
                    row.append(float(cal._matrix_vars[r][c].get()))
                except (ValueError, IndexError):
                    row.append(0.0)
            matrix.append(row)
        return {
            "is_active": cal._calib_active,
            "current_axis": cal._current_axis,
            "Radius": _safe_float(cal.radius_var.get(), 30.0),
            "Rotations": _safe_float(cal.rotations_var.get(), 10.0),
            "raw_dx": dash._calib_raw.get("dx", 0),
            "raw_dy": dash._calib_raw.get("dy", 0),
            "raw_dz": dash._calib_raw.get("dz", 0),
            "axis_results": dict(cal.axis_results),
            "matrix": matrix,
            "status": cal.status_lbl.cget("text"),
            "status_color": cal.status_lbl.cget("text_color"),
        }

    @staticmethod
    def get_live_state(dash, telemetry) -> dict:
        tel = telemetry or {}
        ui_metrics = tel.get("ui_metrics", {})
        terminal = dash._worker_terminal_status
        worker_alive = dash.worker_process is not None and dash.worker_process.is_alive()
        if worker_alive:
            worker_status = "running"
        elif terminal:
            worker_status = terminal
        else:
            worker_status = "idle"

        exec_mode = dash._param_vars.get("Execution Mode")
        exec_mode = exec_mode.get() if exec_mode else "Auto"
        total_sessions = (
            _safe_int(dash.session_total_var.get(), 2)
            if exec_mode != "Manual"
            else None
        )

        return {
            "phase": tel.get("phase", "IDLE"),
            "ui_color": tel.get("ui_color", "gray"),
            "session_num": tel.get("session_num", "—"),
            "trial_idx": tel.get("trial_idx", "—"),
            "total_trials": tel.get("total_trials", "—"),
            "total_sessions": total_sessions,
            "hardware_state": ui_metrics,
            "status_label": dash._status_text,
            "status_color": dash.status_label.cget("text_color"),
            "controls": {
                "start": dash.start_btn.cget("state"),
                "stop": dash.stop_btn.cget("state"),
            },
            "worker_status": worker_status,
            "worker_error": dash._worker_terminal_error,
        }

    @staticmethod
    def get_visual_state(dash, telemetry) -> dict:
        ui_metrics = (telemetry or {}).get("ui_metrics", {})
        return {
            "ui_twin": dash._last_ui_twin,
            "trajectory": {
                "trail_points": dash._trail_points[-1000:],
                "min_x": dash._trail_min_x,
                "max_x": dash._trail_max_x,
                "min_y": dash._trail_min_y,
                "max_y": dash._trail_max_y,
                "angle": dash._trail_last_angle,
                "k_angle": ui_metrics.get("k_angle"),
                "k_turn_speed": ui_metrics.get("k_turn_speed"),
                "k_disp": ui_metrics.get("k_disp"),
            },
        }

    @staticmethod
    def build_full_state(dash, telemetry=None) -> dict:
        live = WebBridge.get_live_state(dash, telemetry)
        cal_active = bool(dash._calib_panel._calib_active)
        return {
            "config": WebBridge.get_config_snapshot(dash),
            "paradigm_params_live": WebBridge.get_paradigm_params_live(dash),
            "paradigm_schema": WebBridge.get_paradigm_schema(dash),
            "calibration": WebBridge.get_calibration_state(dash),
            "live": live,
            "visual": WebBridge.get_visual_state(dash, telemetry),
            "meta": {"running": live["worker_status"] == "running" or cal_active},
        }
