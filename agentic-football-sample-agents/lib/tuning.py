"""Deploy-time tunable tactical parameters (the autopilot's control surface).

autopilot.py rewrites lib/tuning.json between matches; each deploy ships the
file inside lib/ and agents overlay it onto their hard-coded OverrideConfig at
startup. Missing file / empty file / unknown keys = code defaults, so teams
without tuning behave exactly as before.

tuning.json shape (everything optional):

    {
      "global": {"press_bodies": 3, "longshot_max": 52.0},
      "GK":   {"always_blast": true},
      "DEF":  {},
      "MID":  {"outlet_min_gain": 10.0},
      "FWD1": {"wing_y": -14.0},
      "FWD2": {"wing_y": 14.0}
    }

Keys must match OverrideConfig field names; per-position overlays win over
"global". Numeric values are clamped to BOUNDS so a bad tuner run can never
push a parameter into nonsense territory.
"""

from __future__ import annotations

import json
import os
from dataclasses import fields, replace

_PATH = os.path.join(os.path.dirname(__file__), "tuning.json")

# Safety rails — the tuner (rules or LLM advisor) can only move parameters
# inside these ranges. Booleans and strings pass through untouched.
BOUNDS: dict[str, tuple[float, float]] = {
    "shoot_threshold": (35.0, 50.0),
    "longshot_max": (45.0, 58.0),
    "gk_out_dist": (8.0, 18.0),
    "blast_pressure_dist": (6.0, 16.0),
    "outlet_min_gain": (6.0, 20.0),
    "outlet_lane_radius": (3.0, 8.0),
    "press_bodies": (2, 4),
    "chase_radius": (5.0, 12.0),
    "anchor_slack": (8.0, 18.0),
    "mark_radius": (15.0, 30.0),
    "wing_y": (-18.0, 18.0),
}

_INT_KEYS = {"press_bodies"}


def _load(path: str = _PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


_DATA = _load()


def clamp(key: str, value):
    """Clamp numeric values into BOUNDS; cast int keys; pass others through."""
    if key in BOUNDS and isinstance(value, (int, float)) and not isinstance(value, bool):
        lo, hi = BOUNDS[key]
        value = max(lo, min(hi, value))
        return int(round(value)) if key in _INT_KEYS else float(value)
    return value


def apply_tuning(cfg, position_label: str, data: dict | None = None):
    """Overlay tuning (global, then position) onto an OverrideConfig copy."""
    if cfg is None:
        return None
    data = _DATA if data is None else data
    merged = {}
    merged.update(data.get("global") or {})
    merged.update(data.get(position_label) or {})
    if not merged:
        return cfg
    valid = {f.name for f in fields(cfg)}
    kwargs = {k: clamp(k, v) for k, v in merged.items() if k in valid}
    return replace(cfg, **kwargs) if kwargs else cfg


def get(key: str, default, data: dict | None = None):
    """Read a single global tuning value (used by state.py thresholds)."""
    data = _DATA if data is None else data
    value = (data.get("global") or {}).get(key, default)
    return clamp(key, value)
