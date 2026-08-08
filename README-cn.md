# Cercus

**Cercus** 是一个面向高时间精度生物行为学与神经科学实验的多进程、闭环刺激控制框架。系统基于 Master-Worker 架构，实现了 UI 调度、视觉渲染、硬件遥测与数据持久化的物理级解耦。

---

# 第一部分 — 研究者使用指南

## 1. 架构概览与核心特性

Cercus 强制执行单向数据流与功能隔离，包含以下四个子系统：

- **主控中枢** (`src/ui/dashboard.py`)：非阻塞 GUI，负责参数装配、动态表单生成与实时状态监控。同时派生一个守护**网页镜像**进程（`src/core/web_telemetry.py`），通过 WebSocket 向局域网内任意浏览器广播 Dashboard 状态。
- **纯逻辑计算核** (`src/models/paradigm.py`)：数学模型层。基于时间差与硬件反馈输出标准化渲染指令流。
- **无状态渲染引擎** (`src/core/render.py`)：执行基础几何绘制指令（支持 `circle`, `rect`, `element_array` 等渲染类型），不维护状态。
- **异步硬件驱动** (`src/core/hardware.py`)：处理高频传感器数据采集与触发信号下发。
- **双轨数据记录** (`src/core/logger.py`)：分离高频运动学遥测数据与低频实验事件流。

### 执行模式

| 模式                        | 行为                                                                                          |
| --------------------------- | --------------------------------------------------------------------------------------------- |
| **Auto（自动）**            | 基于设定的 ITI/ISI 区间全自动连续执行实验流程。                                               |
| **Manual（手动）**          | 在 ITI 结束后渲染进程安全挂起，等待外部按键（`Space`）精准触发单次试次。                      |
| **Kinematic（运动学触发）** | 当运动学触发条件满足时（如移动距离、角度或速度阈值），试次自动启动。阈值在 Dashboard 中配置。 |

## 2. 环境安装与运行

建议在隔离的虚拟环境（如 Conda）中运行本系统，安装核心依赖项：

```bash
pip install -r requirements.txt
```

执行入口文件启动控制台：

```bash
python main.py
```

## 3. 内置实验范式

以下范式已内置，可通过 Dashboard 下拉菜单动态装载：

| 范式                               | 说明                                                                                                               |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| **Looming（多模态逼近）**          | 视觉 + 风场多模态逼近刺激。包含纯视觉与纯风场基线，以及 7 组从 TTC -373ms 到 +200ms 梯度风场标定的多感觉融合条件。 |
| **ClassicLooming（经典视觉逼近）** | 纯视觉参数化逼近模型。支持动态配置碰撞比（l/v ratio）、起始/终止视角及左右呈现逻辑。                               |
| **OpticFlow（光流场）**            | 矢量化粒子运动模型。支持配置速度、密度、相干性与运动方向。                                                         |
| **MovementTrace（运动轨迹）**      | 利萨茹曲线轨迹跟踪。支持配置 X/Y 轴频率、振幅与拖影长度。                                                          |
| **Grating（光栅）**                | 正弦光栅刺激。支持静态与漂移模式，可配置空间频率、时间频率、方向与对比度。                                         |
| **SingleLooming（单屏逼近）**      | 单屏居中逼近刺激。包含与 Looming 相同的多模态条件，适用于单显示器实验环境。                                        |
| **Blank（空白）**                  | 无刺激 — 仅硬件追踪。用于基线记录。                                                                                |

## 4. 物理空间校准

Dashboard 右侧面板提供了 **物理校准** 系统，用于解耦三轴传感器串扰。

### 操作流程

1. 点击 **Enter Calibration** 激活校准工作进程（刺激工作进程将被关闭）。
2. 设置 **Radius (mm)** — 校准球的已知半径。
3. 设置 **Rotations** — 每个轴记录的完整旋转圈数。
4. 点击 **Calibrate X**（或 Y / Z）。沿该轴**正方向**严格滚动球体。完成后点击 **Stop Axis**。
5. 对三个轴重复上述操作。每个轴的原始向量和目标距离将显示在面板上。
6. 三个轴全部完成后，点击 **Apply Matrix**。系统通过 `inverse(raw_matrix) * target_matrix` 计算 3×3 解耦矩阵，并保存至项目根目录的 `calibration_cfg.json`。
7. 后续启动时矩阵会自动加载并注入硬件守护进程。

也可以在 **Manual Calibration Matrix** 网格中手动编辑 3×3 矩阵值，然后点击 **Save/Update Manual Parameters**。

