"""ExperimentController — worker lifecycle, config build, queue polling.

Pure Python, no UI framework dependency.  Extracted from MasterDashboard.
"""
import json
import logging
import math
import multiprocessing as mp
import os
import queue
import threading
import time
from typing import Any, Dict, List, Optional

from src.models.paradigm import PARADIGM_REGISTRY

log = logging.getLogger(__name__)


def _safe_int(val, default: int) -> int:
    if isinstance(val, bool):
        return default
    if isinstance(val, (int, float)):
        try:
            return int(val)
        except (ValueError, OverflowError):
            return default
    try:
        v = val.strip()
        return int(v) if v.lstrip('-').isdigit() else default
    except (AttributeError, ValueError):
        return default


def _safe_float(val, default: float) -> float:
    if isinstance(val, bool):
        return default
    if isinstance(val, (int, float)):
        try:
            res = float(val)
            return default if (math.isnan(res) or math.isinf(res)) else res
        except (ValueError, OverflowError):
            return default
    try:
        res = float(val.strip())
        return default if (math.isnan(res) or math.isinf(res)) else res
    except (AttributeError, ValueError, TypeError):
        return default


def _coerce_params(
    params: Dict[str, Any], schema: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """Coerce and clamp form values against their declared schema types.

    A cleared numeric field arrives as ``None``; without this the worker would
    receive it verbatim and die on ``int(None)``.  Values outside a declared
    ``min``/``max`` are clamped rather than rejected, matching the widget's own
    blur-time behaviour.  Keys absent from the schema (e.g. companion enable
    flags) pass through untouched.
    """
    out: Dict[str, Any] = {}
    for key, val in params.items():
        meta = schema.get(key)
        if meta is None:
            out[key] = val
            continue

        p_type = meta.get("type", "info")
        if p_type not in ("int", "float"):
            out[key] = val
            continue

        default = meta.get("default", 0)
        def_val = 0.0 if default is None else default
        try:
            num = float(val)
            if math.isnan(num) or math.isinf(num):
                num = float(def_val)
        except (TypeError, ValueError):
            num = float(def_val)

        if math.isnan(num) or math.isinf(num):
            num = 0.0

        lo, hi = meta.get("min"), meta.get("max")
        if lo is not None:
            num = max(num, float(lo))
        if hi is not None:
            num = min(num, float(hi))

        out[key] = int(round(num)) if p_type == "int" else num
    return out


class ExperimentController:
    """Manages worker processes, config building, and queue communication.

    No UI widgets — state is read by the UI layer (NiceGUI pages).
    """

    def __init__(self):
        # Worker state
        self.worker_process: Optional[mp.Process] = None
        self.cmd_queue: Optional[mp.Queue] = None
        self.telemetry_queue: Optional[mp.Queue] = None

        # Calibration matrix (loaded from external json, no live calibration process)
        self.calib_matrix: Optional[list] = None

        # Terminal status (survives until next experiment start)
        self.terminal_status: Optional[str] = None
        self.terminal_error: str = ""

    # ------------------------------------------------------------------
    # Config builder (static — no instance state needed)
    # ------------------------------------------------------------------

    @staticmethod
    def build_config(form: dict) -> Dict[str, Any]:
        """Build experiment config dict from flat form values.

        ``form`` keys:
            paradigm, pattern, subject_id, session_start, session_total,
            iti_range, isi_range, serial_port, screen_id, debug,
            viewing_distance_cm, screen_width_cm, resolution,
            paradigm_params (optional dict of raw widget values, coerced here).

        ``paradigm_params`` carries the kinematic trigger values and their
        companion enable flags as ordinary schema params; they must stay
        flattened to the top level of the returned config because the worker
        looks them up there.
        """
        root_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        out_dir = os.path.join(root_dir, "data")
        os.makedirs(out_dir, exist_ok=True)

        p_cls = PARADIGM_REGISTRY.get(form.get("paradigm"))
        schema = p_cls.get_full_schema() if p_cls else {}
        paradigm_params = _coerce_params(
            dict(form.get("paradigm_params", {})), schema
        )
        exec_mode = paradigm_params.get("Execution Mode", "Auto")

        # Resolution parsing
        res_str = str(form.get("resolution", "3840, 1080")).strip()
        res_parts = [p.strip() for p in res_str.split(",")]
        screen_w_px = _safe_int(res_parts[0], 3840) if len(res_parts) >= 1 else 3840
        screen_h_px = _safe_int(res_parts[1], 1080) if len(res_parts) >= 2 else 1080

        total_sessions = (
            -1
            if exec_mode == "Manual"
            else _safe_int(str(form.get("session_total", "2")), 2)
        )

        cfg: Dict[str, Any] = {
            "Subject ID": str(form.get("subject_id", "")).strip() or "cricket_001",
            "Session Number": _safe_int(str(form.get("session_start", "1")), 1),
            "Total Sessions": total_sessions,
            "ITI Range (sec)": str(form.get("iti_range", "60-90")).strip() or "60-90",
            "ISI Range (sec)": str(form.get("isi_range", "300-300")).strip() or "300-300",
            "Experiment Pattern": form.get("pattern", "Left-Right"),
            "Paradigm Class": form.get("paradigm", "SingleLooming"),
            "Serial Port": str(form.get("serial_port", "mock")).strip() or "mock",
            "Stimulus Screen ID": _safe_int(str(form.get("screen_id", "1")), 1),
            "Debug Mode": bool(form.get("debug", False)),
            "Viewing Distance (cm)": _safe_float(
                str(form.get("viewing_distance_cm", "30.0")), 30.0
            ),
            "Screen Width (cm)": _safe_float(
                str(form.get("screen_width_cm", "53.0")), 53.0
            ),
            "Screen Width (px)": screen_w_px,
            "Screen Height (px)": screen_h_px,
            "Sync Topology": [],
            "_output_dir": out_dir,
        }
        # A paradigm schema key that shadows a framework-reserved key silently
        # overrides operator input — e.g. SingleLooming declares its own
        # "Screen Width (px)", which beats the Resolution field. That is
        # deliberate for single-screen geometry, so the paradigm still wins;
        # log it so the override is visible rather than invisible.
        clash = sorted(set(paradigm_params) & set(cfg))
        if clash:
            log.warning(
                "paradigm %r declares schema keys that shadow reserved config "
                "keys %s; the paradigm's values take precedence over the "
                "corresponding dashboard fields",
                form.get("paradigm"), clash,
            )
        cfg.update(paradigm_params)

        return cfg

    # ------------------------------------------------------------------
    # Queue helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _drain_queue_async(q: mp.Queue):
        """Drain a queue in a daemon thread to avoid blocking."""
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

    def _close_queues(self, prefix: str = ""):
        """Close and drain experiment or calibration queues.

        prefix="" for experiment queues, prefix="calib_" for calibration.
        """
        names = (f"{prefix}cmd_queue", f"{prefix}telemetry_queue")
        for q_name in names:
            q = getattr(self, q_name, None)
            if q is not None:
                try:
                    q.cancel_join_thread()
                except (OSError, ValueError):
                    pass
                self._drain_queue_async(q)
                # Do NOT call q.close() here — the drain thread needs the
                # queue open to consume remaining items.  The queue will be
                # garbage-collected once the drain thread exits and this
                # reference is cleared.
                setattr(self, q_name, None)

    def _kill_worker(self, proc: Optional[mp.Process], timeout: float = 4.0):
        if proc is None:
            return
        for q_attr in (
            "cmd_queue", "telemetry_queue",
            "calib_cmd_queue", "calib_telemetry_queue",
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

    # ------------------------------------------------------------------
    # Telemetry polling
    # ------------------------------------------------------------------

    def poll_telemetry(self) -> dict:
        """Drain telemetry queue, return structured events.

        Returns dict with keys:
            telemetry: latest telemetry frame or None
            verdicts: list of verdict events
            terminal: terminal event or None
            worker_died: bool
        """
        result = {
            "telemetry": None,
            "verdicts": [],
            "terminal": None,
            "worker_died": False,
        }

        # --- Experiment telemetry ---
        if self.telemetry_queue:
            while not self.telemetry_queue.empty():
                try:
                    data = self.telemetry_queue.get_nowait()
                    action = data.get("action")
                    if action == "telemetry":
                        result["telemetry"] = data
                    elif action == "trial_verdict":
                        result["verdicts"].append(data)
                    elif action in ("worker_done", "worker_abort", "worker_error"):
                        result["terminal"] = data
                except (queue.Empty, ValueError, OSError, EOFError):
                    break

        # --- Dead worker detection ---
        if self.worker_process and not self.worker_process.is_alive():
            # Salvage terminal signals buried in queue
            if self.telemetry_queue:
                while not self.telemetry_queue.empty():
                    try:
                        frame = self.telemetry_queue.get_nowait()
                        if frame.get("action") in (
                            "worker_done", "worker_abort", "worker_error"
                        ):
                            result["terminal"] = frame
                    except (queue.Empty, ValueError, OSError, EOFError):
                        break
            result["worker_died"] = True

        return result

    # ------------------------------------------------------------------
    # Experiment lifecycle
    # ------------------------------------------------------------------

    @property
    def worker_alive(self) -> bool:
        return self.worker_process is not None and self.worker_process.is_alive()

    def start_experiment(self, config: dict):
        """Spawn stimulus worker with the given config."""
        if self.worker_alive:
            return
        from src.workers.stimulus_worker import worker_entry
        from src.workers.stimulus_worker import create_ipc_queues

        self.terminal_status = None
        self.terminal_error = ""
        self._close_queues()
        self.cmd_queue, self.telemetry_queue = create_ipc_queues()

        self.worker_process = mp.Process(
            target=worker_entry, args=(config, self.cmd_queue, self.telemetry_queue)
        )
        self.worker_process.start()

    def stop_experiment(self):
        """Send POISON_PILL to the stimulus worker."""
        if self.cmd_queue:
            try:
                self.cmd_queue.put(({"action": "POISON_PILL"}), timeout=1.0)
            except (queue.Full, OSError):
                # Queue full or broken — force-kill as fallback
                self._kill_worker(self.worker_process)

    def cleanup_worker(self):
        """Clean up after worker dies. Call when poll_telemetry reports worker_died."""
        self._close_queues()
        self._kill_worker(self.worker_process)
        self.worker_process = None

    # ------------------------------------------------------------------
    # Calibration matrix (loaded from external tool, no live process)
    # ------------------------------------------------------------------

    def load_calibration_matrix(self, path: Optional[str] = None) -> Optional[list]:
        """Load calibration matrix from json file. Returns matrix or None."""
        if path is None:
            root_dir = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            path = os.path.join(root_dir, "calibration_cfg.json")
        try:
            with open(path, "r") as f:
                matrix = json.load(f)
            if isinstance(matrix, list) and len(matrix) == 3:
                self.calib_matrix = matrix
                return matrix
        except (FileNotFoundError, json.JSONDecodeError, Exception):
            pass
        return None

    def save_calibration_matrix(self, matrix: list, path: Optional[str] = None):
        """Save matrix to disk and store in memory."""
        self.calib_matrix = matrix
        if path is None:
            root_dir = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            path = os.path.join(root_dir, "calibration_cfg.json")
        try:
            with open(path, "w") as f:
                json.dump(matrix, f, indent=2)
        except Exception:
            pass
