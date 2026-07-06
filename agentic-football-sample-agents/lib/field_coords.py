"""Engine → logical field coordinate mapping for Agentic Football 5v5.

Live gameState positions (logged as mx/my/bx/by) arrive in compact engine units
(telemetry tops out near x±7, y±3.5). Agent prompts, parsing clamps, and
distance helpers use the logical pitch: x±55, y±30 (110×60).
"""

from __future__ import annotations

FIELD_X_HALF = 55.0
FIELD_Y_HALF = 30.0
ENGINE_X_HALF = 7.0
ENGINE_Y_HALF = 3.5

SCALE_X = FIELD_X_HALF / ENGINE_X_HALF
SCALE_Y = FIELD_Y_HALF / ENGINE_Y_HALF


def engine_to_field_x(x: float) -> float:
    return x * SCALE_X


def engine_to_field_y(y: float) -> float:
    return y * SCALE_Y


def engine_to_field(x: float, y: float) -> tuple[float, float]:
    return engine_to_field_x(x), engine_to_field_y(y)


def field_definition() -> dict:
    """Canonical logical pitch for maps and stats."""
    return {
        "x_min": -FIELD_X_HALF,
        "x_max": FIELD_X_HALF,
        "y_min": -FIELD_Y_HALF,
        "y_max": FIELD_Y_HALF,
        "length": FIELD_X_HALF * 2,
        "width": FIELD_Y_HALF * 2,
        "label": "5v5",
        "goal_x_own": -FIELD_X_HALF,
        "goal_x_opp": FIELD_X_HALF,
        "center_circle_r": 9.0,
        "box_depth": 16.5,
        "box_half_width": 18.0,
        "goal_half_width": 7.0,
        "engine_half_x": ENGINE_X_HALF,
        "engine_half_y": ENGINE_Y_HALF,
        "scale_x": SCALE_X,
        "scale_y": SCALE_Y,
    }