## 5. 修改默认参数

您可以直接编辑源文件来永久更改默认值，免去每次启动 Dashboard 后重复填写的繁琐。

### 修改默认加载的范式

打开 `src/models/paradigm.py`，滚动至文件最底部的 `PARADIGM_REGISTRY` 字典：

```python
PARADIGM_REGISTRY: Dict[str, type] = {
    "Looming": LoomingParadigm,
    "ClassicLooming": ClassicLoomingParadigm,
    "OpticFlow": OpticFlowParadigm,
    "MovementTrace": MovementTraceParadigm,
    "Blank": BlankParadigm,
    "Grating": GratingParadigm,
    "SingleLooming": SingleLoomingParadigm,
}
```

Dashboard 默认读取该字典的**第一个键**。将最常用的范式移到第一行即可。例如，将默认范式改为 `Grating`：

```python
PARADIGM_REGISTRY: Dict[str, type] = {
    "Grating": GratingParadigm,           # <-- 现在默认加载此范式
    "Looming": LoomingParadigm,
    ...
}
```

### 修改全局默认参数（被试ID、分辨率、ITI/ISI 等）

打开 `src/ui/dashboard.py`，在 `_create_widgets` 方法中搜索对应的 `ctk.StringVar(value="...")`，直接修改 value 字符串。常见示例：

| 参数          | 位置（约）                                                | 当前默认值      | 修改为                             |
| ------------- | --------------------------------------------------------- | --------------- | ---------------------------------- |
| 被试 ID       | `self.subject_var = ctk.StringVar(value="cricket_001")`   | `"cricket_001"` | 您实验室的被试 ID                  |
| 分辨率        | `self.resolution_var = ctk.StringVar(value="3840,1080")`  | `"3840,1080"`   | 您的屏幕分辨率（如 `"1920,1080"`） |
| ITI 范围      | `self.iti_range_var = ctk.StringVar(value="60-90")`       | `"60-90"`       | 您的试次间隔（如 `"30-45"`）       |
| ISI 范围      | `self.isi_range_var = ctk.StringVar(value="300-300")`     | `"300-300"`     | 您的会话间隔                       |
| 观看距离      | `self.viewing_distance_var = ctk.StringVar(value="30.0")` | `"30.0"`        | 您的观看距离（cm）                 |
| 屏幕宽度 (cm) | `self.screen_width_cm_var = ctk.StringVar(value="53.0")`  | `"53.0"`        | 您的屏幕物理宽度（cm）             |

### 修改范式专属参数（对比度、空间频率、运动速度等）

打开 `src/models/paradigm.py`，找到目标范式类，定位其 `get_parameter_schema(cls)` 方法。每个参数是一个字典条目 — 修改其中的 `"default"` 值即可。以 Grating 的空间频率为例：

```python
"Spatial Freq (cpd)": {
    "type": "float",
    "default": 0.05,      # <-- 修改此处为您需要的默认值
    "min": 0.001,
    "max": 10.0,
    "label": "Spatial Frequency (cpd)",
},
```

## 6. 数据产出规范

双轨记录文件于 `data/` 目录自动生成，基于 `global_trial_id` 与时间戳对齐：

1. **`{Subject}_session_{n}_events.csv`** — 低频实验状态事件流。列：`event_name`、`timestamp`、`session_num`、`trial_in_session`、`global_trial_id`、`details`（JSON 序列化字典）。
2. **`{Subject}_session_{n}_kinematics.csv`** — 高频闭环遥测矩阵。列：`sys_time`、`ard_time`、`dx`、`dy`、`dz`、`stim_state`、`global_trial_id`。

两个文件共享 `global_trial_id` 作为关联键，用于将试次级事件与帧级运动学数据交叉引用。

## 7. 网页遥测镜像

Dashboard 会在一个独立守护进程（`src/core/web_telemetry.py`，FastAPI + uvicorn）中运行一个轻量**实时网页镜像**，将其自身状态推送到浏览器。同一局域网内的任何设备都可打开镜像页面 —— 无需先运行实验，配置与校准状态即刻可见。

### 访问方式

- 镜像地址显示在 Dashboard 状态栏中，例如 `Web: http://192.168.1.10:8000`。
- 服务绑定 `0.0.0.0:8000`（或 8000 起第一个空闲端口），前端为单文件页面（`src/ui/static/index.html`）。
- 网页头部提供 **Copy State JSON** 调试按钮，可一键复制当前完整状态。

### 显示内容

