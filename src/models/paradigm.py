import math
import random
import numpy as np
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Tuple, Callable


class BaseParadigm(ABC):
    @staticmethod
    def _apply_random_seed(config: dict) -> None:
        raw = str(config.get("Random Seed", "Auto")).strip()
        if raw.lower() in ("auto", ""):
            seed = np.random.randint(0, 2**31 - 1)
        else:
            try:
                seed = int(raw)
            except ValueError:
                seed = np.random.randint(0, 2**31 - 1)
        random.seed(seed)
        np.random.seed(seed)
        config["Random Seed"] = seed

    @classmethod
    def _schema_default(cls, key: str) -> Any:
        return cls.get_parameter_schema()[key]["default"]

    @classmethod
    def get_telemetry_schema(cls) -> list:
        """Return field definitions for hardware telemetry parsing.
        Each entry: (raw_index, default_value, header_key)
        """
        return [
            (0, 0, "ard_time"),
            (1, 0, "dx"),
            (2, 0, "dy"),
            (3, 0, "dz"),
            (4, 0, "stim_state"),
        ]

    @classmethod
    def get_mock_generator(cls) -> Callable[[int], str]:
        """Return a function that generates mock serial data for this paradigm."""

        def generator(t_ard: int) -> str:
            return f"{t_ard},0,0,0,0"

        return generator

    @classmethod
    def get_sync_channels(cls) -> List[str]:
        """Return named sync trigger channels for this paradigm.
        Each entry generates a Sync Block row in the dashboard topology UI.
        """
        return ["Sync Trigger"]

    @classmethod
    @abstractmethod
    def get_available_patterns(cls) -> List[str]:
        pass

    @classmethod
    @abstractmethod
    def get_parameter_schema(cls) -> Dict[str, Dict[str, Any]]:
        pass

    @abstractmethod
    def generate_trials(self, pattern_key: str) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def prepare_trial(self, trial_context: dict) -> str:
        pass

    def _build_sync_markers(self, is_active: bool, mode: str) -> List[dict]:
        """Generate photodiode sync marker Rect commands.

        mode: "dual" for 4 markers (dual-screen), "single" for 2 markers (single-screen)
        """
        margin = 10
        w, h = 60, 60
        half_w = self._win_w / 2.0
        half_h = self._win_h / 2.0
        odd = self._frame_counter % 2 == 1

        on = [1, 1, 1]
        off = [-1, -1, -1]

        if mode == "dual":
            outer_color = on if (is_active and odd) else off
            inner_color = on if is_active else off
            positions = [
                (-half_w + margin + w / 2, -half_h + margin + h / 2),
                (-half_w + margin + w * 1.5 + margin, -half_h + margin + h / 2),
                (half_w - margin - w * 1.5 - margin, -half_h + margin + h / 2),
                (half_w - margin - w / 2, -half_h + margin + h / 2),
            ]
            colors = [outer_color, inner_color, inner_color, outer_color]
        elif mode == "single":
            flash_color = on if (is_active and odd) else off
            active_color = on if is_active else off
            positions = [
                (half_w - margin - w * 1.5 - margin, -half_h + margin + h / 2),
                (half_w - margin - w / 2, -half_h + margin + h / 2),
            ]
            colors = [active_color, flash_color]
        else:
            return []

        cmds = []
        for i, (pos, color) in enumerate(zip(positions, colors)):
            cmds.append({
                "id": f"_sync_{i}",
                "type": "rect",
                "width": w,
                "height": h,
                "pos": pos,
                "fillColor": color,
                "lineColor": color,
                "lineWidth": 0,
            })
        return cmds

    @abstractmethod
    def process_frame(
        self, elapsed_time: float, trial_context: dict, hw_telemetry: dict
    ) -> Tuple[bool, List[dict], dict]:
        pass

    @abstractmethod
    def get_idle_frame(self, hw_telemetry: dict) -> Tuple[List[dict], dict]:
        pass


# ---------------------------------------------------------------------------
# Looming Paradigm (Multi-modal: Visual + Wind)
# ---------------------------------------------------------------------------


