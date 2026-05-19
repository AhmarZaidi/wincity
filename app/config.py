"""
Configuration and state persistence for WinCity.
All runtime globals live here so other modules can do `import config; config.X`.
"""
import json
import pathlib
import sys

# ── Paths ─────────────────────────────────────────────────────────────────────
# When frozen by PyInstaller (--onefile), __file__ is inside a temp extraction
# dir; use the exe location instead so data/ is found next to the exe.
_BASE_DIR    = (pathlib.Path(sys.executable).parent
                if getattr(sys, "frozen", False)
                else pathlib.Path(__file__).parent.parent)
_DATA_DIR    = _BASE_DIR / "data"
_CONFIG_FILE = _DATA_DIR / "config.json"
_STATE_FILE  = _DATA_DIR / "state.json"

# ── Runtime constants (overwritten by load_config) ────────────────────────────
WIDGET_WIDTH       = 55
WIDGET_HEIGHT      = 25
OFFSET_FROM_RIGHT  = 130
OFFSET_FROM_TOP    = None
UPDATE_INTERVAL    = 10
LOW_PCT            = 10
CORNER_RADIUS      = 8
FILL_PADDING       = 0
FILL_RIGHT_EXTEND  = 0
FONT_SIZE          = 22
RENDER_SCALE       = 8
OUTLINE_WIDTH      = 1
VISIBILITY_POLL_MS = 500
POPUP_Y_OFFSET      = 20
POPUP_CORNER_RADIUS = 12
POPUP_TITLE_SIZE    = 16
POPUP_TEXT_SIZE     = 12
POPUP_ICON_SIZE     = 16

_DEFAULT_CONFIG = {
    "WIDGET_WIDTH": 55, "WIDGET_HEIGHT": 25, "OFFSET_FROM_RIGHT": 130,
    "OFFSET_FROM_TOP": None, "UPDATE_INTERVAL": 10, "LOW_PCT": 10,
    "VISIBILITY_POLL_MS": 500, "CORNER_RADIUS": 8, "FILL_PADDING": 0,
    "FILL_RIGHT_EXTEND": 0, "FONT_SIZE": 22, "RENDER_SCALE": 8,
    "OUTLINE_WIDTH": 1, "POPUP_Y_OFFSET": 20, "POPUP_CORNER_RADIUS": 12,
    "POPUP_TITLE_SIZE": 16, "POPUP_TEXT_SIZE": 12, "POPUP_ICON_SIZE": 16,
    # Popup rows — order = display order; set "visible": false to hide.
    # The "graph" entry controls where the history chart is injected.
    "rows": [
        {"id": "status",      "visible": True},
        {"id": "power_mode",  "visible": True},
        {"id": "percentage",  "visible": True},
        {"id": "health",      "visible": True},
        {"id": "time",        "visible": True},
        {"id": "rate",        "visible": True},
        {"id": "elapsed",     "visible": True},
        {"id": "graph",       "visible": True},
        {"id": "screen_on",   "visible": False},
        {"id": "cycle_count", "visible": False},
        {"id": "temperature", "visible": False},
    ],
    # Theme colors — '#rrggbb' (RGB) or '#rrggbbaa' (RGBA, last 2 digits = alpha).
    "colors": {
        "dark": {
            "bg": "#1c1c1c", "fg": "#ffffff", "fg2": "#9d9d9d",
            "border": "#3c3c3c", "icon": "#c8c8c8", "danger": "#e04040",
            "hover": "#2d2d2d", "widget_body": "#1a1a1a", "widget_nub": "#aaaaaa",
            "widget_outline": "#888888", "widget_text": "#ffffff",
            "graph_container": "#2c2c32",
        },
        "light": {
            "bg": "#f9f9f9", "fg": "#1a1a1a", "fg2": "#5c5c5c",
            "border": "#dedede", "icon": "#555555", "danger": "#c42b1c",
            "hover": "#ebebeb", "widget_body": "#ffffff", "widget_nub": "#1e1e1e",
            "widget_outline": "#1e1e1e", "widget_text": "#1a1a1a",
            "graph_container": "#cdcfd7",
        },
        "graph": {
            "charging_fill": "#0078d45f", "charging_line": "#008ce6eb",
            "low_fill": "#f0be2864",      "low_line": "#d7a00ff0",
            "normal_fill": "#4cbb6464",   "normal_line": "#28aa46f0",
        },
        "widget": {
            "fill_charging": "#3296f0", "fill_low": "#dc3232",
            "fill_saver": "#f0be28",    "fill_normal": "#3cc850",
        },
    },
}


def _colors_to_tuples(d):
    """Convert '#rrggbb' / '#rrggbbaa' / RGB lists to PIL-compatible tuples."""
    result = {}
    for k, v in d.items():
        if isinstance(v, str) and v.startswith("#"):
            h = v.lstrip("#")
            if len(h) in (6, 8):
                result[k] = tuple(int(h[i:i + 2], 16) for i in range(0, len(h), 2))
            else:
                result[k] = v
        elif isinstance(v, list):
            result[k] = tuple(v)
        else:
            result[k] = v
    return result