- **实时状态**：相位徽章、会话/试次进度（分段条）、完整硬件状态网格、工作进程状态与 Dashboard 状态行。
- **刺激孪生视图**：400×150 画布重放刺激渲染指令（`ui_twin`）。
- **运动轨迹**：150×150 画布绘制近期路径与当前朝向箭头，并显示 θ/ω/D 运动学指标。
- **校准**：实时原始 DX/DY/DZ 里程计、逐轴结果清单与手动 3×3 矩阵。
- **配置**：全部参数，含动态范式参数与运动学触发阈值。

### 数据协议

Dashboard 以最高 20 Hz 频率通过 WebSocket 端点 `/ws/full_state` 推送完整 `full_state` JSON 快照（`config` / `calibration` / `live` / `visual`）。前端通过 `requestAnimationFrame` 分批渲染，仅重写发生变化的 DOM 值。

### 注意事项

- 浏览器与实验机须处于同一网络。
- 前端通过 CDN 加载 Tailwind / Lucide / Google Fonts；在完全离线的网络中布局会降级，但数据仍实时更新。
- 网页进程为尽力而为：崩溃时绝不影响正在运行的实验，并会在约 2 秒内自愈。

---

# 第二部分 — 开发者指南

## 1. 框架扩展：添加新范式

扩展新实验范式无需修改底层渲染引擎或控制流代码。所有开发均限定在 `src/models/paradigm.py` 中完成。

### 步骤 1：继承基类

新建核心计算类并强制继承 `BaseParadigm` 抽象类：

```python
from src.models.paradigm import BaseParadigm

class MyParadigm(BaseParadigm):
    ...
```

### 步骤 2：定义前端映射接口

- **`get_available_patterns(cls)`**：返回该范式支持的具体模式名称列表（显示在 Dashboard 的 Pattern 下拉菜单中）。

```python
@classmethod
def get_available_patterns(cls) -> List[str]:
    return ["My Pattern A", "My Pattern B"]
```

- **`get_parameter_schema(cls)`**：声明动态 UI 参数配置字典。框架依据字典中的 `type` 字段自动渲染主控表单。支持的类型：`int`、`float`、`str`、`choice`、`bool`、`info`、`filepath`。

```python
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
        "Execution Mode": {
            "type": "choice",
            "default": "Auto",
            "choices": ["Auto", "Manual", "Kinematic"],
            "label": "Execution Mode",
        },
    }
```

### 步骤 3：实现核心生命周期

- **`generate_trials(self, pattern_key)`**：根据用户选择的模式，构建并返回当前 Session 的全体试次上下文配置（`List[dict]`）。

- **`prepare_trial(self, trial_context)`**：返回当前试次开始前需下发至硬件的初始化串口指令（如无则返回空字符串 `""`）。

- **`get_idle_frame(self, hw_telemetry)`**：输出 ITI/ISI 等空闲阶段的稳态渲染指令，需返回元组 `(cmds, telemetry_dict, sync_states)`。

- **`process_frame(self, elapsed_time, trial_context, hw_telemetry)`**：帧级闭环计算核心。根据当前时间戳与硬件遥测输入完成坐标更新，返回帧状态元组 `(is_done, cmds, telemetry_dict, sync_states)`。

### 步骤 4：返回标准渲染指令

上述生命周期中返回的 `cmds` 列表需使用以下支持的 `type` 字典：

| 类型            | 关键参数                                                        |
| --------------- | --------------------------------------------------------------- |
| `circle`        | `radius`, `pos`, `fillColor`, `lineColor`, `lineWidth`, `edges` |
| `rect`          | `width`, `height`, `pos`, `fillColor`, `lineColor`, `lineWidth` |
| `element_array` | `n_elements`, `xys`, `sizes`, `colors`, `opacities`             |

色彩空间采用 PsychoPy RGB 约定：`-1` = 纯黑，`0` = 中灰，`+1` = 纯白。

#### 同步块协议（光电标记）

> **架构说明**：旧版 `ScreenEnvironment` 类已废弃。底层 `CoreRenderer`（`src/core/render.py`）对光电标记与同步块实行**零感知** — 它仅盲绘收到的 `cmds` 指令。所有同步逻辑完全由范式（Paradigm）层封装，通过返回的指令包驱动。

每个范式负责在其 `cmds` 列表末尾追加正确数量的光电同步块。框架提供 `BaseParadigm._build_sync_markers(is_active, mode)` 作为共享工具方法，范式也可自行实现坐标计算逻辑。

**规范一：时钟与帧追踪**