class LoomingParadigm(BaseParadigm):
    EXPERIMENT_PATTERNS = {
        "Baseline Visual": {
            "type": "baseline_visual",
            "target_ttc_ms": None,
            "lv_ratio_ms": 100,
        },
        "Baseline Wind": {
            "type": "baseline_wind",
            "target_ttc_ms": None,
            "lv_ratio_ms": None,
        },
        "Looming + Wind (TTC -373ms / 30°)": {
            "type": "looming_wind",
            "target_ttc_ms": -373,
            "lv_ratio_ms": 100,
        },
        "Looming + Wind (TTC -308ms / 36°)": {
            "type": "looming_wind",
            "target_ttc_ms": -308,
            "lv_ratio_ms": 100,
        },
        "Looming + Wind (TTC -261ms / 42°)": {
            "type": "looming_wind",
            "target_ttc_ms": -261,
            "lv_ratio_ms": 100,
        },
        "Looming + Wind (TTC -225ms / 48°)": {
            "type": "looming_wind",
            "target_ttc_ms": -225,
            "lv_ratio_ms": 100,
        },
        "Looming + Wind (TTC -119ms / 80°)": {
            "type": "looming_wind",
            "target_ttc_ms": -119,
            "lv_ratio_ms": 100,
        },
        "Looming + Wind (TTC 0ms / 180°)": {
            "type": "looming_wind",
            "target_ttc_ms": 0,
            "lv_ratio_ms": 100,
        },
        "Looming + Wind (TTC +200ms)": {
            "type": "looming_wind",
            "target_ttc_ms": 200,
            "lv_ratio_ms": 100,
        },
    }

    def __init__(self, debug_mode: bool = False, config: dict = None):
        self.config = config or {}
        self.viewing_distance_cm = float(self.config.get("Viewing Distance (cm)", 30.0))
        self.screen_width_cm = float(self.config.get("Screen Width (cm)", 53.0))

        screen_w_px = int(self.config.get("Screen Width (px)", 3840))
        screen_h_px = int(self.config.get("Screen Height (px)", 1080))
        bezel_width_px = int(self.config.get("Bezel Width (px)", 0))

        self.init_deg = 2.0
        self.max_deg = 179.0
        self._baseline_delay = 1.0
        self._baseline_post = 1.5

        self.scale = 0.3 if debug_mode else 1.0
        self._win_w = screen_w_px // 3 if debug_mode else screen_w_px
        self._win_h = screen_h_px // 2 if debug_mode else screen_h_px
        self._frame_counter = 0

        if debug_mode:
            self.per_screen_w_px = screen_w_px // 6
            self.c_l = -screen_w_px // 12
            self.c_r = screen_w_px // 12
            self.mask_w = screen_w_px // 6
            self.mask_h = screen_h_px // 3
        else:
            self.per_screen_w_px = screen_w_px // 2
            half_bezel = bezel_width_px // 2
            self.c_l = -(screen_w_px // 4 + half_bezel)
            self.c_r = screen_w_px // 4 + half_bezel
            self.mask_w = screen_w_px // 2
            self.mask_h = screen_h_px

        self.init_px = self._deg_to_pix(self.init_deg)

    @classmethod
    def get_available_patterns(cls) -> List[str]:
        return list(cls.EXPERIMENT_PATTERNS.keys())

    @classmethod
    def get_parameter_schema(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "Execution Mode": {
                "type": "choice",
                "default": "Auto",
                "choices": ["Auto", "Manual", "Kinematic"],
                "label": "Execution Mode",
            },
            "Bezel Width (px)": {
                "type": "int",
                "default": 0,
                "min": 0,
                "max": 200,
                "label": "Bezel Width (px)",
            },
            "note": {
                "type": "info",
                "label": "This paradigm has fixed experiment patterns. Select a pattern above.",
            },
        }

    @classmethod
    def get_sync_channels(cls) -> List[str]:
        return ["Trial Active", "Phase Flip"]

    def _build_stimulus_commands(self, side: str, theta: float, stim_active: bool = False) -> List[dict]:
        r_px_l = self._deg_to_pix(theta if side in ("left", "both") else self.init_deg)
        r_px_r = self._deg_to_pix(theta if side in ("right", "both") else self.init_deg)

        # ── 色彩空间 (PsychoPy RGB: -1=纯黑, 0=中灰, +1=纯白) ──
        _gray = [0, 0, 0]       # 中性灰背景
        _black = [-1, -1, -1]   # 纯黑刺激物

        bg_l = {
            "id": "_bg_l",
            "type": "rect",
            "width": self.mask_w,
            "height": self.mask_h,
            "pos": (self.c_l, 0),
            "fillColor": _gray,
            "lineColor": _gray,
            "lineWidth": 0,
        }
        bg_r = {
            "id": "_bg_r",
            "type": "rect",
            "width": self.mask_w,
            "height": self.mask_h,
            "pos": (self.c_r, 0),
            "fillColor": _gray,
            "lineColor": _gray,
            "lineWidth": 0,
        }
        # ── 圆形刺激 (纯黑 Looming Disk) ──
        # edges=256: 高精度多边形拟合，减少大半径锯齿
        # lineWidth=0 + lineColor=fillColor: 消除描边伪影
        stim_l = {
            "id": "stim_l",
            "type": "circle",
            "radius": r_px_l,
            "pos": (self.c_l, 0),
            "fillColor": _black,
            "lineColor": _black,
            "lineWidth": 0,
            "edges": 256,
        }
        stim_r = {
            "id": "stim_r",
            "type": "circle",
            "radius": r_px_r,
            "pos": (self.c_r, 0),
            "fillColor": _black,
            "lineColor": _black,
            "lineWidth": 0,
            "edges": 256,
        }
        bezel = {
            "id": "_bezel",
            "type": "rect",
            "width": 0,
            "height": self.mask_h * 1.5,
            "pos": (0, 0),
            "fillColor": _gray,
            "lineColor": _gray,
            "lineWidth": 0,
        }

        sync = self._build_sync_markers(stim_active, "dual")
        if side == "left":
            return [bg_l, stim_l, bg_r, stim_r, bezel, *sync]
        elif side == "right":
            return [bg_r, stim_r, bg_l, stim_l, bezel, *sync]
        else:
            return [bg_l, bg_r, stim_l, stim_r, bezel, *sync]

    def generate_trials(self, pattern_key: str) -> List[Dict[str, Any]]:
        p = self.EXPERIMENT_PATTERNS[pattern_key]
        trials = []
        for direction in ["left"] * 9 + ["right"] * 9:
            d = {
                "type": p["type"],
                "target_ttc_ms": p["target_ttc_ms"],
                "lv_ratio_ms": p["lv_ratio_ms"],
            }
            if p["type"] == "baseline_visual":
                d["wind_dir"], d["screen_side"] = "none", direction
            else:
                d["wind_dir"], d["screen_side"] = direction, direction
            trials.append(d)
        random.shuffle(trials)
        return trials

    def prepare_trial(self, trial_context: dict) -> str:
        if trial_context["type"] == "looming_wind":
            wind_dir = trial_context.get("wind_dir", "none")
            if wind_dir == "none":
                return ""
            lv_s = trial_context.get("lv_ratio_ms", 100) / 1000.0
            init_rad = math.radians(self.init_deg / 2)
            t_col_s = lv_s / math.tan(init_rad) if math.tan(init_rad) != 0 else 0
            delay_ms = max(
                0, int(round(t_col_s * 1000)) + trial_context["target_ttc_ms"]
            )
            dir_char = "R" if wind_dir == "right" else "L"
            return f"<{dir_char},{delay_ms}>"
        elif trial_context["type"] == "baseline_wind":
            self._baseline_delay = random.uniform(0.1, 0.2)
            self._baseline_post = random.uniform(1.0, 2.0)
            wind_dir = trial_context.get("wind_dir", "none")
            if wind_dir != "none":
                dir_char = "R" if wind_dir == "right" else "L"
                delay_ms = int(round(self._baseline_delay * 1000))
                return f"<{dir_char},{delay_ms}>"
        return ""

    def _deg_to_pix(self, deg: float) -> float:
        deg = min(deg, 179.99)
        r_cm = math.tan(math.radians(deg / 2.0)) * self.viewing_distance_cm
        px = r_cm * (self.per_screen_w_px / self.screen_width_cm) * self.scale
        return min(px, self.per_screen_w_px * 2.0)

    def get_idle_frame(self, hw_telemetry: dict) -> Tuple[List[dict], dict]:
        cmds = self._build_stimulus_commands("both", self.init_deg)
        tel = {
            "phase": "Idle",
            "hw_cmd": None,
            "ui_color": "cyan",
            "ui_metrics": {
                "theta": self.init_deg,
                "side": "—",
                **hw_telemetry,
            },
            "ui_twin": {
                "side": "—",
                "radius_ratio": self._deg_to_pix(self.init_deg) / self.per_screen_w_px,
            },
        }
        return cmds, tel

    def build_prewarm_commands(self) -> List[dict]:
        """Force-allocate GPU buffers at max radius before any trial starts.

        圆形以灰色填充（与背景同色），确保不可见；
        但 GPU 纹理/VBO 已按最大半径完成分配。
        后续试次首帧只需轻量属性更新（radius + fillColor）。
        """
        _gray = [0, 0, 0]
        max_r = self._deg_to_pix(self.max_deg)
        return [
            {"id": "_bg_l", "type": "rect", "width": self.mask_w, "height": self.mask_h,
             "pos": (self.c_l, 0), "fillColor": _gray, "lineColor": _gray, "lineWidth": 0},
            {"id": "_bg_r", "type": "rect", "width": self.mask_w, "height": self.mask_h,
             "pos": (self.c_r, 0), "fillColor": _gray, "lineColor": _gray, "lineWidth": 0},
            {"id": "stim_l", "type": "circle", "radius": max_r, "pos": (self.c_l, 0),
             "fillColor": _gray, "lineColor": _gray, "lineWidth": 0, "edges": 256},
            {"id": "stim_r", "type": "circle", "radius": max_r, "pos": (self.c_r, 0),
             "fillColor": _gray, "lineColor": _gray, "lineWidth": 0, "edges": 256},
            {"id": "_bezel", "type": "rect", "width": 0, "height": self.mask_h * 1.5,
             "pos": (0, 0), "fillColor": _gray, "lineColor": _gray, "lineWidth": 0},
        ]

    def process_frame(
        self, elapsed_time: float, trial_context: dict, hw_telemetry: dict
    ) -> Tuple[bool, List[dict], dict]:
        self._frame_counter += 1
        t_type = trial_context["type"]
        side = trial_context["screen_side"]

        is_done = False
        theta = self.init_deg
        hw_cmd = None
        phase = "Trial"
        stim_active = 0
        wind_active = 0

        if t_type in ["looming_wind", "baseline_visual"]:
            lv_s = trial_context.get("lv_ratio_ms", 100) / 1000.0
            init_rad = math.radians(self.init_deg / 2)
            t_col = lv_s / math.tan(init_rad) if math.tan(init_rad) != 0 else 0

            # 严格依据时间轴进行状态切片
            if elapsed_time >= t_col + 1.0:
                is_done = True
                phase = "PostLooming_End"
            elif elapsed_time >= t_col:
                theta = self.max_deg
                # 越过 TTC=0 瞬间，发射特征 Phase 触发 Worker 记录
                phase = "Collision_TTC0"
                stim_active = 1
            else:
                delta = max(t_col - elapsed_time, 0.001)
                theta = math.degrees(2 * math.atan(lv_s / delta))
                theta = min(theta, self.max_deg)
                phase = "Looming"
                stim_active = 1

        elif t_type == "baseline_wind":
            if elapsed_time >= (self._baseline_delay + self._baseline_post):
                is_done = True
            else:
                phase = "Baseline"
                theta = self.init_deg
                stim_active = 1

        cmds = self._build_stimulus_commands(side, theta, bool(stim_active))

        ui_color = (
            "lime"
            if phase == "Looming"
            else ("yellow" if phase == "Collision_TTC0"
            else ("red" if phase == "PostLooming_End"
            else ("orange" if phase == "Baseline" else "cyan")))
        )
        radius_ratio = self._deg_to_pix(theta) / self.per_screen_w_px
        tel = {
            "phase": phase,
            "hw_cmd": hw_cmd,
            "ui_color": ui_color,
            "ui_metrics": {
                "theta": round(theta, 1),
                "side": side,
                **hw_telemetry,
            },
            "ui_twin": {
                "side": side,
                "radius_ratio": radius_ratio,
            },
        }
        return is_done, cmds, tel


# ---------------------------------------------------------------------------
# Classic Looming Paradigm (Visual only, configurable)
# ---------------------------------------------------------------------------


class ClassicLoomingParadigm(BaseParadigm):
    EXPERIMENT_PATTERNS = {
        "Classic Looming (Random L/R)": "Random L/R",
        "Classic Looming (Always Left)": "Always Left",
        "Classic Looming (Always Right)": "Always Right",
    }

    def __init__(self, debug_mode: bool = False, config: dict = None):
        self.config = config or {}
        self.viewing_distance_cm = float(self.config.get("Viewing Distance (cm)", 30.0))
        self.screen_width_cm = float(self.config.get("Screen Width (cm)", 53.0))
        self.lv_ratio_ms = float(
            self.config.get("l/v Ratio (ms)", self._schema_default("l/v Ratio (ms)"))
        )
        self.init_deg = float(
            self.config.get(
                "Initial Degree (°)", self._schema_default("Initial Degree (°)")
            )
        )
        self.max_deg = float(
            self.config.get(
                "Final Degree (°)", self._schema_default("Final Degree (°)")
            )
        )

        screen_w_px = int(self.config.get("Screen Width (px)", 3840))
        screen_h_px = int(self.config.get("Screen Height (px)", 1080))
        bezel_width_px = int(self.config.get("Bezel Width (px)", 0))

        self.scale = 0.3 if debug_mode else 1.0
        self._win_w = screen_w_px // 3 if debug_mode else screen_w_px
        self._win_h = screen_h_px // 2 if debug_mode else screen_h_px
        self._frame_counter = 0

        if debug_mode:
            self.per_screen_w_px = screen_w_px // 6
            self.c_l = -screen_w_px // 12
            self.c_r = screen_w_px // 12
            self.mask_w = screen_w_px // 6
            self.mask_h = screen_h_px // 3
        else:
            self.per_screen_w_px = screen_w_px // 2
            half_bezel = bezel_width_px // 2
            self.c_l = -(screen_w_px // 4 + half_bezel)
            self.c_r = screen_w_px // 4 + half_bezel
            self.mask_w = screen_w_px // 2
            self.mask_h = screen_h_px

        self.init_px = self._deg_to_pix(self.init_deg)

    @classmethod
    def get_available_patterns(cls) -> List[str]:
        return list(cls.EXPERIMENT_PATTERNS.keys())

    @classmethod
    def get_parameter_schema(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "l/v Ratio (ms)": {
                "type": "float",
                "default": 80.0,
                "min": 1.0,
                "max": 10000.0,
                "label": "l/v Ratio (ms)",
            },
            "Initial Degree (°)": {
                "type": "float",
                "default": 2.0,
                "min": 0.1,
                "max": 179.0,
                "label": "Initial Degree (°)",
            },
            "Final Degree (°)": {
                "type": "float",
                "default": 180.0,
                "min": 1.0,
                "max": 179.9,
                "label": "Final Degree (°)",
            },
            "Number of Trials": {
                "type": "int",
                "default": 18,
                "min": 1,
                "max": 9999,
                "label": "Number of Trials",
            },
            "Execution Mode": {
                "type": "choice",
                "default": "Auto",
                "choices": ["Auto", "Manual", "Kinematic"],
                "label": "Execution Mode",
            },
            "Bezel Width (px)": {
                "type": "int",
                "default": 0,
                "min": 0,
                "max": 200,
                "label": "Bezel Width (px)",
            },
        }

    def generate_trials(self, pattern_key: str) -> List[Dict[str, Any]]:
        mode = self.EXPERIMENT_PATTERNS.get(pattern_key, pattern_key)
        num_trials = int(
            self.config.get(
                "Number of Trials", self._schema_default("Number of Trials")
            )
        )
        trials = []

        if mode == "Always Left":
            directions = ["left"] * num_trials
        elif mode == "Always Right":
            directions = ["right"] * num_trials
        else:
            half = num_trials // 2
            extra_left = num_trials - half
            directions = ["left"] * extra_left + ["right"] * half
            random.shuffle(directions)

        for direction in directions:
            trials.append(
                {
                    "type": "classic_looming",
                    "direction": direction,
                    "lv_ratio_ms": self.lv_ratio_ms,
                    "initial_angle_deg": self.init_deg,
                    "final_angle_deg": self.max_deg,
                }
            )
        return trials

    def prepare_trial(self, trial_context: dict) -> str:
        return ""

    def _deg_to_pix(self, deg: float) -> float:
        deg = min(deg, 179.99)
        r_cm = math.tan(math.radians(deg / 2.0)) * self.viewing_distance_cm
        px = r_cm * (self.per_screen_w_px / self.screen_width_cm) * self.scale
        return min(px, self.per_screen_w_px * 2.0)

    @classmethod
    def get_sync_channels(cls) -> List[str]:
        return ["Trial Active", "Phase Flip"]

    def _build_stimulus_commands(self, side: str, theta: float, stim_active: bool = False) -> List[dict]:
        r_px_l = self._deg_to_pix(theta if side in ("left", "both") else self.init_deg)
        r_px_r = self._deg_to_pix(theta if side in ("right", "both") else self.init_deg)

        # ── 色彩空间 (PsychoPy RGB: -1=纯黑, 0=中灰, +1=纯白) ──
        _gray = [0, 0, 0]       # 中性灰背景
        _black = [-1, -1, -1]   # 纯黑刺激物

        bg_l = {
            "id": "_bg_l",
            "type": "rect",
            "width": self.mask_w,
            "height": self.mask_h,
            "pos": (self.c_l, 0),
            "fillColor": _gray,
            "lineColor": _gray,
            "lineWidth": 0,
        }
        bg_r = {
            "id": "_bg_r",
            "type": "rect",
            "width": self.mask_w,
            "height": self.mask_h,
            "pos": (self.c_r, 0),
            "fillColor": _gray,
            "lineColor": _gray,
            "lineWidth": 0,
        }
        # ── 圆形刺激 (纯黑 Looming Disk) ──
        # edges=256: 高精度多边形拟合，减少大半径锯齿
        # lineWidth=0 + lineColor=fillColor: 消除描边伪影
        stim_l = {
            "id": "stim_l",
            "type": "circle",
            "radius": r_px_l,
            "pos": (self.c_l, 0),
            "fillColor": _black,
            "lineColor": _black,
            "lineWidth": 0,
            "edges": 256,
        }
        stim_r = {
            "id": "stim_r",
            "type": "circle",
            "radius": r_px_r,
            "pos": (self.c_r, 0),
            "fillColor": _black,
            "lineColor": _black,
            "lineWidth": 0,
            "edges": 256,
        }
        bezel = {
            "id": "_bezel",
            "type": "rect",
            "width": 0,
            "height": self.mask_h * 1.5,
            "pos": (0, 0),
            "fillColor": _gray,
            "lineColor": _gray,
            "lineWidth": 0,
        }

        sync = self._build_sync_markers(stim_active, "dual")
        if side == "left":
            return [bg_l, stim_l, bg_r, stim_r, bezel, *sync]
        elif side == "right":
            return [bg_r, stim_r, bg_l, stim_l, bezel, *sync]
        else:
            return [bg_l, bg_r, stim_l, stim_r, bezel, *sync]

    def get_idle_frame(self, hw_telemetry: dict) -> Tuple[List[dict], dict]:
        cmds = self._build_stimulus_commands("both", self.init_deg)
        tel = {
            "phase": "Idle",
            "hw_cmd": None,
            "ui_color": "cyan",
            "ui_metrics": {
                "theta": self.init_deg,
                "side": "—",
                **hw_telemetry,
            },
            "ui_twin": {
                "side": "—",
                "radius_ratio": self._deg_to_pix(self.init_deg) / self.per_screen_w_px,
            },
        }
        return cmds, tel

    def build_prewarm_commands(self) -> List[dict]:
        """Force-allocate GPU buffers at max radius before any trial starts.

        圆形以灰色填充（与背景同色），确保不可见；
        但 GPU 纹理/VBO 已按最大半径完成分配。
        后续试次首帧只需轻量属性更新（radius + fillColor）。
        """
        _gray = [0, 0, 0]
        max_r = self._deg_to_pix(self.max_deg)
        return [
            {"id": "_bg_l", "type": "rect", "width": self.mask_w, "height": self.mask_h,
             "pos": (self.c_l, 0), "fillColor": _gray, "lineColor": _gray, "lineWidth": 0},
            {"id": "_bg_r", "type": "rect", "width": self.mask_w, "height": self.mask_h,
             "pos": (self.c_r, 0), "fillColor": _gray, "lineColor": _gray, "lineWidth": 0},
            {"id": "stim_l", "type": "circle", "radius": max_r, "pos": (self.c_l, 0),
             "fillColor": _gray, "lineColor": _gray, "lineWidth": 0, "edges": 256},
            {"id": "stim_r", "type": "circle", "radius": max_r, "pos": (self.c_r, 0),
             "fillColor": _gray, "lineColor": _gray, "lineWidth": 0, "edges": 256},
            {"id": "_bezel", "type": "rect", "width": 0, "height": self.mask_h * 1.5,
             "pos": (0, 0), "fillColor": _gray, "lineColor": _gray, "lineWidth": 0},
        ]

    def process_frame(
        self, elapsed_time: float, trial_context: dict, hw_telemetry: dict
    ) -> Tuple[bool, List[dict], dict]:
        self._frame_counter += 1
        lv_s = trial_context["lv_ratio_ms"] / 1000.0
        init_deg = trial_context["initial_angle_deg"]
        final_deg = trial_context["final_angle_deg"]
        side = trial_context["direction"]

        init_rad = math.radians(init_deg / 2)
        t_col = lv_s / math.tan(init_rad) if math.tan(init_rad) != 0 else 0

        is_done = False
        theta = init_deg
        stim_active = 0
        phase = "Trial"

        # 严格依据时间轴进行相变切片
        if elapsed_time >= t_col + 1.0:
            is_done = True
            theta = final_deg
            phase = "PostLooming_End"
        elif elapsed_time >= t_col:
            theta = final_deg
            phase = "Collision_TTC0"
        else:
            delta = max(t_col - elapsed_time, 0.001)
            theta = math.degrees(2 * math.atan(lv_s / delta))
            theta = min(theta, final_deg)
            phase = "Looming"
            stim_active = 1

        cmds = self._build_stimulus_commands(side, theta, bool(stim_active))
        ui_color = "lime" if phase == "Looming" else "cyan"

        tel = {
            "phase": phase,
            "hw_cmd": None,
            "ui_color": ui_color,
            "ui_metrics": {
                "theta": round(theta, 1),
                "side": side,
                **hw_telemetry,
            },
            "ui_twin": {
                "side": side,
                "radius_ratio": self._deg_to_pix(theta) / self.per_screen_w_px,
            },
        }
        return is_done, cmds, tel


# ---------------------------------------------------------------------------
# Optic Flow Paradigm (Vectorized dot-motion)
# ---------------------------------------------------------------------------


class OpticFlowParadigm(BaseParadigm):
    EXPERIMENT_PATTERNS = {
        "Optic Flow": "optic_flow",
    }

    def __init__(self, debug_mode: bool = False, config: dict = None):
        self.config = config or {}
        self.speed = float(
            self.config.get("Speed (deg/s)", self._schema_default("Speed (deg/s)"))
        )
        self.density = int(self.config.get("Density", self._schema_default("Density")))
        self.coherence = float(
            self.config.get("Coherence", self._schema_default("Coherence"))
        )
        self.direction = self.config.get("Direction", self._schema_default("Direction"))
        self.trial_duration = float(
            self.config.get(
                "Trial Duration (s)", self._schema_default("Trial Duration (s)")
            )
        )
        self.viewing_distance_cm = float(self.config.get("Viewing Distance (cm)", 30.0))
        self.screen_width_cm = float(self.config.get("Screen Width (cm)", 53.0))

        self.scale = 0.3 if debug_mode else 1.0

        screen_w_px = int(self.config.get("Screen Width (px)", 3840))
        screen_h_px = int(self.config.get("Screen Height (px)", 1080))
        self.screen_w = float(screen_w_px // 3 if debug_mode else screen_w_px)
        self.screen_h = float(screen_h_px // 2 if debug_mode else screen_h_px)
        self._win_w = self.screen_w
        self._win_h = self.screen_h
        self._frame_counter = 0

        half_w = self.screen_w / 2.0
        half_h = self.screen_h / 2.0
        self._x = np.random.uniform(-half_w, half_w, self.density).astype(np.float64)
        self._y = np.random.uniform(-half_h, half_h, self.density).astype(np.float64)

        coh_count = int(self.density * self.coherence)
        base_angle = 180.0 if self.direction == "Left" else 0.0
        angles = np.empty(self.density, dtype=np.float64)
        angles[:coh_count] = base_angle
        angles[coh_count:] = np.random.uniform(0.0, 360.0, self.density - coh_count)
        self._dx = np.cos(np.radians(angles))
        self._dy = np.sin(np.radians(angles))

    def _deg_to_pix(self, deg: float) -> float:
        deg = min(deg, 179.99)
        r_cm = math.tan(math.radians(deg / 2.0)) * self.viewing_distance_cm
        return r_cm * (self.screen_w / self.screen_width_cm) * self.scale

    @classmethod
    def get_available_patterns(cls) -> List[str]:
        return list(cls.EXPERIMENT_PATTERNS.keys())

    @classmethod
    def get_sync_channels(cls) -> List[str]:
        return ["Trial Active", "Phase Flip"]

    @classmethod
    def get_parameter_schema(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "Speed (deg/s)": {
                "type": "float",
                "default": 30.0,
                "min": 0.1,
                "max": 1000.0,
                "label": "Speed (deg/s)",
            },
            "Density": {
                "type": "int",
                "default": 200,
                "min": 1,
                "max": 50000,
                "label": "Density",
            },
            "Coherence": {
                "type": "float",
                "default": 1.0,
                "min": 0.0,
                "max": 1.0,
                "label": "Coherence (0–1)",
            },
            "Direction": {
                "type": "choice",
                "default": "Left",
                "choices": ["Left", "Right"],
                "label": "Direction",
            },
            "Trial Duration (s)": {
                "type": "float",
                "default": 5.0,
                "min": 0.1,
                "max": 600.0,
                "label": "Trial Duration (s)",
            },
            "Number of Trials": {
                "type": "int",
                "default": 10,
                "min": 1,
                "max": 9999,
                "label": "Number of Trials",
            },
            "Execution Mode": {
                "type": "choice",
                "default": "Auto",
                "choices": ["Auto", "Manual", "Kinematic"],
                "label": "Execution Mode",
            },
            "Random Seed": {
                "type": "string",
                "default": "Auto",
                "label": "Random Seed",
            },
        }

    def generate_trials(self, pattern_key: str) -> List[Dict[str, Any]]:
        n = int(
            self.config.get(
                "Number of Trials", self._schema_default("Number of Trials")
            )
        )
        return [
            {
                "type": "optic_flow",
                "trial_idx": i,
                "speed": self.speed,
                "density": self.density,
                "coherence": self.coherence,
                "direction": self.direction,
                "trial_duration": self.trial_duration,
            }
            for i in range(n)
        ]

    def prepare_trial(self, trial_context: dict) -> str:
        density = trial_context["density"]
        coherence = trial_context["coherence"]
        direction = trial_context["direction"]

        half_w = self.screen_w / 2.0
        half_h = self.screen_h / 2.0
        self._x = np.random.uniform(-half_w, half_w, density).astype(np.float64)
        self._y = np.random.uniform(-half_h, half_h, density).astype(np.float64)

        coh_count = int(density * coherence)
        base_angle = 180.0 if direction == "Left" else 0.0
        angles = np.empty(density, dtype=np.float64)
        angles[:coh_count] = base_angle
        angles[coh_count:] = np.random.uniform(0.0, 360.0, density - coh_count)
        self._dx = np.cos(np.radians(angles))
        self._dy = np.sin(np.radians(angles))

        self._last_time = 0.0
        self._coh_count = int(density * coherence)

        # Pre-allocate per-frame rendering arrays (avoids GC jitter)
        self._xys = np.empty((density, 2), dtype=np.float64)
        self._sizes = np.full((density, 2), 15.0, dtype=np.float64)
        self._colors = np.full((density, 3), 1.0, dtype=np.float64)
        self._opacities = np.ones(density, dtype=np.float64)

        # Pre-allocate per-frame scratch arrays (avoids GC jitter)
        self._rng = np.random.default_rng()
        self._rand_buf = np.empty(density, dtype=np.float64)
        self._annihilated = np.empty(density, dtype=bool)
        self._noise_mask = np.empty(density, dtype=bool)
        self._noise_mask[:coh_count] = False
        self._noise_mask[coh_count:] = True
        self._mask_right = np.empty(density, dtype=bool)
        self._mask_left = np.empty(density, dtype=bool)
        self._mask_top = np.empty(density, dtype=bool)
        self._mask_bottom = np.empty(density, dtype=bool)
        self._wrapped = np.empty(density, dtype=bool)

        return ""

    def get_idle_frame(self, hw_telemetry: dict) -> Tuple[List[dict], dict]:
        bg = {
            "id": "_bg",
            "type": "rect",
            "width": self.screen_w,
            "height": self.screen_h,
            "pos": (0, 0),
            "fillColor": [0, 0, 0],
            "lineColor": [0, 0, 0],
        }
        sync = self._build_sync_markers(False, "dual")
        tel = {
            "phase": "Idle",
            "hw_cmd": None,
            "ui_color": "cyan",
            "ui_metrics": {
                "speed": 0.0,
                "density": self.density,
                "n_dots": self.density,
                **hw_telemetry,
            },
            "ui_twin": None,
        }
        return [bg, *sync], tel

    def process_frame(
        self, elapsed_time: float, trial_context: dict, hw_telemetry: dict
    ) -> Tuple[bool, List[dict], dict]:
        self._frame_counter += 1
        speed = trial_context["speed"]
        density = trial_context["density"]

        is_done = elapsed_time >= trial_context["trial_duration"]

        dt = elapsed_time - self._last_time
        if dt <= 0:
            dt = 1.0 / 60.0
        self._last_time = elapsed_time

        step = self._deg_to_pix(speed) * dt
        self._x += self._dx * step
        self._y += self._dy * step

        half_w = self.screen_w / 2.0
        half_h = self.screen_h / 2.0
        coh_count = getattr(self, "_coh_count", density)

        # Frame-level annihilation: 3% chance per frame for noise particles
        self._rng.random(density, out=self._rand_buf)
        np.less(self._rand_buf, 0.03, out=self._annihilated)
        annihilated = self._annihilated
        annihilated &= self._noise_mask  # only noise particles can be annihilated
        if np.any(annihilated):
            n = annihilated.sum()
            self._x[annihilated] = np.random.uniform(-half_w, half_w, n)
            self._y[annihilated] = np.random.uniform(-half_h, half_h, n)
            new_angles = np.random.uniform(0.0, 360.0, n)
            self._dx[annihilated] = np.cos(np.radians(new_angles))
            self._dy[annihilated] = np.sin(np.radians(new_angles))

        # Wrap-around boundary check (in-place, pre-allocated masks)
        np.greater(self._x, half_w, out=self._mask_right)
        np.less(self._x, -half_w, out=self._mask_left)
        np.greater(self._y, half_h, out=self._mask_top)
        np.less(self._y, -half_h, out=self._mask_bottom)
        np.bitwise_or(self._mask_right, self._mask_left, out=self._wrapped)
        np.bitwise_or(self._wrapped, self._mask_top, out=self._wrapped)
        np.bitwise_or(self._wrapped, self._mask_bottom, out=self._wrapped)

        self._x[self._mask_right] -= self.screen_w
        self._x[self._mask_left] += self.screen_w
        self._y[self._mask_top] -= self.screen_h
        self._y[self._mask_bottom] += self.screen_h

        # Re-randomize direction for wrapped noise particles to break visual streaks
        np.bitwise_and(self._wrapped, self._noise_mask, out=self._annihilated)
        if np.any(self._annihilated):
            n = self._annihilated.sum()
            new_angles = np.random.uniform(0.0, 360.0, n)
            self._dx[self._annihilated] = np.cos(np.radians(new_angles))
            self._dy[self._annihilated] = np.sin(np.radians(new_angles))

        bg = {
            "id": "_bg",
            "type": "rect",
            "width": self.screen_w,
            "height": self.screen_h,
            "pos": (0, 0),
            "fillColor": [0, 0, 0],
            "lineColor": [0, 0, 0],
        }
        self._xys[:, 0] = self._x
        self._xys[:, 1] = self._y
        sync = self._build_sync_markers(True, "dual")
        cmds = [
            bg,
            {
                "type": "element_array",
                "n_elements": density,
                "xys": self._xys,
                "sizes": self._sizes,
                "colors": self._colors,
                "opacities": self._opacities,
            },
            *sync,
        ]

        tel = {
            "phase": "OpticFlow",
            "hw_cmd": None,
            "ui_color": "lime",
            "ui_metrics": {
                "speed": speed,
                "density": density,
                "n_dots": density,
                **hw_telemetry,
            },
            "ui_twin": None,
        }
        return is_done, cmds, tel


# ---------------------------------------------------------------------------
# Movement Trace Paradigm (Lissajous trajectory)
# ---------------------------------------------------------------------------


class MovementTraceParadigm(BaseParadigm):
    EXPERIMENT_PATTERNS = {
        "Movement Trace": "movement_trace",
    }

    def __init__(self, debug_mode: bool = False, config: dict = None):
        self.config = config or {}
        self.freq_x = float(self.config.get("Freq X", self._schema_default("Freq X")))
        self.freq_y = float(self.config.get("Freq Y", self._schema_default("Freq Y")))
        self.amp_x = float(
            self.config.get("Amplitude X", self._schema_default("Amplitude X"))
        )
        self.amp_y = float(
            self.config.get("Amplitude Y", self._schema_default("Amplitude Y"))
        )
        self.speed = float(self.config.get("Speed", self._schema_default("Speed")))
        self.n_trail = int(
            self.config.get("Trail Points", self._schema_default("Trail Points"))
        )
        self.trial_duration = float(
            self.config.get(
                "Trial Duration (s)", self._schema_default("Trial Duration (s)")
            )
        )

        self.scale = 0.3 if debug_mode else 1.0

        screen_w_px = int(self.config.get("Screen Width (px)", 3840))
        screen_h_px = int(self.config.get("Screen Height (px)", 1080))
        self.screen_w = float(screen_w_px // 3 if debug_mode else screen_w_px)
        self.screen_h = float(screen_h_px // 2 if debug_mode else screen_h_px)
        self._win_w = self.screen_w
        self._win_h = self.screen_h
        self._frame_counter = 0

        self._t_accum = 0.0
        self._trail_x = np.zeros(self.n_trail, dtype=np.float64)
        self._trail_y = np.zeros(self.n_trail, dtype=np.float64)
        self._trail_colors = np.zeros((self.n_trail, 3), dtype=np.float64)

    @classmethod
    def get_available_patterns(cls) -> List[str]:
        return list(cls.EXPERIMENT_PATTERNS.keys())

    @classmethod
    def get_sync_channels(cls) -> List[str]:
        return ["Quad Right", "Quad Upper", "Node Trigger", "Reserved"]

    @classmethod
    def get_parameter_schema(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "Freq X": {
                "type": "float",
                "default": 3.0,
                "min": 0.1,
                "max": 100.0,
                "label": "Frequency X",
            },
            "Freq Y": {
                "type": "float",
                "default": 2.0,
                "min": 0.1,
                "max": 100.0,
                "label": "Frequency Y",
            },
            "Amplitude X": {
                "type": "float",
                "default": 400.0,
                "min": 1.0,
                "max": 2000.0,
                "label": "Amplitude X (px)",
            },
            "Amplitude Y": {
                "type": "float",
                "default": 300.0,
                "min": 1.0,
                "max": 2000.0,
                "label": "Amplitude Y (px)",
            },
            "Speed": {
                "type": "float",
                "default": 1.0,
                "min": 0.01,
                "max": 100.0,
                "label": "Speed multiplier",
            },
            "Trail Points": {
                "type": "int",
                "default": 64,
                "min": 1,
                "max": 10000,
                "label": "Trail Points",
            },
            "Trial Duration (s)": {
                "type": "float",
                "default": 10.0,
                "min": 0.1,
                "max": 600.0,
                "label": "Trial Duration (s)",
            },
            "Number of Trials": {
                "type": "int",
                "default": 5,
                "min": 1,
                "max": 9999,
                "label": "Number of Trials",
            },
            "Execution Mode": {
                "type": "choice",
                "default": "Auto",
                "choices": ["Auto", "Manual", "Kinematic"],
                "label": "Execution Mode",
            },
        }

    def generate_trials(self, pattern_key: str) -> List[Dict[str, Any]]:
        n = int(
            self.config.get(
                "Number of Trials", self._schema_default("Number of Trials")
            )
        )
        return [{"type": "movement_trace", "trial_idx": i} for i in range(n)]

    def prepare_trial(self, trial_context: dict) -> str:
        self._t_accum = 0.0
        self._last_sin = 0.0
        self._trail_x = np.zeros(self.n_trail, dtype=np.float64)
        self._trail_y = np.zeros(self.n_trail, dtype=np.float64)
        self._trail_colors = np.zeros((self.n_trail, 3), dtype=np.float64)

        # Pre-allocate per-frame rendering arrays (avoids GC jitter)
        self._xys = np.empty((self.n_trail, 2), dtype=np.float64)
        trail_range = np.linspace(12.0, 2.0, self.n_trail, dtype=np.float64)
        self._sizes = np.empty((self.n_trail, 2), dtype=np.float64)
        self._sizes[:, 0] = trail_range
        self._sizes[:, 1] = trail_range
        self._opacities = np.ones(self.n_trail, dtype=np.float64)
        self._trail_linspace = np.linspace(1.0, 0.0, self.n_trail, dtype=np.float64)

        return ""

    def get_idle_frame(self, hw_telemetry: dict) -> Tuple[List[dict], dict]:
        bg = {
            "id": "_bg",
            "type": "rect",
            "width": self.screen_w,
            "height": self.screen_h,
            "pos": (0, 0),
            "fillColor": [0, 0, 0],
            "lineColor": [0, 0, 0],
        }
        sync = self._build_sync_markers(False, "dual")
        tel = {
            "phase": "Idle",
            "hw_cmd": None,
            "ui_color": "cyan",
            "ui_metrics": {
                "n_trail": self.n_trail,
                "pos_x": 0.0,
                "pos_y": 0.0,
                **hw_telemetry,
            },
            "ui_twin": None,
        }
        return [bg, *sync], tel

    def process_frame(
        self, elapsed_time: float, trial_context: dict, hw_telemetry: dict
    ) -> Tuple[bool, List[dict], dict]:
        self._frame_counter += 1
        self._t_accum = elapsed_time * self.speed
        t = self._t_accum

        x = self.amp_x * self.scale * math.sin(self.freq_x * t)
        y = self.amp_y * self.scale * math.sin(self.freq_y * t)

        # In-place shift (avoids np.roll allocating new arrays)
        self._trail_x[1:] = self._trail_x[:-1]
        self._trail_y[1:] = self._trail_y[:-1]
        self._trail_colors[1:] = self._trail_colors[:-1]
        self._trail_x[0] = x
        self._trail_y[0] = y
        self._trail_colors[0] = [1.0, 1.0, 1.0]

        self._trail_colors[:, 0] = 2.0 * self._trail_linspace - 1.0
        self._trail_colors[:, 1] = 2.0 * self._trail_linspace - 1.0
        self._trail_colors[:, 2] = 2.0 * self._trail_linspace - 1.0

        bg = {
            "id": "_bg",
            "type": "rect",
            "width": self.screen_w,
            "height": self.screen_h,
            "pos": (0, 0),
            "fillColor": [0, 0, 0],
            "lineColor": [0, 0, 0],
        }
        self._xys[:, 0] = self._trail_x
        self._xys[:, 1] = self._trail_y
        sync = self._build_sync_markers(True, "dual")
        cmds = [
            bg,
            {
                "type": "element_array",
                "n_elements": self.n_trail,
                "xys": self._xys[::-1],
                "sizes": self._sizes[::-1],
                "colors": self._trail_colors[::-1],
                "opacities": self._opacities[::-1],
            },
            *sync,
        ]

        is_done = elapsed_time >= self.trial_duration

        tel = {
            "phase": "MovementTrace",
            "hw_cmd": None,
            "ui_color": "lime",
            "ui_metrics": {
                "n_trail": self.n_trail,
                "pos_x": round(x, 1),
                "pos_y": round(y, 1),
                **hw_telemetry,
            },
            "ui_twin": None,
        }
        return is_done, cmds, tel


# ---------------------------------------------------------------------------
# Blank Paradigm (No stimulus, hardware tracking only)
# ---------------------------------------------------------------------------


class BlankParadigm(BaseParadigm):
    EXPERIMENT_PATTERNS = {
        "Blank Tracking (No Stimulus)": "blank_tracking",
    }

    def __init__(self, debug_mode: bool = False, config: dict = None):
        self.config = config or {}
        self.trial_duration = float(
            self.config.get(
                "Trial Duration (s)", self._schema_default("Trial Duration (s)")
            )
        )

        screen_w_px = int(self.config.get("Screen Width (px)", 3840))
        screen_h_px = int(self.config.get("Screen Height (px)", 1080))

        if debug_mode:
            self.screen_w = float(screen_w_px // 3)
            self.screen_h = float(screen_h_px // 2)
        else:
            self.screen_w = float(screen_w_px)
            self.screen_h = float(screen_h_px)

        self._win_w = self.screen_w
        self._win_h = self.screen_h
        self._frame_counter = 0

    @classmethod
    def get_available_patterns(cls) -> List[str]:
        return list(cls.EXPERIMENT_PATTERNS.keys())

    @classmethod
    def get_parameter_schema(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "Trial Duration (s)": {
                "type": "float",
                "default": 10.0,
                "min": 0.1,
                "max": 600.0,
                "label": "Trial Duration (s)",
            },
            "Number of Trials": {
                "type": "int",
                "default": 5,
                "min": 1,
                "max": 9999,
                "label": "Number of Trials",
            },
            "Execution Mode": {
                "type": "choice",
                "default": "Auto",
                "choices": ["Auto", "Manual", "Kinematic"],
                "label": "Execution Mode",
            },
        }

    def generate_trials(self, pattern_key: str) -> List[Dict[str, Any]]:
        n = int(
            self.config.get(
                "Number of Trials", self._schema_default("Number of Trials")
            )
        )
        return [
            {
                "type": "blank_tracking",
                "trial_idx": i,
                "trial_duration": self.trial_duration,
            }
            for i in range(n)
        ]

    def prepare_trial(self, trial_context: dict) -> str:
        return ""

    def _build_blank_bg(self) -> dict:
        return {
            "id": "_bg",
            "type": "rect",
            "width": self.screen_w,
            "height": self.screen_h,
            "pos": (0, 0),
            "fillColor": [0, 0, 0],
            "lineColor": [0, 0, 0],
        }

    def get_idle_frame(self, hw_telemetry: dict) -> Tuple[List[dict], dict]:
        sync = self._build_sync_markers(False, "dual")
        tel = {
            "phase": "Idle",
            "hw_cmd": None,
            "ui_color": "cyan",
            "ui_metrics": {
                **hw_telemetry,
            },
            "ui_twin": None,
        }
        return [self._build_blank_bg(), *sync], tel

    def process_frame(
        self, elapsed_time: float, trial_context: dict, hw_telemetry: dict
    ) -> Tuple[bool, List[dict], dict]:
        self._frame_counter += 1
        is_done = elapsed_time >= trial_context["trial_duration"]

        sync = self._build_sync_markers(True, "dual")
        tel = {
            "phase": "Blank",
            "hw_cmd": None,
            "ui_color": "lime",
            "ui_metrics": {
                **hw_telemetry,
            },
            "ui_twin": None,
        }
        return is_done, [self._build_blank_bg(), *sync], tel


# ---------------------------------------------------------------------------
# Grating Paradigm (Sinusoidal grating, pure-plugin via IoC protocol)
# ---------------------------------------------------------------------------


class GratingParadigm(BaseParadigm):
    EXPERIMENT_PATTERNS = {
        "Static Grating": "static_grating",
        "Drifting Grating": "drifting_grating",
    }

    def __init__(self, debug_mode: bool = False, config: dict = None):
        self.config = config or {}
        self.sf = float(
            self.config.get(
                "Spatial Freq (cpd)", self._schema_default("Spatial Freq (cpd)")
            )
        )
        self.tf = float(
            self.config.get(
                "Temporal Freq (Hz)", self._schema_default("Temporal Freq (Hz)")
            )
        )
        self.ori = float(
            self.config.get(
                "Orientation (°)", self._schema_default("Orientation (°)")
            )
        )
        self.contrast = float(
            self.config.get("Contrast", self._schema_default("Contrast"))
        )
        self.trial_duration = float(
            self.config.get(
                "Trial Duration (s)", self._schema_default("Trial Duration (s)")
            )
        )
        self.viewing_distance_cm = float(
            self.config.get("Viewing Distance (cm)", 30.0)
        )
        self.screen_width_cm = float(
            self.config.get("Screen Width (cm)", 53.0)
        )

        self.scale = 0.3 if debug_mode else 1.0

        screen_w_px = int(self.config.get("Screen Width (px)", 3840))
        screen_h_px = int(self.config.get("Screen Height (px)", 1080))
        self._win_w = screen_w_px // 3 if debug_mode else screen_w_px
        self._win_h = screen_h_px // 2 if debug_mode else screen_h_px
        self._frame_counter = 0

        if debug_mode:
            self.per_screen_w_px = screen_w_px // 6
            self.c_l = -screen_w_px // 12
            self.c_r = screen_w_px // 12
            self.mask_w = screen_w_px // 6
            self.mask_h = screen_h_px // 3
        else:
            self.per_screen_w_px = screen_w_px // 2
            self.c_l = -(screen_w_px // 4)
            self.c_r = screen_w_px // 4
            self.mask_w = screen_w_px // 2
            self.mask_h = screen_h_px

    @classmethod
    def get_available_patterns(cls) -> List[str]:
        return list(cls.EXPERIMENT_PATTERNS.keys())

    @classmethod
    def get_parameter_schema(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "Single Screen Mode": {
                "type": "bool",
                "default": True,
                "label": "Single Screen Mode",
            },
            "Spatial Freq (cpd)": {
                "type": "float",
                "default": 0.05,
                "min": 0.001,
                "max": 10.0,
                "label": "Spatial Frequency (cpd)",
            },
            "Temporal Freq (Hz)": {
                "type": "float",
                "default": 2.0,
                "min": 0.0,
                "max": 100.0,
                "label": "Temporal Frequency (Hz)",
            },
            "Orientation (°)": {
                "type": "float",
                "default": 0.0,
                "min": 0.0,
                "max": 360.0,
                "label": "Orientation (°)",
            },
            "Contrast": {
                "type": "float",
                "default": 1.0,
                "min": 0.0,
                "max": 1.0,
                "label": "Contrast (0-1)",
            },
            "Trial Duration (s)": {
                "type": "float",
                "default": 5.0,
                "min": 0.1,
                "max": 600.0,
                "label": "Trial Duration (s)",
            },
            "Number of Trials": {
                "type": "int",
                "default": 10,
                "min": 1,
                "max": 9999,
                "label": "Number of Trials",
            },
            "Execution Mode": {
                "type": "choice",
                "default": "Auto",
                "choices": ["Auto", "Manual", "Kinematic"],
                "label": "Execution Mode",
            },
        }

    def generate_trials(self, pattern_key: str) -> List[Dict[str, Any]]:
        n = int(
            self.config.get(
                "Number of Trials", self._schema_default("Number of Trials")
            )
        )
        return [
            {
                "type": "grating",
                "trial_idx": i,
                "Single Screen Mode": bool(self.config.get("Single Screen Mode", True)),
                "sf": self.sf,
                "tf": self.tf,
                "ori": self.ori,
                "contrast": self.contrast,
                "trial_duration": self.trial_duration,
            }
            for i in range(n)
        ]

    def prepare_trial(self, trial_context: dict) -> str:
        return ""

    def _deg_to_pix(self, deg: float) -> float:
        deg = min(deg, 179.99)
        r_cm = math.tan(math.radians(deg / 2.0)) * self.viewing_distance_cm
        return r_cm * (self.per_screen_w_px / self.screen_width_cm) * self.scale

    def _build_grating_commands(
        self, phase: float, trial_context: dict
    ) -> List[dict]:
        sf = trial_context.get("sf", self.sf)
        ori = trial_context.get("ori", self.ori)
        contrast = trial_context.get("contrast", self.contrast)
        is_single = trial_context.get("Single Screen Mode", True)

        if is_single:
            full_w = self.mask_w * 2
            h = self.mask_h
            return [
                {
                    "id": "_bg",
                    "class_name": "Rect",
                    "init_kwargs": {},
                    "updates": {
                        "size": [full_w, h],
                        "pos": [0, 0],
                        "fillColor": [0, 0, 0],
                        "lineColor": [0, 0, 0],
                    },
                },
                {
                    "id": "stim_full",
                    "class_name": "GratingStim",
                    "init_kwargs": {"tex": "sin", "mask": None},
                    "updates": {
                        "sf": sf,
                        "ori": ori,
                        "phase": phase,
                        "size": [full_w, h],
                        "pos": [0, 0],
                        "contrast": contrast,
                    },
                }
            ]
        else:
            w = self.mask_w
            h = self.mask_h
            return [
                {
                    "id": "_bg_l",
                    "class_name": "Rect",
                    "init_kwargs": {},
                    "updates": {
                        "size": [w, h],
                        "pos": [self.c_l, 0],
                        "fillColor": [0, 0, 0],
                        "lineColor": [0, 0, 0],
                    },
                },
                {
                    "id": "_bg_r",
                    "class_name": "Rect",
                    "init_kwargs": {},
                    "updates": {
                        "size": [w, h],
                        "pos": [self.c_r, 0],
                        "fillColor": [0, 0, 0],
                        "lineColor": [0, 0, 0],
                    },
                },
                {
                    "id": "stim_l",
                    "class_name": "GratingStim",
                    "init_kwargs": {"tex": "sin", "mask": None},
                    "updates": {
                        "sf": sf,
                        "ori": ori,
                        "phase": phase,
                        "size": [w, h],
                        "pos": [self.c_l, 0],
                        "contrast": contrast,
                    },
                },
                {
                    "id": "stim_r",
                    "class_name": "GratingStim",
                    "init_kwargs": {"tex": "sin", "mask": None},
                    "updates": {
                        "sf": sf,
                        "ori": ori,
                        "phase": phase,
                        "size": [w, h],
                        "pos": [self.c_r, 0],
                        "contrast": contrast,
                    },
                },
                {
                    "id": "_bezel",
                    "class_name": "Rect",
                    "init_kwargs": {},
                    "updates": {
                        "size": [100, int(self.mask_h * 1.5)],
                        "pos": [0, 0],
                        "fillColor": [-1, -1, -1],
                        "lineColor": [-1, -1, -1],
                    },
                },
            ]

    def _build_ui_twin(self, ori: float, side: str = "both") -> List[dict]:
        """Build Canvas draw commands representing grating orientation."""
        items: List[dict] = []
        centre_y = 75
        line_half = 50

        rad = math.radians(ori)
        dx = line_half * math.cos(rad)
        dy = -line_half * math.sin(rad)

        # Bezel divider
        items.append(
            {
                "cmd": "create_line",
                "args": [200, 0, 200, 150],
                "kwargs": {"fill": "#333333", "dash": (4, 2)},
            }
        )

        centres: List[int] = []
        if side in ("left", "both", "—"):
            centres.append(100)
        if side in ("right", "both", "—"):
            centres.append(300)

        for cx in centres:
            # Orientation line
            items.append(
                {
                    "cmd": "create_line",
                    "args": [
                        cx - dx,
                        centre_y - dy,
                        cx + dx,
                        centre_y + dy,
                    ],
                    "kwargs": {"fill": "white", "width": 2},
                }
            )
            # Spatial frequency indicator circle
            sf_safe = max(self.sf, 0.001)
            r = max(3, min(60, int(4.0 / sf_safe)))
            items.append(
                {
                    "cmd": "create_oval",
                    "args": [cx - r, centre_y - r, cx + r, centre_y + r],
                    "kwargs": {"outline": "cyan", "width": 1},
                }
            )

        return items

    def get_idle_frame(
        self, hw_telemetry: dict
    ) -> Tuple[List[dict], dict]:
        is_single = bool(self.config.get("Single Screen Mode", True))
        trial_ctx = {
            "Single Screen Mode": is_single,
            "sf": self.sf,
            "tf": self.tf,
            "ori": self.ori,
            "contrast": self.contrast,
            "trial_duration": self.trial_duration,
        }
        cmds = self._build_grating_commands(0.0, trial_ctx)
        mode = "single" if is_single else "dual"
        sync = self._build_sync_markers(False, mode)
        cmds.extend(sync)
        tel = {
            "phase": "Idle",
            "hw_cmd": None,
            "ui_color": "cyan",
            "ui_metrics": {
                "sf": self.sf,
                "tf": self.tf,
                "ori": self.ori,
                "contrast": self.contrast,
                **hw_telemetry,
            },
            "ui_twin": self._build_ui_twin(self.ori, "both"),
        }
        return cmds, tel

    def process_frame(
        self,
        elapsed_time: float,
        trial_context: dict,
        hw_telemetry: dict,
    ) -> Tuple[bool, List[dict], dict]:
        self._frame_counter += 1
        is_done = elapsed_time >= trial_context["trial_duration"]

        tf = trial_context.get("tf", self.tf)
        dynamic_phase = (elapsed_time * tf) % 1.0

        cmds = self._build_grating_commands(dynamic_phase, trial_context)
        is_single = trial_context.get("Single Screen Mode", True)
        mode = "single" if is_single else "dual"
        sync = self._build_sync_markers(True, mode)
        cmds.extend(sync)

        tel = {
            "phase": "Grating",
            "hw_cmd": None,
            "ui_color": "lime",
            "ui_metrics": {
                "sf": trial_context.get("sf", self.sf),
                "tf": tf,
                "ori": trial_context.get("ori", self.ori),
                "contrast": trial_context.get("contrast", self.contrast),
                "phase_val": round(dynamic_phase, 3),
                **hw_telemetry,
            },
            "ui_twin": self._build_ui_twin(
                trial_context.get("ori", self.ori), "both"
            ),
        }
        return is_done, cmds, tel


# ---------------------------------------------------------------------------
# Single Looming Paradigm (Visual only, single-screen centered)
# ---------------------------------------------------------------------------


class SingleLoomingParadigm(BaseParadigm):
    EXPERIMENT_PATTERNS = {
        "Baseline Visual": {
            "type": "baseline_visual",
            "target_ttc_ms": None,
            "lv_ratio_ms": 100,
        },
        "Baseline Wind": {
            "type": "baseline_wind",
            "target_ttc_ms": None,
            "lv_ratio_ms": None,
        },
        "Looming + Wind (TTC -373ms / 30°)": {
            "type": "looming_wind",
            "target_ttc_ms": -373,
            "lv_ratio_ms": 100,
        },
        "Looming + Wind (TTC -308ms / 36°)": {
            "type": "looming_wind",
            "target_ttc_ms": -308,
            "lv_ratio_ms": 100,
        },
        "Looming + Wind (TTC -261ms / 42°)": {
            "type": "looming_wind",
            "target_ttc_ms": -261,
            "lv_ratio_ms": 100,
        },
        "Looming + Wind (TTC -225ms / 48°)": {
            "type": "looming_wind",
            "target_ttc_ms": -225,
            "lv_ratio_ms": 100,
        },
        "Looming + Wind (TTC -119ms / 80°)": {
            "type": "looming_wind",
            "target_ttc_ms": -119,
            "lv_ratio_ms": 100,
        },
        "Looming + Wind (TTC 0ms / 180°)": {
            "type": "looming_wind",
            "target_ttc_ms": 0,
            "lv_ratio_ms": 100,
        },
        "Looming + Wind (TTC +200ms)": {
            "type": "looming_wind",
            "target_ttc_ms": 200,
            "lv_ratio_ms": 100,
        },
    }

    def __init__(self, debug_mode: bool = False, config: dict = None):
        self.config = config or {}
        self.viewing_distance_cm = float(self.config.get("Viewing Distance (cm)", 30.0))
        self.screen_width_cm = float(self.config.get("Screen Width (cm)", 53.0))

        screen_w_px = int(self.config.get("Screen Width (px)", 1920))
        screen_h_px = int(self.config.get("Screen Height (px)", 1080))

        self.init_deg = 2.0
        self.max_deg = 179.0
        self._baseline_delay = 1.0
        self._baseline_post = 1.5

        self.scale = 0.3 if debug_mode else 1.0
        self._win_w = screen_w_px // 3 if debug_mode else screen_w_px
        self._win_h = screen_h_px // 2 if debug_mode else screen_h_px
        self._frame_counter = 0

        if debug_mode:
            self.per_screen_w_px = screen_w_px // 3
            self.mask_w = screen_w_px // 3
            self.mask_h = screen_h_px // 2
        else:
            self.per_screen_w_px = screen_w_px
            self.mask_w = screen_w_px
            self.mask_h = screen_h_px

        self.init_px = self._deg_to_pix(self.init_deg)

    @classmethod
    def get_available_patterns(cls) -> List[str]:
        return list(cls.EXPERIMENT_PATTERNS.keys())

    @classmethod
    def get_parameter_schema(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "Execution Mode": {
                "type": "choice",
                "default": "Auto",
                "choices": ["Auto", "Manual", "Kinematic"],
                "label": "Execution Mode",
            },
            "Screen Width (px)": {
                "type": "int",
                "default": 1920,
                "min": 100,
                "max": 7680,
                "label": "Screen Width (px)",
            },
            "Screen Height (px)": {
                "type": "int",
                "default": 1080,
                "min": 100,
                "max": 4320,
                "label": "Screen Height (px)",
            },
            "note": {
                "type": "info",
                "label": "This paradigm has fixed experiment patterns. Select a pattern above.",
            },
        }

    @classmethod
    def get_sync_channels(cls) -> List[str]:
        return ["Trial Active", "Phase Flip"]

    def _build_stimulus_commands(self, theta: float, stim_active: bool = False) -> List[dict]:
        r_px = self._deg_to_pix(theta)

        _gray = [0, 0, 0]
        _black = [-1, -1, -1]

        bg = {
            "id": "_bg",
            "type": "rect",
            "width": self.mask_w,
            "height": self.mask_h,
            "pos": (0, 0),
            "fillColor": _gray,
            "lineColor": _gray,
            "lineWidth": 0,
        }
        stim = {
            "id": "stim",
            "type": "circle",
            "radius": r_px,
            "pos": (0, 0),
            "fillColor": _black,
            "lineColor": _black,
            "lineWidth": 0,
            "edges": 256,
        }
        sync = self._build_sync_markers(stim_active, "single")
        return [bg, stim, *sync]

    def generate_trials(self, pattern_key: str) -> List[Dict[str, Any]]:
        p = self.EXPERIMENT_PATTERNS[pattern_key]
        trials = []
        for _ in range(18):
            d = {
                "type": p["type"],
                "target_ttc_ms": p["target_ttc_ms"],
                "lv_ratio_ms": p["lv_ratio_ms"],
            }
            if p["type"] == "baseline_visual":
                d["wind_dir"], d["screen_side"] = "none", "center"
            else:
                d["wind_dir"], d["screen_side"] = "center", "center"
            trials.append(d)
        return trials

    def prepare_trial(self, trial_context: dict) -> str:
        if trial_context["type"] == "looming_wind":
            wind_dir = trial_context.get("wind_dir", "none")
            if wind_dir == "none":
                return ""
            lv_s = trial_context.get("lv_ratio_ms", 100) / 1000.0
            init_rad = math.radians(self.init_deg / 2)
            t_col_s = lv_s / math.tan(init_rad) if math.tan(init_rad) != 0 else 0
            delay_ms = max(
                0, int(round(t_col_s * 1000)) + trial_context["target_ttc_ms"]
            )
            dir_char = "R" if wind_dir == "right" else "L"
            return f"<{dir_char},{delay_ms}>"
        elif trial_context["type"] == "baseline_wind":
            self._baseline_delay = random.uniform(0.1, 0.2)
            self._baseline_post = random.uniform(1.0, 2.0)
            wind_dir = trial_context.get("wind_dir", "none")
            if wind_dir != "none":
                dir_char = "R" if wind_dir == "right" else "L"
                delay_ms = int(round(self._baseline_delay * 1000))
                return f"<{dir_char},{delay_ms}>"
        return ""

    def _deg_to_pix(self, deg: float) -> float:
        deg = min(deg, 179.99)
        r_cm = math.tan(math.radians(deg / 2.0)) * self.viewing_distance_cm
        px = r_cm * (self.per_screen_w_px / self.screen_width_cm) * self.scale
        return min(px, self.per_screen_w_px * 2.0)

    def get_idle_frame(self, hw_telemetry: dict) -> Tuple[List[dict], dict]:
        cmds = self._build_stimulus_commands(self.init_deg)
        tel = {
            "phase": "Idle",
            "hw_cmd": None,
            "ui_color": "cyan",
            "ui_metrics": {
                "theta": self.init_deg,
                "side": "center",
                **hw_telemetry,
            },
            "ui_twin": {
                "side": "center",
                "radius_ratio": self._deg_to_pix(self.init_deg) / self.per_screen_w_px,
            },
        }
        return cmds, tel

    def build_prewarm_commands(self) -> List[dict]:
        _gray = [0, 0, 0]
        max_r = self._deg_to_pix(self.max_deg)
        return [
            {"id": "_bg", "type": "rect", "width": self.mask_w, "height": self.mask_h,
             "pos": (0, 0), "fillColor": _gray, "lineColor": _gray, "lineWidth": 0},
            {"id": "stim", "type": "circle", "radius": max_r, "pos": (0, 0),
             "fillColor": _gray, "lineColor": _gray, "lineWidth": 0, "edges": 256},
        ]

    def process_frame(
        self, elapsed_time: float, trial_context: dict, hw_telemetry: dict
    ) -> Tuple[bool, List[dict], dict]:
        self._frame_counter += 1
        t_type = trial_context["type"]

        is_done = False
        theta = self.init_deg
        hw_cmd = None
        phase = "Trial"
        stim_active = 0
        wind_active = 0

        if t_type in ["looming_wind", "baseline_visual"]:
            lv_s = trial_context.get("lv_ratio_ms", 100) / 1000.0
            init_rad = math.radians(self.init_deg / 2)
            t_col = lv_s / math.tan(init_rad) if math.tan(init_rad) != 0 else 0

            if elapsed_time >= t_col + 1.0:
                is_done = True
                phase = "PostLooming_End"
            elif elapsed_time >= t_col:
                theta = self.max_deg
                phase = "Collision_TTC0"
                stim_active = 1
            else:
                delta = max(t_col - elapsed_time, 0.001)
                theta = math.degrees(2 * math.atan(lv_s / delta))
                theta = min(theta, self.max_deg)
                phase = "Looming"
                stim_active = 1

        elif t_type == "baseline_wind":
            if elapsed_time >= (self._baseline_delay + self._baseline_post):
                is_done = True
            else:
                phase = "Baseline"
                theta = self.init_deg
                stim_active = 1

        cmds = self._build_stimulus_commands(theta, bool(stim_active))

        ui_color = (
            "lime"
            if phase == "Looming"
            else ("yellow" if phase == "Collision_TTC0"
            else ("red" if phase == "PostLooming_End"
            else ("orange" if phase == "Baseline" else "cyan")))
        )
        radius_ratio = self._deg_to_pix(theta) / self.per_screen_w_px
        tel = {
            "phase": phase,
            "hw_cmd": hw_cmd,
            "ui_color": ui_color,
            "ui_metrics": {
                "theta": round(theta, 1),
                "side": "center",
                **hw_telemetry,
            },
            "ui_twin": {
                "side": "center",
                "radius_ratio": radius_ratio,
            },
        }
        return is_done, cmds, tel


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

PARADIGM_REGISTRY: Dict[str, type] = {
    "Looming": LoomingParadigm,
    "ClassicLooming": ClassicLoomingParadigm,
    "OpticFlow": OpticFlowParadigm,
    "MovementTrace": MovementTraceParadigm,
    "Blank": BlankParadigm,
    "Grating": GratingParadigm,
    "SingleLooming": SingleLoomingParadigm,
}


def get_available_patterns() -> dict:
    mapping = {}
    for cls_name, cls_obj in PARADIGM_REGISTRY.items():
        for pat in cls_obj.get_available_patterns():
            mapping[pat] = cls_name
    return mapping
