# 模块 API 参考

## `loco_box.serial_bridge` — 串口桥接

```python
class SerialBridge:
    def __init__(self, port: str = "AUTO", baudrate: int = 9600)
    def connect(self) -> bool
    def disconnect(self)
    def is_connected(self) -> bool
    def send(self, key: str, hold_ms: int = 0) -> bool
    def press_key(self, key: str, hold_ms: int = 50) -> bool
    def mouse_left(self) -> bool
    def mouse_right(self) -> bool

    @staticmethod
    def find_arduino() -> Optional[str]
    @staticmethod
    def list_ports() -> list[str]
```

## `loco_box.monitor` — 监控线程

```python
class MonitorThread:
    POLL_INTERVAL = 0.3      # 轮询间隔（秒）
    CONFIRM_APPEAR = 4       # 出现确认次数
    CONFIRM_ABSENT = 3       # 消失确认次数

    def __init__(
        self,
        monitor_region: Region,      # 监控区域 {left, top, width, height}
        shot_region: Region,         # 截图区域
        matcher: WhiteTextMatcher,   # 白字匹配器
        delay_sec: float,            # 消失后截图延时
        threshold: float,            # 匹配阈值
        on_screenshot: Callable,     # 截图回调 (np.ndarray) -> None
        on_status: Callable,         # 状态回调 (str) -> None
        on_error: Callable,          # 错误回调 (str) -> None
        on_box_appear: Optional[Callable] = None,  # 盒子出现回调
    )
    def start(self)
    def stop(self)
    def is_running(self) -> bool
```

## `loco_box.matcher` — 白字匹配

```python
@dataclass
class MatchAnalysis:
    absent: bool           # 确认缺失
    strong_present: bool   # 强匹配
    weak_present: bool     # 弱匹配
    score: float           # 原始分数

class WhiteTextMatcher:
    def __init__(self, template_bgr: np.ndarray, brightness: int = 200)
    def analyze(self, frame_bgr: np.ndarray, threshold: float) -> MatchAnalysis

    @property
    def tpl_mask(self) -> np.ndarray   # 模板笔画掩码（灰度）
    @property
    def is_valid(self) -> bool         # 模板是否有效（≥3字符，≥40px笔画）
    @property
    def tpl_stroke_pixels(self) -> int # 模板笔画像素数
```

**辅助函数**：
```python
def extract_text_strokes(bgr: np.ndarray, brightness: int = 200)
    -> tuple[np.ndarray, dict]   # (笔画掩码, 元数据)
```

## `loco_box.image_ops` — 图像处理

```python
# 截图
def grab_region(region: Region) -> np.ndarray     # BGR 数组

# 颜色转换（BGR ↔ RGB ↔ Gray）
def bgra_to_bgr(bgra: np.ndarray) -> np.ndarray
def bgr_to_gray(bgr: np.ndarray) -> np.ndarray
def bgr_to_rgb(bgr: np.ndarray) -> np.ndarray
def rgb_to_bgr(rgb: np.ndarray) -> np.ndarray
def gray_to_bgr(gray: np.ndarray) -> np.ndarray

# 文件 I/O
def save_bgr(path, bgr: np.ndarray) -> None
def load_bgr(path) -> Optional[np.ndarray]

# 预览渲染
def render_bgr_preview(bgr, width, height, bg_hex) -> Image
def blank_preview(width, height, bg_hex) -> Image
def draw_text_top_right(image, text, margin, fill, font_size) -> Image

# 图像处理
def gaussian_blur_gray(gray: np.ndarray, radius: int = 2) -> np.ndarray
def edge_density(gray: np.ndarray) -> float
def lap_var(gray: np.ndarray) -> float
```

## `loco_box.settings` — 配置持久化

```python
@dataclass
class AppConfig:
    delay: str = "1"
    threshold: str = "0.45"
    brightness: str = "200"
    trigger_delay: str = "5.0"
    com_port: str = "AUTO"
    template_region: Optional[Region] = None
    region_b: Optional[Region] = None

def load_config() -> AppConfig
def save_config(cfg: AppConfig, template_bgr: Optional[np.ndarray] = None)
def load_template_image() -> Optional[np.ndarray]
```

## `loco_box.region_selector` — 区域框选

```python
def select_region(
    on_selected: Callable[[Region], None],
    on_cancel: Optional[Callable[[], None]] = None,
)
# 在独立线程启动全屏半透明框选窗口
```

## `loco_box.types` — 类型

```python
Region = dict   # {"left": int, "top": int, "width": int, "height": int}
```