范式类必须维护内部帧计数器以驱动帧率闪烁指示。在 `prepare_trial`（或试次初始化阶段）重置 `self._frame_counter = 0`，并在每帧 `process_frame` 调用时自增：

```python
def prepare_trial(self, trial_context):
    self._frame_counter = 0  # 试次开始时重置
    return ""

def process_frame(self, elapsed_time, trial_context, hw_telemetry):
    self._frame_counter += 1
    # ...
```

计数器驱动闪烁切换：`odd = self._frame_counter % 2 == 1`。

**规范二：通道物理对齐**

| 屏幕模式             | 色块数量 | 布局                                                 |
| -------------------- | -------- | ---------------------------------------------------- |
| **双屏（Surround）** | 4        | 左下外侧、左下内侧、右下内侧、右下外侧               |
| **单屏（Single）**   | 2        | 右下角：内侧（试次状态）+ 外侧（帧率闪烁），紧凑并排 |

- **双屏范式**必须在 `cmds` 末尾追加 4 个同步色块：最外侧色块随帧闪烁指示帧率，内侧色块常亮指示试次激活状态。
- **单屏范式**必须在 `cmds` 末尾追加恰好 2 个同步色块，**两个色块必须紧凑并排放置在屏幕的同一角落（右下角）**，内侧色块常亮指示试次状态，外侧色块随帧闪烁指示帧率。

```python
# 单屏范式：在 process_frame / get_idle_frame 中调用
sync = self._build_sync_markers(stim_active, "single")
# 双屏范式：在 process_frame / get_idle_frame 中调用
sync = self._build_sync_markers(stim_active, "dual")
```

**规范三：图层压栈顺序**

所有同步/光电 `rect` 指令**必须置于 `cmds` 列表的最末尾**。这确保其在绝对顶层绘制，不被任何刺激物背景、遮罩或叠加层遮挡。

```python
cmds = []  # 刺激物绘制指令
cmds.append({...})  # circle, rect, element_array 等

# --- 同步块必须在最后追加 ---
sync = self._build_sync_markers(is_active, "single")  # 或 "dual"
cmds.extend(sync)
return cmds
```

**标准参考实现**（`BaseParadigm._build_sync_markers`）：

```python
def _build_sync_markers(self, is_active: bool, mode: str) -> list[dict]:
    off, on = [-1, -1, -1], [1, 1, 1]  # PsychoPy RGB 色彩空间
    odd = (self._frame_counter % 2 == 1)
    margin, w, h = 10, 60, 60
    half_w, half_h = self._win_w / 2.0, self._win_h / 2.0

    if mode == "single":
        # 2 通道：右下角紧凑并排
        flash_color = on if (is_active and odd) else off
        active_color = on if is_active else off
        positions = [
            (half_w - margin - w * 1.5 - margin, -half_h + margin + h / 2),  # 内侧
            (half_w - margin - w / 2, -half_h + margin + h / 2),              # 外侧
        ]
        colors = [active_color, flash_color]
    elif mode == "dual":
        # 4 通道：左下角对 + 右下角对
        outer_color = on if (is_active and odd) else off
        inner_color = on if is_active else off
        positions = [
            (-half_w + margin + w / 2, -half_h + margin + h / 2),
            (-half_w + margin + w * 1.5 + margin, -half_h + margin + h / 2),
            (half_w - margin - w * 1.5 - margin, -half_h + margin + h / 2),
            (half_w - margin - w / 2, -half_h + margin + h / 2),
        ]
        colors = [outer_color, inner_color, inner_color, outer_color]

    cmds = []
    for i, (pos, color) in enumerate(zip(positions, colors)):
        cmds.append({
            "id": f"_sync_{i}", "type": "rect",
            "width": w, "height": h, "pos": pos,
            "fillColor": color, "lineColor": color, "lineWidth": 0,
        })
    return cmds
```

### 步骤 5：全局注册

新定义的范式类必须加入 `src/models/paradigm.py` 脚本底部的 `PARADIGM_REGISTRY` 字典进行注册，方可被主控面板解析调用：

```python
PARADIGM_REGISTRY: Dict[str, type] = {
    "Looming": LoomingParadigm,
    "ClassicLooming": ClassicLoomingParadigm,
    "OpticFlow": OpticFlowParadigm,
    "MovementTrace": MovementTraceParadigm,
    "Blank": BlankParadigm,
    "Grating": GratingParadigm,
    "SingleLooming": SingleLoomingParadigm,
    "MyParadigm": MyParadigm,  # <-- 在此注册
}
```

下次启动 Dashboard 时，新范式将出现在下拉菜单中。
