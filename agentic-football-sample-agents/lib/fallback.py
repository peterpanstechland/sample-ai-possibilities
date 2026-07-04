"""Fallback command factory for AI soccer position agents.

Each position defines a FallbackConfig, and build_fallback() returns a
fallback_commands(game_state, team_id, my_player_id) function.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable

from state import get_goal_positions, get_possession_info, dist, _player_idx, _is_my_team, resolve_holder


@dataclass
class FallbackConfig:
    """Per-position fallback behaviour."""

    # What to do when we have the ball
    possession_action: str = "PASS"
    """One of: GK_DISTRIBUTE, PASS, SHOOT_OR_PASS, SHOOT_OR_ADVANCE."""

    # Default position when nothing else applies
    default_x_factor: float = 0.0
    """Multiplied by my_goal_x or opp_goal_x (see default_x_ref)."""
    default_x_ref: str = "my_goal"
    """'my_goal' or 'opp_goal' — which goal x to multiply."""
    default_y: float | str = 0
    """Fixed y, or 'track_ball' to follow ball y * 0.5 (clamped ±10)."""

    # Pressing
    press_distance: float = 20.0
    press_intensity: float = 0.7
    press_duration: int = 3
    press_only_if_designated: bool = False
    """When True, only PRESS_BALL if I am my team's closest player to the ball.
    Non-pressing teammates fall through to off_ball_action instead — this stops
    five agents piling into the same PRESS every tick (real observed: 200+ press
    commands per match)."""

    off_ball_action: str = "MOVE_TO"
    """What non-designated players do when opponent has the ball: 'MOVE_TO'
    (current, drift to default position) or 'MARK' (tight-mark nearest opponent
    within 25 units)."""

    # Shoot threshold (distance to opp goal) — shoot-first policy:
    # any look inside 45 is a full-power shot at CENTER, never a dribble
    shoot_threshold: float = 45.0
    shoot_aim: str = "CENTER"
    shoot_power: float = 1.0

    # Advance with ball (for forwards)
    advance_x_factor: float = 0.6
    advance_y: float = 0.0
    advance_sprint: bool = True

    # Run into space when teammate has ball
    support_x_factor: float = 0.5
    support_y: float = 0.0
    support_sprint: bool = True

    # DEF-specific: mark opponents near our goal
    mark_threshold: float = 0.0
    """If > 0, mark the opponent closest to our goal when within this distance."""
    mark_tightness: str = "TIGHT"

    # Pass target filter (player IDs to exclude from pass targets)
    pass_exclude_ids: list[int] = field(default_factory=list)

    # Default stance when player not found
    default_stance: int = 0

    # Last-resort command — used when BOTH the LLM and fallback function crash.
    # Only commandType, playerId, parameters, and duration are used.
    last_resort_command_type: str = "SET_STANCE"
    last_resort_params: dict = field(default_factory=lambda: {"stance": 0})
    last_resort_duration: int = 0


# ---------------------------------------------------------------------------
# Pre-built configs for each position
# ---------------------------------------------------------------------------

GK_CONFIG = FallbackConfig(
    possession_action="GK_DISTRIBUTE",
    default_x_factor=0.9, default_x_ref="my_goal", default_y="track_ball",
    default_stance=2,
    last_resort_command_type="SET_STANCE", last_resort_params={"stance": 2},
)

DEF_CONFIG = FallbackConfig(
    possession_action="PASS",
    pass_exclude_ids=[0],  # don't pass back to GK
    default_x_factor=0.6, default_x_ref="my_goal", default_y=0,
    mark_threshold=30.0, mark_tightness="TIGHT",
    default_stance=2,
    last_resort_command_type="SET_STANCE", last_resort_params={"stance": 2},
)

MID_CONFIG = FallbackConfig(
    possession_action="SHOOT_OR_PASS",
    default_x_factor=0.5, default_x_ref="ball_x", default_y="track_ball_30",
    press_distance=20.0, press_intensity=0.6,
    shoot_threshold=45.0, shoot_aim="CENTER", shoot_power=1.0,
    default_stance=0,
    last_resort_command_type="PRESS_BALL", last_resort_params={"intensity": 0.5},
    last_resort_duration=3,
)

FWD1_CONFIG = FallbackConfig(
    possession_action="SHOOT_OR_ADVANCE",
    advance_x_factor=0.6, advance_y=-8, advance_sprint=True,
    support_x_factor=0.5, support_y=-10, support_sprint=True,
    default_x_factor=0.4, default_x_ref="opp_goal", default_y=-8,
    press_distance=20.0, press_intensity=0.7,
    default_stance=1,
    last_resort_command_type="PRESS_BALL", last_resort_params={"intensity": 0.6},
    last_resort_duration=3,
)

FWD2_CONFIG = FallbackConfig(
    possession_action="SHOOT_OR_ADVANCE",
    advance_x_factor=0.6, advance_y=8, advance_sprint=True,
    support_x_factor=0.5, support_y=10, support_sprint=True,
    default_x_factor=0.4, default_x_ref="opp_goal", default_y=8,
    press_distance=20.0, press_intensity=0.7,
    default_stance=1,
    last_resort_command_type="PRESS_BALL", last_resort_params={"intensity": 0.6},
    last_resort_duration=3,
)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_last_resort(cfg: FallbackConfig, player_id: int) -> dict:
    """Build the last-resort command dict from a FallbackConfig.

    This command is only used when BOTH the LLM and the fallback function crash.
    """
    return {
        "commandType": cfg.last_resort_command_type,
        "playerId": player_id,
        "parameters": dict(cfg.last_resort_params),
        "duration": cfg.last_resort_duration,
    }


def build_fallback(cfg: FallbackConfig) -> Callable[[dict, int, int], list[dict]]:
    """Return a fallback_commands(game_state, team_id, my_player_id) function."""

    def fallback_commands(game_state: dict, team_id: int, my_player_id: int) -> list[dict]:
        ball = game_state.get("ball", {})
        ball_pos = ball.get("position", {"x": 0, "y": 0})
        players = game_state.get("players", [])
        my_goal_x, opp_goal_x = get_goal_positions(team_id)

        me = next(
            (p for p in players if _player_idx(p) == my_player_id and _is_my_team(p, team_id)),
            None,
        )
        if not me:
            return [_cmd("SET_STANCE", my_player_id, team_id, {"stance": cfg.default_stance})]

        pos = me.get("position", {"x": 0, "y": 0})

        # --- I have the ball (team-aware: opp player with my idx doesn't count) ---
        if resolve_holder(ball, players) is me:
            return _on_ball(cfg, game_state, players, team_id, my_player_id, pos, my_goal_x, opp_goal_x)

        # --- DEF: mark dangerous opponent ---
        if cfg.mark_threshold > 0:
            opponents = [p for p in players if not _is_my_team(p, team_id)]
            if opponents:
                dangerous = min(opponents, key=lambda p: abs(p.get("position", {}).get("x", 0) - my_goal_x))
                if abs(dangerous.get("position", {}).get("x", 0) - my_goal_x) < cfg.mark_threshold:
                    return [_cmd("MARK", my_player_id, team_id,
                                 {"target_player_id": _player_idx(dangerous),
                                  "tightness": cfg.mark_tightness}, duration=3)]

        # --- Teammate has ball → support run (forwards) ---
        if cfg.possession_action in ("SHOOT_OR_ADVANCE",):
            _, _, we_have_ball = get_possession_info(ball, players, team_id)
            if we_have_ball:
                return [_cmd("MOVE_TO", my_player_id, team_id,
                             {"target_x": opp_goal_x * cfg.support_x_factor,
                              "target_y": cfg.support_y, "sprint": cfg.support_sprint})]

        # --- Press if close to ball and opponent has it ---
        _, _, we_have_ball = get_possession_info(ball, players, team_id)
        if not we_have_ball and dist(pos, ball_pos) < cfg.press_distance:
            # Convention-based orchestration: only the team's closest player
            # actually presses, everyone else marks / holds shape. Without this
            # we saw 200+ PRESS_BALL per match while conceding on the counter.
            if cfg.press_only_if_designated:
                team_mates = [p for p in players if _is_my_team(p, team_id)]
                closest = min(team_mates, key=lambda p: dist(p.get("position", {}), ball_pos))
                if _player_idx(closest) != my_player_id:
                    if cfg.off_ball_action == "MARK":
                        opponents = [p for p in players if not _is_my_team(p, team_id)]
                        near = [o for o in opponents if dist(o.get("position", {}), pos) < 25]
                        if near:
                            target = min(near, key=lambda p: dist(p.get("position", {}), pos))
                            return [_cmd("MARK", my_player_id, team_id,
                                         {"target_player_id": _player_idx(target),
                                          "tightness": "TIGHT"}, duration=3)]
                    tx, ty = _default_pos(cfg, my_goal_x, opp_goal_x, ball_pos)
                    return [_cmd("MOVE_TO", my_player_id, team_id,
                                 {"target_x": tx, "target_y": ty, "sprint": False})]
            return [_cmd("PRESS_BALL", my_player_id, team_id,
                         {"intensity": cfg.press_intensity}, duration=cfg.press_duration)]

        # --- Off-ball MARK (when opponent has ball but I'm out of press range) ---
        if not we_have_ball and cfg.off_ball_action == "MARK":
            opponents = [p for p in players if not _is_my_team(p, team_id)]
            near = [o for o in opponents if dist(o.get("position", {}), pos) < 25]
            if near:
                target = min(near, key=lambda p: dist(p.get("position", {}), pos))
                return [_cmd("MARK", my_player_id, team_id,
                             {"target_player_id": _player_idx(target),
                              "tightness": "TIGHT"}, duration=3)]

        # --- Default position ---
        tx, ty = _default_pos(cfg, my_goal_x, opp_goal_x, ball_pos)
        return [_cmd("MOVE_TO", my_player_id, team_id,
                      {"target_x": tx, "target_y": ty, "sprint": False})]

    return fallback_commands


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cmd(cmd_type: str, pid: int, tid: int, params: dict, duration: int = 0) -> dict:
    return {"commandType": cmd_type, "playerId": pid, "teamId": tid,
            "parameters": params, "duration": duration}


def _on_ball(cfg, game_state, players, team_id, my_player_id, pos, my_goal_x, opp_goal_x):
    """Handle possession for all position types."""
    if cfg.possession_action == "GK_DISTRIBUTE":
        teammates = [p for p in players if _is_my_team(p, team_id) and _player_idx(p) != my_player_id]
        if teammates:
            nearest = min(teammates, key=lambda p: dist(p.get("position", {}), pos))
            return [_cmd("GK_DISTRIBUTE", my_player_id, team_id,
                         {"target_player_id": _player_idx(nearest), "method": "THROW"})]
        return [_cmd("GK_DISTRIBUTE", my_player_id, team_id,
                     {"target_player_id": 1, "method": "THROW"})]

    if cfg.possession_action == "PASS":
        exclude = set(cfg.pass_exclude_ids) | {my_player_id}
        teammates = [p for p in players if _is_my_team(p, team_id) and _player_idx(p) not in exclude]
        if teammates:
            target = min(teammates, key=lambda p: dist(p.get("position", {}), pos))
            return [_cmd("PASS", my_player_id, team_id,
                         {"target_player_id": _player_idx(target), "type": "GROUND"})]
        return [_cmd("PASS", my_player_id, team_id,
                     {"target_player_id": 2, "type": "GROUND"})]

    if cfg.possession_action == "SHOOT_OR_PASS":
        # <= to match the prompt rule "distOppGoal<=45: SHOOT"
        if abs(pos.get("x", 0) - opp_goal_x) <= cfg.shoot_threshold:
            return [_cmd("SHOOT", my_player_id, team_id,
                         {"aim_location": cfg.shoot_aim, "power": cfg.shoot_power})]
        forwards = [p for p in players if _is_my_team(p, team_id) and _player_idx(p) in (3, 4)]
        if forwards:
            target = min(forwards, key=lambda p: abs(p.get("position", {}).get("x", 0) - opp_goal_x))
            return [_cmd("PASS", my_player_id, team_id,
                         {"target_player_id": _player_idx(target), "type": "GROUND"})]
        return [_cmd("PASS", my_player_id, team_id,
                     {"target_player_id": 3, "type": "GROUND"})]

    if cfg.possession_action == "SHOOT_OR_ADVANCE":
        # <= to match the prompt rule "distOppGoal<=45: SHOOT"
        if abs(pos.get("x", 0) - opp_goal_x) <= cfg.shoot_threshold:
            return [_cmd("SHOOT", my_player_id, team_id,
                         {"aim_location": cfg.shoot_aim, "power": cfg.shoot_power})]
        return [_cmd("MOVE_TO", my_player_id, team_id,
                     {"target_x": opp_goal_x * cfg.advance_x_factor,
                      "target_y": cfg.advance_y, "sprint": cfg.advance_sprint})]

    # Shouldn't reach here
    return [_cmd("SET_STANCE", my_player_id, team_id, {"stance": 0})]


def _default_pos(cfg, my_goal_x, opp_goal_x, ball_pos):
    """Calculate default x,y from config."""
    if cfg.default_x_ref == "my_goal":
        tx = my_goal_x * cfg.default_x_factor
    elif cfg.default_x_ref == "opp_goal":
        tx = opp_goal_x * cfg.default_x_factor
    elif cfg.default_x_ref == "ball_x":
        tx = ball_pos.get("x", 0) * cfg.default_x_factor
    else:
        tx = 0

    if cfg.default_y == "track_ball":
        ty = max(-10, min(10, ball_pos.get("y", 0) * 0.5))
    elif cfg.default_y == "track_ball_30":
        ty = ball_pos.get("y", 0) * 0.3
    else:
        ty = cfg.default_y

    return tx, ty