# ── Color / row globals (overwritten by load_config) ──────────────────────────
ROWS_CONFIG   = list(_DEFAULT_CONFIG["rows"])
COLORS_DARK   = _colors_to_tuples(_DEFAULT_CONFIG["colors"]["dark"])
COLORS_LIGHT  = _colors_to_tuples(_DEFAULT_CONFIG["colors"]["light"])
COLORS_GRAPH  = _colors_to_tuples(_DEFAULT_CONFIG["colors"]["graph"])
COLORS_WIDGET = _colors_to_tuples(_DEFAULT_CONFIG["colors"]["widget"])


# ── Config I/O ────────────────────────────────────────────────────────────────

def load_config():
    """Read data/config.json; create with defaults if missing. Updates module globals."""
    global WIDGET_WIDTH, WIDGET_HEIGHT, OFFSET_FROM_RIGHT, OFFSET_FROM_TOP
    global UPDATE_INTERVAL, LOW_PCT, VISIBILITY_POLL_MS
    global CORNER_RADIUS, FILL_PADDING, FILL_RIGHT_EXTEND, FONT_SIZE, RENDER_SCALE, OUTLINE_WIDTH
    global POPUP_Y_OFFSET, POPUP_CORNER_RADIUS, POPUP_TITLE_SIZE, POPUP_TEXT_SIZE, POPUP_ICON_SIZE
    global ROWS_CONFIG, COLORS_DARK, COLORS_LIGHT, COLORS_GRAPH, COLORS_WIDGET

    _DATA_DIR.mkdir(exist_ok=True)
    if not _CONFIG_FILE.exists():
        try:
            _CONFIG_FILE.write_text(json.dumps(_DEFAULT_CONFIG, indent=2), encoding="utf-8")
        except Exception:
            pass
        return

    try:
        cfg = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return

    def _gi(key, default):
        v = cfg.get(key)
        return int(v) if v is not None else default

    WIDGET_WIDTH        = _gi("WIDGET_WIDTH",        WIDGET_WIDTH)
    wh                  = cfg.get("WIDGET_HEIGHT")
    WIDGET_HEIGHT       = int(wh) if wh is not None else None
    OFFSET_FROM_RIGHT   = _gi("OFFSET_FROM_RIGHT",   OFFSET_FROM_RIGHT)
    ot                  = cfg.get("OFFSET_FROM_TOP")
    OFFSET_FROM_TOP     = int(ot) if ot is not None else None
    UPDATE_INTERVAL     = _gi("UPDATE_INTERVAL",     UPDATE_INTERVAL)
    LOW_PCT             = _gi("LOW_PCT",             LOW_PCT)
    VISIBILITY_POLL_MS  = _gi("VISIBILITY_POLL_MS",  VISIBILITY_POLL_MS)
    CORNER_RADIUS       = _gi("CORNER_RADIUS",       CORNER_RADIUS)
    FILL_PADDING        = _gi("FILL_PADDING",        FILL_PADDING)
    FILL_RIGHT_EXTEND   = _gi("FILL_RIGHT_EXTEND",   FILL_RIGHT_EXTEND)
    FONT_SIZE           = _gi("FONT_SIZE",           FONT_SIZE)
    RENDER_SCALE        = _gi("RENDER_SCALE",        RENDER_SCALE)
    OUTLINE_WIDTH       = _gi("OUTLINE_WIDTH",       OUTLINE_WIDTH)
    POPUP_Y_OFFSET      = _gi("POPUP_Y_OFFSET",      POPUP_Y_OFFSET)
    POPUP_CORNER_RADIUS = _gi("POPUP_CORNER_RADIUS", POPUP_CORNER_RADIUS)
    POPUP_TITLE_SIZE    = _gi("POPUP_TITLE_SIZE",    POPUP_TITLE_SIZE)
    POPUP_TEXT_SIZE     = _gi("POPUP_TEXT_SIZE",     POPUP_TEXT_SIZE)
    POPUP_ICON_SIZE     = _gi("POPUP_ICON_SIZE",     POPUP_ICON_SIZE)

    rows = cfg.get("rows")
    if isinstance(rows, list):
        ROWS_CONFIG = rows

    colors = cfg.get("colors", {})
    if isinstance(colors, dict):
        if "dark"   in colors: COLORS_DARK   = _colors_to_tuples(colors["dark"])
        if "light"  in colors: COLORS_LIGHT  = _colors_to_tuples(colors["light"])
        if "graph"  in colors: COLORS_GRAPH  = _colors_to_tuples(colors["graph"])
        if "widget" in colors: COLORS_WIDGET = _colors_to_tuples(colors["widget"])


# ── State I/O ────────────────────────────────────────────────────────────────

def load_state():
    """Return parsed state.json as a dict, or {} on failure."""
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_state(data):
    """Atomically write state to data/state.json (tmp → rename)."""
    try:
        _DATA_DIR.mkdir(exist_ok=True)
        tmp = _STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(_STATE_FILE)
    except Exception:
        pass
